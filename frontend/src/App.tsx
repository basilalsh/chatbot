import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ThemeProvider } from "./hooks/useTheme";
import { useChat } from "./hooks/useChat";
import { useConversations } from "./hooks/useConversations";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import EmptyState from "./components/EmptyState";
import ChatBubble from "./components/ChatBubble";
import TypingIndicator from "./components/TypingIndicator";
import ChatInput from "./components/ChatInput";
import DocumentManager from "./components/DocumentManager";
import { ToasterProvider } from "./components/Toaster";
import type { ChatMessage } from "./lib/types";

// ── Inner chat view (re-mounts when conversation switches via `key`) ──────────
interface ChatAreaProps {
  initialMessages: ChatMessage[];
  onTitle: (title: string) => void;
  onPersist: (messages: ChatMessage[]) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onOpenDocuments: () => void;
  cacheVersion: number;
}

function ChatArea({ initialMessages, onTitle, onPersist, sidebarOpen, onToggleSidebar, onOpenDocuments, cacheVersion }: ChatAreaProps) {
  const { messages, isLoading, send, stop } = useChat({ initialMessages, onTitle, onPersist, cacheVersion });
  const scrollRef = useRef<HTMLDivElement>(null);

  // Abort stream on unmount (conversation switch / delete)
  useEffect(() => () => { stop(); }, [stop]);

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const hasMessages = messages.length > 0;
  const showTyping = isLoading && !messages.some((m) => m.isStreaming);

  return (
    <div className="flex flex-col h-dvh bg-gray-50 dark:bg-[#0c0a0f] transition-colors duration-300">
      <Header onToggleSidebar={onToggleSidebar} onOpenDocuments={onOpenDocuments} />

      {/* Chat body */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto flex flex-col">
        {!hasMessages ? (
          <EmptyState onSuggestion={send} />
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-4 w-full">
            <AnimatePresence mode="popLayout">
              {messages.map((msg) => (
                <ChatBubble key={msg.id} message={msg} onFollowUp={send} />
              ))}
            </AnimatePresence>
            <AnimatePresence>
              {showTyping && <TypingIndicator />}
            </AnimatePresence>
          </div>
        )}
      </div>

      <ChatInput onSend={send} onStop={stop} isLoading={isLoading} />
      <p className="text-center text-[10px] text-brand-400/50 dark:text-white/40 pb-2 select-none">
        Powered by Basil
      </p>
    </div>
  );
}

// ── Root app ──────────────────────────────────────────────────────────────────
function AppContent() {
  const convStore = useConversations();

  // Sidebar open by default on desktop, closed on mobile
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [docsOpen, setDocsOpen] = useState(false);
  const [reindexVersion, setReindexVersion] = useState(0);

  // chatKey controls ChatArea remount (new messages loaded on switch)
  const [chatKey, setChatKey] = useState(() => convStore.activeId ?? "new");

  // Tracks which conversation the current in-progress chat belongs to
  const currentConvIdRef = useRef<string | null>(convStore.activeId);

  // ── Sidebar actions ──────────────────────────────────────────────────────
  const handleNewChat = useCallback(() => {
    convStore.newChat();
    currentConvIdRef.current = null;
    setChatKey("new-" + Date.now());
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [convStore]);

  const handleSelect = useCallback((id: string) => {
    convStore.select(id);
    currentConvIdRef.current = id;
    setChatKey(id);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [convStore]);

  const handleDelete = useCallback((id: string) => {
    convStore.deleteConv(id);
    if (id === currentConvIdRef.current) {
      currentConvIdRef.current = null;
      setChatKey("new-" + Date.now());
    }
  }, [convStore]);

  // ── Chat callbacks ───────────────────────────────────────────────────────
  const handleTitle = useCallback((title: string) => {
    const id = currentConvIdRef.current;
    if (!id) {
      // New chat — auto-create conversation with this title
      const newId = convStore.createNew(title);
      currentConvIdRef.current = newId;
    } else {
      // Only update title on the first message of an existing conversation
      const conv = convStore.conversations.find((c) => c.id === id);
      if (conv && conv.messages.length === 0) {
        convStore.setTitle(id, title);
      }
    }
  }, [convStore]);

  const handlePersist = useCallback((messages: ChatMessage[]) => {
    const id = currentConvIdRef.current;
    if (id) convStore.saveMessages(id, messages);
  }, [convStore]);

  const initialMessages = convStore.activeConversation?.messages ?? [];

  return (
    <div className="relative">
      <Sidebar
        open={sidebarOpen}
        conversations={convStore.conversations}
        activeId={convStore.activeId}
        onNew={handleNewChat}
        onSelect={handleSelect}
        onDelete={handleDelete}
        onRename={convStore.setTitle}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main content — shifts right on desktop when sidebar is open */}
      <div
        className="transition-[margin-left] duration-300 ease-in-out"
        style={{ marginLeft: sidebarOpen ? "260px" : 0 }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={chatKey}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            <ChatArea
              initialMessages={initialMessages}
              onTitle={handleTitle}
              onPersist={handlePersist}
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen((v) => !v)}
              onOpenDocuments={() => setDocsOpen(true)}
              cacheVersion={reindexVersion}
            />
          </motion.div>
        </AnimatePresence>
      </div>

      <DocumentManager open={docsOpen} onClose={() => setDocsOpen(false)} onReindexComplete={() => setReindexVersion((v) => v + 1)} />
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <ToasterProvider>
        <AppContent />
      </ToasterProvider>
    </ThemeProvider>
  );
}
