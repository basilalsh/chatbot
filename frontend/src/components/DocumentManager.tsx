import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Upload, Trash2, FileText, ExternalLink, AlertCircle, Loader2 } from "lucide-react";
import { useToast } from "./Toaster";

interface DocInfo {
  name: string;
  size_bytes: number;
  modified: number;
}

interface IndexState {
  status: "ready" | "processing" | "embedding" | "error";
  message: string;
  progress: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onReindexComplete?: () => void;
}

export default function DocumentManager({ open, onClose, onReindexComplete }: Props) {
  const { toast } = useToast();
  const [docs, setDocs] = useState<DocInfo[]>([]);
  const [indexState, setIndexState] = useState<IndexState>({ status: "ready", message: "", progress: 0 });
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingName, setDeletingName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wasIndexingRef = useRef(false);

  const fetchDocs = useCallback(async () => {
    try {
      const res = await fetch("/documents");
      if (!res.ok) return;
      const data = await res.json();
      setDocs(data.documents ?? []);
      setIndexState(data.index ?? { status: "ready", message: "", progress: 0 });
    } catch {
      // ignore network errors
    }
  }, []);

  // Poll index status while indexing is in progress
  useEffect(() => {
    if (!open) return;
    fetchDocs();
  }, [open, fetchDocs]);

  useEffect(() => {
    if (indexState.status === "processing" || indexState.status === "embedding") {
      wasIndexingRef.current = true;
      if (!pollRef.current) {
        pollRef.current = setInterval(async () => {
          try {
            const res = await fetch("/documents/status");
            if (!res.ok) return;
            const data = await res.json();
            setIndexState(data);
            if (data.status === "ready" || data.status === "error") {
              // Refresh doc list and stop polling
              fetchDocs();
              if (pollRef.current) {
                clearInterval(pollRef.current);
                pollRef.current = null;
              }
              // Notify parent to clear client-side answer cache
              if (data.status === "ready" && wasIndexingRef.current) {
                wasIndexingRef.current = false;
                onReindexComplete?.();
                toast("Index updated — answers reflect new documents.", "success");
              }
            }
          } catch {
            // ignore
          }
        }, 2500);
      }
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [indexState.status, fetchDocs, onReindexComplete, toast]);

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!e.target) return;
    (e.target as HTMLInputElement).value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Only PDF files are supported.");
      return;
    }
    setUploadError(null);
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/documents/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setUploadError(data.error ?? "Upload failed.");
      } else {
        await fetchDocs();
        toast(`"${file.name}" uploaded successfully.`, "success");
      }
    } catch {
      setUploadError("Network error during upload.");
    } finally {
      setUploading(false);
    }
  }, [fetchDocs, toast]);

  const handleDelete = useCallback(async (name: string) => {
    if (!confirm(`Delete "${name}"? This will trigger a reindex.`)) return;
    setDeletingName(name);
    try {
      const res = await fetch(`/documents/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        toast(data.error ?? "Delete failed.", "error");
      } else {
        await fetchDocs();
        toast(`"${name}" deleted.`, "success");
      }
    } catch {
      toast("Network error during delete.", "error");
    } finally {
      setDeletingName(null);
    }
  }, [fetchDocs, toast]);

  const isIndexing = indexState.status === "processing" || indexState.status === "embedding";

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="dm-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="fixed inset-0 bg-black/50 z-50"
            onClick={onClose}
          />

          {/* Panel */}
          <motion.div
            key="dm-panel"
            initial={{ opacity: 0, scale: 0.95, y: -12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -12 }}
            transition={{ type: "spring", stiffness: 360, damping: 30 }}
            className="fixed top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2
                       w-[92vw] max-w-lg
                       bg-white dark:bg-[#15111e]
                       border border-brand-200/60 dark:border-white/[0.08]
                       rounded-2xl shadow-2xl shadow-black/20
                       flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-brand-100 dark:border-white/[0.06]">
              <div>
                <h2 className="text-sm font-bold text-brand-800 dark:text-brand-100 tracking-tight">
                  Document Manager
                </h2>
                <p className="text-[11px] text-brand-400/70 dark:text-white/40 mt-0.5">
                  Upload or remove PDFs — the assistant adapts automatically
                </p>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-brand-400 hover:text-brand-700 dark:text-white/35 dark:hover:text-white/70 hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Index status bar */}
            <AnimatePresence>
              {(isIndexing || indexState.status === "error") && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className={`px-5 py-2.5 text-xs font-medium flex items-center gap-2 ${
                    indexState.status === "error"
                      ? "bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400"
                      : "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400"
                  }`}
                >
                  {isIndexing ? (
                    <Loader2 size={13} className="animate-spin shrink-0" />
                  ) : (
                    <AlertCircle size={13} className="shrink-0" />
                  )}
                  <span className="truncate">{indexState.message}</span>
                  {isIndexing && indexState.progress > 0 && (
                    <span className="ml-auto shrink-0">{indexState.progress}%</span>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Progress bar */}
            <AnimatePresence>
              {isIndexing && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="w-full h-0.5 bg-brand-100 dark:bg-white/[0.06]"
                >
                  <motion.div
                    className="h-full bg-gradient-to-r from-brand-500 to-brand-700"
                    initial={{ width: "0%" }}
                    animate={{ width: `${indexState.progress}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Document list */}
            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-1.5 min-h-[120px] max-h-[40vh]">
              {docs.length === 0 ? (
                <p className="text-center text-[12px] text-brand-400/60 dark:text-white/30 py-8">
                  No documents uploaded yet. Add a PDF below.
                </p>
              ) : (
                docs.map((doc) => (
                  <motion.div
                    key={doc.name}
                    layout
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -10 }}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-brand-50/60 dark:bg-white/[0.03] border border-brand-100/80 dark:border-white/[0.05] group"
                  >
                    <FileText size={15} className="text-brand-500 dark:text-brand-300/70 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-brand-700 dark:text-brand-200 truncate" title={doc.name}>
                        {doc.name}
                      </p>
                      <p className="text-[10px] text-brand-400/70 dark:text-white/35">
                        {formatBytes(doc.size_bytes)}  ·  modified {timeAgo(doc.modified * 1000)}
                      </p>
                    </div>
                    <a
                      href={`/documents/view/${encodeURIComponent(doc.name)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-md text-brand-400/60 hover:text-brand-600 dark:text-white/25 dark:hover:text-white/60 hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors opacity-0 group-hover:opacity-100 cursor-pointer"
                      title="Open PDF"
                    >
                      <ExternalLink size={12} />
                    </a>
                    <button
                      onClick={() => handleDelete(doc.name)}
                      disabled={deletingName === doc.name || isIndexing}
                      className="p-1.5 rounded-md text-brand-400/60 hover:text-red-500 dark:text-white/25 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-30 cursor-pointer"
                      title="Delete document"
                    >
                      {deletingName === doc.name ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Trash2 size={12} />
                      )}
                    </button>
                  </motion.div>
                ))
              )}
            </div>

            {/* Upload area */}
            <div className="px-5 pb-5 pt-2 border-t border-brand-100/60 dark:border-white/[0.05]">
              {uploadError && (
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-xs text-red-500 mb-2 flex items-center gap-1"
                >
                  <AlertCircle size={12} />
                  {uploadError}
                </motion.p>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={handleFileChange}
              />
              <motion.button
                whileHover={{ scale: 1.02, y: -1 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading || isIndexing}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl
                           border-2 border-dashed border-brand-300/60 dark:border-white/[0.1]
                           text-sm font-semibold text-brand-600 dark:text-brand-300
                           hover:border-brand-500 hover:bg-brand-50/60 dark:hover:bg-white/[0.04]
                           disabled:opacity-50 disabled:cursor-not-allowed
                           transition-colors cursor-pointer"
              >
                {uploading ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Uploading…
                  </>
                ) : (
                  <>
                    <Upload size={15} />
                    Upload PDF
                  </>
                )}
              </motion.button>
              <p className="text-center text-[10px] text-brand-400/50 dark:text-white/25 mt-2">
                Max 150 MB · PDF files only · Reindex happens automatically
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60_000);
  if (min < 2) return "just now";
  if (min < 60) return `${min}m ago`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
