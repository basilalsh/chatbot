import { FormEvent, useRef, useState, useEffect } from "react";
import { Send, Square } from "lucide-react";
import { motion } from "framer-motion";
import { detectLang } from "../lib/utils";

interface Props {
  onSend: (text: string) => void;
  onStop: () => void;
  isLoading: boolean;
}

export default function ChatInput({ onSend, onStop, isLoading }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [value]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text || text.length > 2000) return;
    onSend(text);
    setValue("");
    // Reset textarea height
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const charCount = value.length;
  const isNear = charCount >= 1800;
  const isOver = charCount >= 2000;
  const isArabic = value.length > 0 && detectLang(value) === "ar";

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
      className="sticky bottom-0 bg-gradient-to-t from-gray-50 via-gray-50/95 to-gray-50/0 dark:from-[#0c0a0f] dark:via-[#0c0a0f]/95 dark:to-[#0c0a0f]/0 pt-6 pb-4 px-4"
    >
      <form
        onSubmit={handleSubmit}
        className="relative max-w-3xl mx-auto"
      >
        <div className="relative flex items-end gap-2 p-2 rounded-2xl border border-brand-200/60 dark:border-white/[0.08] bg-white dark:bg-white/[0.04] shadow-sm focus-within:border-brand-400 dark:focus-within:border-brand-500/40 transition-all input-glow-focus">
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask in English or Arabic…"
            rows={1}
            maxLength={2000}
            dir={isArabic ? "rtl" : "ltr"}
            className="flex-1 resize-none bg-transparent text-sm text-brand-800 dark:text-brand-100 placeholder:text-brand-400/60 dark:placeholder:text-white/35 outline-none px-2 py-2 max-h-40 leading-relaxed"
          />

          {isLoading ? (
            <motion.button
              type="button"
              onClick={onStop}
              whileHover={{ scale: 1.12 }}
              whileTap={{ scale: 0.88 }}
              transition={{ type: "spring", stiffness: 400, damping: 18 }}
              className="relative flex items-center justify-center w-9 h-9 rounded-xl bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors shrink-0 cursor-pointer"
              title="Stop generating"
            >
              {/* Pulsing ring behind the button */}
              <motion.span
                aria-hidden
                className="absolute inset-0 rounded-xl bg-red-500/20"
                animate={{ scale: [1, 1.45, 1], opacity: [0.5, 0, 0.5] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
              />
              <Square size={16} fill="currentColor" className="relative z-10" />
            </motion.button>
          ) : (
            <motion.button
              type="submit"
              disabled={!value.trim()}
              whileHover={value.trim() ? { scale: 1.08 } : undefined}
              whileTap={value.trim() ? { scale: 0.92 } : undefined}
              transition={{ type: "spring", stiffness: 400, damping: 18 }}
              className="flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-brand-700 to-brand-900 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:shadow-md hover:shadow-brand-900/25 transition-shadow shrink-0 cursor-pointer"
              title="Send message"
            >
              <Send size={16} />
            </motion.button>
          )}
        </div>

        {/* Character counter */}
        <div className="flex justify-end mt-1 px-2">
          <span
            className={`text-[10px] font-medium transition-colors ${
              isOver
                ? "text-red-500 font-bold"
                : isNear
                ? "text-amber-500"
                : "text-brand-500/70 dark:text-white/45"
            }`}
          >
            {charCount > 0 ? `${charCount} / 2000` : ""}
          </span>
        </div>
      </form>
    </motion.div>
  );
}
