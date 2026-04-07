import { useTheme } from "../hooks/useTheme";
import { Moon, Sun, Menu, FolderOpen } from "lucide-react";
import logo from "../assets/dhofar-insurance-social.png";
import { motion, AnimatePresence } from "framer-motion";

interface Props {
  onToggleSidebar: () => void;
  onOpenDocuments: () => void;
}

export default function Header({ onToggleSidebar, onOpenDocuments }: Props) {
  const { theme, toggle } = useTheme();

  return (
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

      {/* Right: documents + theme toggle */}
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
      </div>
    </motion.header>
  );
}
