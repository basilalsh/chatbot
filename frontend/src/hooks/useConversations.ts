import { useCallback, useState } from "react";
import type { ChatMessage, Conversation } from "../lib/types";
import { uid } from "../lib/utils";

const STORAGE_KEY = "dic-conversations";
const MAX_CONVS = 100;

function loadConvs(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Conversation[];
  } catch {}
  return [];
}

function persist(convs: Conversation[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(convs));
  } catch {}
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>(loadConvs);
  const [activeId, setActiveId] = useState<string | null>(
    () => loadConvs()[0]?.id ?? null
  );

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;

  const select = useCallback((id: string) => setActiveId(id), []);

  const newChat = useCallback(() => setActiveId(null), []);

  /** Creates a new conversation, sets it active, returns the new id. */
  const createNew = useCallback((title?: string): string => {
    const id = uid();
    const conv: Conversation = {
      id,
      title: title?.trim() || "New conversation",
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setConversations((prev) => {
      const next = [conv, ...prev].slice(0, MAX_CONVS);
      persist(next);
      return next;
    });
    setActiveId(id);
    return id;
  }, []);

  const deleteConv = useCallback((id: string) => {
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== id);
      persist(next);
      return next;
    });
    // If we deleted the active one, switch to the next available
    setActiveId((cur) => {
      if (cur !== id) return cur;
      const remaining = loadConvs().filter((c) => c.id !== id);
      return remaining[0]?.id ?? null;
    });
  }, []);

  const saveMessages = useCallback((id: string, messages: ChatMessage[]) => {
    setConversations((prev) => {
      const exists = prev.some((c) => c.id === id);
      if (!exists) return prev; // conversation was deleted, ignore
      const next = prev.map((c) =>
        c.id === id ? { ...c, messages, updatedAt: Date.now() } : c
      );
      persist(next);
      return next;
    });
  }, []);

  const setTitle = useCallback((id: string, title: string) => {
    setConversations((prev) => {
      const next = prev.map((c) => (c.id === id ? { ...c, title } : c));
      persist(next);
      return next;
    });
  }, []);

  return {
    conversations,
    activeId,
    activeConversation,
    select,
    newChat,
    createNew,
    deleteConv,
    saveMessages,
    setTitle,
  };
}
