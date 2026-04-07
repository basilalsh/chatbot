import { createContext, useCallback, useContext, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle, AlertCircle, Info, X } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────
type ToastType = "success" | "error" | "info";

interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastCtx {
  toast: (message: string, type?: ToastType) => void;
}

// ── Context ────────────────────────────────────────────────────────────────────
const ToastContext = createContext<ToastCtx>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

// ── Provider + renderer ────────────────────────────────────────────────────────
export function ToasterProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counterRef = useRef(0);

  const toast = useCallback((message: string, type: ToastType = "success") => {
    const id = `t-${counterRef.current++}`;
    setToasts((prev) => [...prev.slice(-4), { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}

      {/* Toast stack — top-right, above everything */}
      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: -10, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -6, scale: 0.94, transition: { duration: 0.14 } }}
              transition={{ type: "spring", stiffness: 420, damping: 28 }}
              className={`pointer-events-auto flex items-center gap-2.5 pl-3 pr-2 py-2.5 rounded-xl shadow-lg text-[13px] font-medium max-w-[300px] min-w-[200px] ${
                t.type === "success"
                  ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30"
                  : t.type === "error"
                  ? "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-500/30"
                  : "bg-brand-50 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-500/30"
              }`}
            >
              {t.type === "success" && <CheckCircle size={14} className="shrink-0" />}
              {t.type === "error" && <AlertCircle size={14} className="shrink-0" />}
              {t.type === "info" && <Info size={14} className="shrink-0" />}
              <span className="flex-1 leading-snug">{t.message}</span>
              <button
                onClick={() => dismiss(t.id)}
                className="p-1 rounded-md hover:bg-black/10 dark:hover:bg-white/10 transition-colors cursor-pointer shrink-0"
                aria-label="Dismiss"
              >
                <X size={11} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
