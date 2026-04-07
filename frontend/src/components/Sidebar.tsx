import { motion, AnimatePresence } from "framer-motion";
import { Plus, Trash2, MessageSquare, X, Pencil, Check } from "lucide-react";
import { useRef, useState } from "react";
import type { Conversation } from "../lib/types";
import { timeAgo } from "../lib/utils";

interface Props {
  open: boolean;
  conversations: Conversation[];
  activeId: string | null;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onClose: () => void;
}

export default function Sidebar({
  open,
  conversations,
  activeId,
  onNew,
  onSelect,
  onDelete,
  onRename,
  onClose,
}: Props) {
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <>
      {/* Mobile backdrop */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/40 z-30 md:hidden"
            onClick={onClose}
          />
        )}
      </AnimatePresence>

      {/* Sidebar panel */}
      <motion.aside
        initial={false}
        animate={{ x: open ? 0 : -280 }}
        transition={{ type: "spring", damping: 30, stiffness: 280, mass: 0.8 }}
        className="fixed left-0 top-0 h-dvh w-[260px] z-40 bg-white dark:bg-[#0f0c14] border-r border-brand-200/50 dark:border-white/[0.06] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-brand-200/40 dark:border-white/[0.05]">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-500/70 dark:text-white/35">
            Conversations
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-brand-400 hover:text-brand-700 dark:text-white/35 dark:hover:text-white/70 transition-colors cursor-pointer"
            title="Close sidebar"
          >
            <X size={15} />
          </button>
        </div>

        {/* New Chat button */}
        <div className="px-3 pt-3 pb-2">
          <motion.button
            onClick={onNew}
            whileHover={{ scale: 1.02, y: -1 }}
            whileTap={{ scale: 0.97 }}
            transition={{ type: "spring", stiffness: 400, damping: 22 }}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-br from-brand-700 to-brand-900 hover:from-brand-600 hover:to-brand-800 text-white transition-colors cursor-pointer shadow-md shadow-brand-900/20"
          >
            <Plus size={15} />
            New Chat
          </motion.button>
        </div>

        {/* Conversation list */}
        <div className="flex-1 overflow-y-auto px-2 pt-1 pb-4">
          {sorted.length === 0 ? (
            <p className="text-center text-[11px] text-brand-400/50 dark:text-white/25 mt-10 px-4 leading-relaxed">
              Your conversations will appear here
            </p>
          ) : (
            <div className="space-y-0.5">
              {sorted.map((conv, index) => (
                <ConvItem
                  key={conv.id}
                  index={index}
                  conv={conv}
                  isActive={conv.id === activeId}
                  onSelect={() => onSelect(conv.id)}
                  onDelete={(e) => {
                    e.stopPropagation();
                    onDelete(conv.id);
                  }}
                  onRename={(title) => onRename(conv.id, title)}
                />
              ))}
            </div>
          )}
        </div>
      </motion.aside>
    </>
  );
}

function ConvItem({
  conv,
  index,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: {
  conv: Conversation;
  index: number;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRename: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title);
  const inputRef = useRef<HTMLInputElement>(null);
  // Tracks whether the user actively cancelled (Escape) to prevent onBlur from saving.
  const cancelledRef = useRef(false);

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    cancelledRef.current = false;
    setDraft(conv.title);
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  };

  const commitEdit = () => {
    if (cancelledRef.current) { cancelledRef.current = false; return; }
    const trimmed = draft.trim();
    if (trimmed && trimmed !== conv.title) onRename(trimmed);
    setEditing(false);
  };

  const cancelEdit = () => {
    cancelledRef.current = true;
    setEditing(false);
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{
        delay: Math.min(index * 0.035, 0.35),
        duration: 0.3,
        ease: "easeOut",
      }}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
      className={`relative w-full text-left flex items-start gap-2.5 px-3 py-2.5 rounded-lg group transition-colors cursor-pointer overflow-hidden ${
        isActive
          ? "bg-brand-100 dark:bg-white/[0.09]"
          : "hover:bg-brand-50 dark:hover:bg-white/[0.04]"
      }`}
    >
      {/* Active accent bar */}
      {isActive && (
        <motion.span
          layoutId="conv-active-bar"
          className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-gradient-to-b from-brand-600 to-brand-800"
          transition={{ type: "spring", stiffness: 500, damping: 35 }}
        />
      )}

      <MessageSquare
        size={13}
        className={`mt-1 shrink-0 transition-colors ${
          isActive
            ? "text-brand-600 dark:text-brand-300"
            : "text-brand-400/60 dark:text-white/25"
        }`}
      />
      <div className="flex-1 min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commitEdit(); }
              if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
              e.stopPropagation();
            }}
            onClick={(e) => e.stopPropagation()}
            maxLength={80}
            className="w-full text-[13px] font-medium bg-white dark:bg-white/[0.08] border border-brand-300 dark:border-brand-500/40 rounded-md px-1.5 py-0.5 outline-none text-brand-900 dark:text-white"
          />
        ) : (
          <p
            className={`text-[13px] font-medium truncate leading-snug transition-colors ${
              isActive
                ? "text-brand-900 dark:text-white"
                : "text-brand-700 dark:text-white/65"
            }`}
          >
            {conv.title}
          </p>
        )}
        <p className="text-[10.5px] text-brand-400/60 dark:text-white/25 mt-0.5">
          {timeAgo(conv.updatedAt)}
        </p>
      </div>
      <div className="flex items-center gap-0.5 shrink-0 mt-0.5">
        {editing ? (
          <motion.button
            onClick={(e) => { e.stopPropagation(); commitEdit(); }}
            onMouseDown={(e) => e.preventDefault()}
            whileHover={{ scale: 1.2 }}
            whileTap={{ scale: 0.85 }}
            transition={{ type: "spring", stiffness: 500, damping: 20 }}
            className="p-1 rounded-md text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors cursor-pointer"
            title="Save"
          >
            <Check size={12} />
          </motion.button>
        ) : (
          <motion.button
            onClick={startEdit}
            whileHover={{ scale: 1.2 }}
            whileTap={{ scale: 0.85 }}
            transition={{ type: "spring", stiffness: 500, damping: 20 }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-brand-300 hover:text-brand-600 dark:text-white/20 dark:hover:text-white/60 transition-all cursor-pointer"
            title="Rename"
          >
            <Pencil size={11} />
          </motion.button>
        )}
        <motion.button
          onClick={onDelete}
          whileHover={{ scale: 1.2 }}
          whileTap={{ scale: 0.85 }}
          transition={{ type: "spring", stiffness: 500, damping: 20 }}
          className="opacity-0 group-hover:opacity-100 p-1 rounded-md text-brand-300 hover:text-red-500 dark:text-white/20 dark:hover:text-red-400 transition-all cursor-pointer"
          title="Delete"
        >
          <Trash2 size={12} />
        </motion.button>
      </div>
    </motion.div>
  );
}
