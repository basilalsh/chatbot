import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../lib/types";
import { detectLang, extractPartialAnswer, uid } from "../lib/utils";

const MAX_HISTORY = 12;
const CACHE_LIMIT = 50;

interface UseChatOpts {
  initialMessages?: ChatMessage[];
  /** Called once (on first user message) with a title derived from that message. */
  onTitle?: (title: string) => void;
  /** Called when a response turn fully completes. */
  onPersist?: (messages: ChatMessage[]) => void;
  /**
   * Increment this to clear the client-side answer cache
   * (e.g. after a document reindex completes in DocumentManager).
   */
  cacheVersion?: number;
}

export function useChat(opts?: UseChatOpts) {
  const [messages, setMessages] = useState<ChatMessage[]>(opts?.initialMessages ?? []);
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const historyRef = useRef<{ role: string; content: string }[]>([]);
  const cacheRef = useRef<Map<string, ChatMessage>>(new Map());
  const titleSetRef = useRef(false);

  // Keep callback refs stable so useCallback([]) never goes stale
  const onTitleRef = useRef(opts?.onTitle);
  const onPersistRef = useRef(opts?.onPersist);
  onTitleRef.current = opts?.onTitle;
  onPersistRef.current = opts?.onPersist;

  // Clear per-session answer cache whenever a document reindex completes.
  const cacheVersion = opts?.cacheVersion ?? 0;
  const prevCacheVersionRef = useRef(cacheVersion);
  useEffect(() => {
    if (prevCacheVersionRef.current !== cacheVersion) {
      prevCacheVersionRef.current = cacheVersion;
      cacheRef.current.clear();
    }
  }, [cacheVersion]);

  // Reconstruct conversation history from loaded messages on mount
  useEffect(() => {
    const init = opts?.initialMessages;
    if (!init?.length) return;
    const hist: { role: string; content: string }[] = [];
    for (const m of init) {
      if (!m.isStreaming && m.content) {
        hist.push({ role: m.role, content: m.content.slice(0, 500) });
      }
    }
    historyRef.current = hist.slice(-MAX_HISTORY);
    // Mark title as already set for loaded conversations
    titleSetRef.current = true;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Persist when a loading turn completes (isLoading: true → false)
  const prevIsLoadingRef = useRef(false);
  useEffect(() => {
    if (prevIsLoadingRef.current && !isLoading && messages.length > 0) {
      onPersistRef.current?.(messages);
    }
    prevIsLoadingRef.current = isLoading;
  }, [isLoading, messages]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(async (text: string) => {
    const question = text.trim();
    if (!question) return;

    // Fire onTitle once per conversation (first user message)
    if (!titleSetRef.current) {
      titleSetRef.current = true;
      onTitleRef.current?.(question.slice(0, 60));
    }

    const cacheKey = question.toLowerCase().replace(/\s+/g, " ");
    const now = Date.now();
    const userMsg: ChatMessage = { id: uid(), role: "user", content: question, createdAt: now };

    // Check cache
    if (cacheRef.current.has(cacheKey)) {
      const cached = cacheRef.current.get(cacheKey)!;
      const cachedCopy: ChatMessage = { ...cached, id: uid() };
      setMessages((prev) => [...prev, userMsg, cachedCopy]);
      pushHistory(question, cached.content);
      return;
    }

    // Add user message + streaming placeholder
    const assistantId = uid();
    const placeholder: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: now,
    };
    setMessages((prev) => [...prev, userMsg, placeholder]);
    setIsLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/ask-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          history: historyRef.current.slice(-6),
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Server error" }));
        updateAssistant(assistantId, {
          content: err.error || "Something went wrong.",
          isStreaming: false,
        });
        return;
      }

      const contentType = res.headers.get("content-type") || "";

      // Non-streaming JSON response (greetings, FAQ, etc.)
      if (contentType.includes("application/json")) {
        const data = await res.json();
        const msg: Partial<ChatMessage> = {
          content: data.answer || "",
          sources: data.sources || [],
          followUps: data.follow_up_questions || [],
          language: data.language || detectLang(data.answer || ""),
          confidence: data.confidence,
          isStreaming: false,
        };
        updateAssistant(assistantId, msg);
        cacheResponse(cacheKey, assistantId, msg);
        pushHistory(question, data.answer || "");
        return;
      }

      // SSE streaming
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let rawAnswer = "";
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let event: any;
          try {
            event = JSON.parse(line.slice(6));
          } catch {
            continue;
          }

          if (event.token) {
            rawAnswer += event.token;
            const display = extractPartialAnswer(rawAnswer);
            updateAssistant(assistantId, { content: display });
          }

          if (event.replace) {
            rawAnswer = event.replace;
            updateAssistant(assistantId, { content: event.replace });
          }

          if (event.error) {
            updateAssistant(assistantId, { content: event.error, isStreaming: false });
          }

          if (event.done) {
            const parsed = extractPartialAnswer(rawAnswer);
            const lang = event.language || detectLang(rawAnswer);
            const finalData: Partial<ChatMessage> = {
              content: parsed,
              sources: event.sources || [],
              followUps: event.follow_up_questions || [],
              language: lang,
              confidence: event.confidence,
              isStreaming: false,
            };
            updateAssistant(assistantId, finalData);
            cacheResponse(cacheKey, assistantId, finalData);
            pushHistory(question, parsed);
          }
        }
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        updateAssistant(assistantId, { isStreaming: false });
      } else {
        updateAssistant(assistantId, {
          content: err.message || "Network error.",
          isStreaming: false,
        });
      }
    } finally {
      setIsLoading(false);
      abortRef.current = null;
    }
  }, []);

  function updateAssistant(id: string, patch: Partial<ChatMessage>) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...patch } : m))
    );
  }

  function pushHistory(question: string, answer: string) {
    historyRef.current.push({ role: "user", content: question });
    historyRef.current.push({ role: "assistant", content: answer });
    if (historyRef.current.length > MAX_HISTORY) {
      historyRef.current = historyRef.current.slice(-MAX_HISTORY);
    }
  }

  function cacheResponse(key: string, id: string, data: Partial<ChatMessage>) {
    if (cacheRef.current.size >= CACHE_LIMIT) {
      const first = cacheRef.current.keys().next().value;
      if (first) cacheRef.current.delete(first);
    }
    cacheRef.current.set(key, { id, role: "assistant", content: "", ...data } as ChatMessage);
  }

  return { messages, isLoading, send, stop };
}

