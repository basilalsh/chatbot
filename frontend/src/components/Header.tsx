import { useState } from "react";
import { useTheme } from "../hooks/useTheme";
import { Moon, Sun, Menu, FolderOpen, Power } from "lucide-react";
import logo from "../assets/dhofar-insurance-social.png";
import { motion, AnimatePresence } from "framer-motion";

interface Props {
  onToggleSidebar: () => void;
  onOpenDocuments: () => void;
}

export default function Header({ onToggleSidebar, onOpenDocuments }: Props) {
  const { theme, toggle } = useTheme();
  const [confirming, setConfirming] = useState(false);
  const [shutdownDone, setShutdownDone] = useState(false);

  async function handleShutdown() {
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    setShutdownDone(true);
    try { await fetch("/shutdown", { method: "POST" }); } catch { /* server closed */ }
  }

  return (
    <>
      {/* Shutdown confirmation overlay */}
      <AnimatePresence>
        {confirming && (
          <motion.div
            key="overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setConfirming(false)}
          >
            <motion.div
              initial={{ scale: 0.92, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.92, opacity: 0 }}
              transition={{ type: "spring", stiffness: 380, damping: 26 }}
              className="bg-white dark:bg-[#1a1625] rounded-2xl shadow-2xl p-6 mx-4 max-w-sm w-full border border-gray-200 dark:border-white/10"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <Power size={18} className="text-red-600 dark:text-red-400" />
                </div>
                <h2 className="text-base font-semibold text-gray-900 dark:text-white">Shut down server?</h2>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
                This will stop the application. You will need to run <code className="font-mono bg-gray-100 dark:bg-white/10 px-1 rounded">run.bat</code> again to restart it.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setConfirming(false)}
                  className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={handleShutdown}
                  className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-700 transition-colors cursor-pointer"
                >
                  Shut down
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Server-stopped banner */}
      <AnimatePresence>
        {shutdownDone && (
          <motion.div
            key="banner"
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          >
            <div className="bg-white dark:bg-[#1a1625] rounded-2xl shadow-2xl p-8 mx-4 max-w-sm w-full text-center border border-gray-200 dark:border-white/10">
              <div className="w-14 h-14 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
                <Power size={24} className="text-red-500" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Server stopped</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">Run <code className="font-mono bg-gray-100 dark:bg-white/10 px-1 rounded">run.bat</code> to restart the application.</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

    <motion.header
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="flex items-center justify-between px-4 py-3 border-b border-brand-200/60 dark:border-white/[0.06] bg-white/70 dark:bg-white/[0.03] backdrop-blur-xl sticky top-0 z-20"
    >
      {/* Left: sidebar toggle + logo */}
      <div className="flex items-center gap-3">
        <motion.button
          onClick={onToggleSidebar}
          whileHover={{ scale: 1.12 }}
          whileTap={{ scale: 0.88 }}
          transition={{ type: "spring", stiffness: 400, damping: 20 }}
          className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors text-brand-600 dark:text-brand-300 cursor-pointer"
          title="Toggle sidebar"
        >
          <Menu size={18} />
        </motion.button>
        <img
          src={logo}
          alt="Dhofar Insurance"
          className="h-9 w-auto"
        />
        <div className="hidden sm:block">
          <h1 className="text-sm font-bold tracking-tight text-brand-800 dark:text-brand-200 leading-none">
            Dhofar Insurance
          </h1>
          <p className="text-[11px] text-brand-500/70 dark:text-white/60 font-medium">
            Enterprise AI Assistant
          </p>
        </div>
      </div>

      {/* Right: documents + theme toggle + shutdown */}
      <div className="flex items-center gap-1">
        <motion.button
          onClick={onOpenDocuments}
          whileHover={{ scale: 1.12 }}
          whileTap={{ scale: 0.88 }}
          transition={{ type: "spring", stiffness: 400, damping: 20 }}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors text-brand-600 dark:text-brand-300 cursor-pointer text-[11px] font-semibold"
          title="Manage documents"
        >
          <FolderOpen size={15} />
          <span className="hidden sm:inline">Documents</span>
        </motion.button>
        <motion.button
          onClick={toggle}
          whileHover={{ scale: 1.12 }}
          whileTap={{ scale: 0.88 }}
          transition={{ type: "spring", stiffness: 400, damping: 20 }}
          className="relative flex items-center justify-center w-8 h-8 rounded-lg hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors text-brand-600 dark:text-brand-300 cursor-pointer overflow-hidden"
          title={theme === "dark" ? "Light mode" : "Dark mode"}
        >
          <AnimatePresence mode="wait" initial={false}>
            {theme === "dark" ? (
              <motion.span
                key="sun"
                initial={{ rotate: -90, scale: 0, opacity: 0 }}
                animate={{ rotate: 0, scale: 1, opacity: 1 }}
                exit={{ rotate: 90, scale: 0, opacity: 0 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
                className="absolute"
              >
                <Sun size={16} />
              </motion.span>
            ) : (
              <motion.span
                key="moon"
                initial={{ rotate: 90, scale: 0, opacity: 0 }}
                animate={{ rotate: 0, scale: 1, opacity: 1 }}
                exit={{ rotate: -90, scale: 0, opacity: 0 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
                className="absolute"
              >
                <Moon size={16} />
              </motion.span>
            )}
          </AnimatePresence>
        </motion.button>
        <motion.button
          onClick={handleShutdown}
          whileHover={{ scale: 1.12 }}
          whileTap={{ scale: 0.88 }}
          transition={{ type: "spring", stiffness: 400, damping: 20 }}
          className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/20 transition-colors text-red-500 dark:text-red-400 cursor-pointer"
          title="Shut down server"
        >
          <Power size={16} />
        </motion.button>
      </div>
    </motion.header>
    </>
  );
}
