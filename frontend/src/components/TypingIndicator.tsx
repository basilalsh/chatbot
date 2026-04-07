import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";

const MESSAGES = [
  "Analyzing documents\u2026",
  "Searching knowledge base\u2026",
  "Processing your question\u2026",
  "Preparing answer\u2026",
];

// Peak scaleY for each of the 5 equalizer bars (gives a natural wave shape)
const BAR_PEAKS = [0.5, 1.0, 0.65, 1.0, 0.5];

export default function TypingIndicator() {
  const [msgIdx, setMsgIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setMsgIdx((i) => (i + 1) % MESSAGES.length),
      2400,
    );
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6, scale: 0.96 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="flex justify-start"
    >
      <div className="relative flex items-center gap-3.5 px-4 py-3 rounded-2xl rounded-bl-md bg-white dark:bg-white/[0.05] border border-brand-200/50 dark:border-white/[0.06] shadow-sm overflow-hidden">
        
        {/* Shimmer sweep across the container */}
        <motion.div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-r from-transparent via-brand-100/60 dark:via-white/[0.04] to-transparent pointer-events-none"
          animate={{ x: ["-100%", "260%"] }}
          transition={{
            duration: 2.6,
            repeat: Infinity,
            ease: "linear",
            repeatDelay: 1.2,
          }}
        />

        {/* Equalizer bars */}
        <div className="flex items-end gap-[3px] h-[18px] relative z-10">
          {BAR_PEAKS.map((peak, i) => (
            <motion.span
              key={i}
              className="w-[4px] rounded-sm bg-gradient-to-t from-brand-700 to-brand-400 dark:from-brand-600 dark:to-brand-300"
              style={{ height: 18, transformOrigin: "50% 100%", display: "block" }}
              animate={{ scaleY: [0.22, peak, 0.22] }}
              transition={{
                duration: 0.72,
                repeat: Infinity,
                delay: i * 0.1,
                ease: "easeInOut",
              }}
            />
          ))}
        </div>

        {/* Cycling status text */}
        <div className="relative h-[18px] w-44 overflow-hidden z-10">
          <AnimatePresence mode="wait">
            <motion.span
              key={msgIdx}
              initial={{ y: 14, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -14, opacity: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="absolute inset-0 flex items-center text-xs text-brand-400/80 dark:text-brand-300/60 font-medium whitespace-nowrap"
            >
              {MESSAGES[msgIdx]}
            </motion.span>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
