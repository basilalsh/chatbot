import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { MessageSquare, Globe, ShieldCheck } from "lucide-react";

interface Props {
  onSuggestion: (text: string) => void;
}

const FALLBACK_SUGGESTIONS = [
  "What are the company's leave policies?",
  "ما هي سياسة الشركة في التعويضات؟",
  "Explain the claims process for motor insurance",
  "What documents are needed for a new policy?",
];

export default function EmptyState({ onSuggestion }: Props) {
  const [suggestions, setSuggestions] = useState<string[]>(FALLBACK_SUGGESTIONS);

  useEffect(() => {
    fetch("/api/suggestions")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.suggestions?.length) {
          setSuggestions(data.suggestions as string[]);
        }
      })
      .catch(() => {/* keep fallback */});
  }, []);
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      className="flex flex-col items-center justify-center flex-1 px-6 py-16"
    >
      {/* Icon */}
      <div className="relative mb-6">
        <motion.div
          animate={{ y: [0, -8, 0] }}
          transition={{ duration: 3.6, repeat: Infinity, ease: "easeInOut" }}
          className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand-700 to-brand-900 flex items-center justify-center shadow-lg shadow-brand-900/25"
        >
          <MessageSquare className="text-white" size={28} />
        </motion.div>
        <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-gold-500 flex items-center justify-center shadow-sm animate-pulse-ring">
          <span className="text-white text-[10px] font-bold relative z-10">AI</span>
        </div>
      </div>

      {/* Title */}
      <h2 className="text-xl sm:text-2xl font-bold text-brand-800 dark:text-brand-100 text-center mb-2">
        Welcome to AI Assistant
      </h2>
      <p className="text-sm text-brand-500/80 dark:text-brand-300/60 text-center max-w-md mb-8 leading-relaxed">
        Ask any question about company policies, regulations, or procedures in
        English or Arabic.
      </p>

      {/* Feature pills */}
      <div className="flex flex-wrap justify-center gap-2 mb-10">
        {[
          { icon: Globe, label: "English & Arabic" },
          { icon: ShieldCheck, label: "Enterprise-grade" },
          { icon: MessageSquare, label: "Instant answers" },
        ].map(({ icon: Icon, label }, i) => (
          <motion.span
            key={label}
            initial={{ opacity: 0, scale: 0.85, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ delay: 0.3 + i * 0.08, duration: 0.35, ease: "easeOut" }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-brand-100/80 dark:bg-white/[0.06] text-brand-600 dark:text-brand-300 border border-brand-200/50 dark:border-white/[0.06]"
          >
            <Icon size={12} />
            {label}
          </motion.span>
        ))}
      </div>

      {/* Suggestion chips */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
        {suggestions.map((s, i) => (
          <motion.button
            key={i}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.08, duration: 0.4 }}
            whileHover={{ scale: 1.03, y: -2, boxShadow: "0 4px 16px rgba(115,47,63,0.1)" }}
            whileTap={{ scale: 0.97 }}
            onClick={() => onSuggestion(s)}
            className="text-left px-4 py-3 rounded-xl text-sm text-brand-700 dark:text-brand-200 bg-white dark:bg-white/[0.04] border border-brand-200/60 dark:border-white/[0.06] hover:border-brand-400 dark:hover:border-brand-500/40 transition-colors cursor-pointer group"
          >
            <span className="group-hover:text-brand-800 dark:group-hover:text-white transition-colors">
              {s}
            </span>
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}
