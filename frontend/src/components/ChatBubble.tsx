import { motion, AnimatePresence } from "framer-motion";
import { Copy, Check, ChevronRight, ChevronDown, FileText } from "lucide-react";
import { useState, useCallback } from "react";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import type { ChatMessage, Source } from "../lib/types";
import { detectLang, timeAgo } from "../lib/utils";

interface Props {
  message: ChatMessage;
  onFollowUp?: (text: string) => void;
}

export default function ChatBubble({ message, onFollowUp }: Props) {
  const isUser = message.role === "user";
  const lang = message.language || detectLang(message.content);
  const isArabic = lang === "ar";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, x: isUser ? 12 : -12 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      transition={{ type: "spring", stiffness: 420, damping: 32 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} group`}
    >
      <div
        className={`max-w-[85%] sm:max-w-[75%] ${isUser ? "order-1" : "order-1"}`}
        dir={isArabic ? "rtl" : "ltr"}
      >
        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-3 text-[0.9rem] leading-relaxed ${
            isUser
              ? "bg-gradient-to-br from-brand-700 to-brand-900 text-white rounded-br-md shadow-md shadow-brand-900/15"
              : "bg-white dark:bg-white/[0.05] border border-brand-200/50 dark:border-white/[0.06] text-brand-800 dark:text-brand-100 rounded-bl-md shadow-sm"
          } ${message.isStreaming ? "streaming-cursor" : ""}`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <AnswerContent
              content={message.content}
              sources={message.sources}
            />
          )}
        </div>

        {/* Meta bar (assistant only) */}
        {!isUser && !message.isStreaming && message.content && (
          <div className="flex items-center gap-2 mt-1.5 px-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
            <ConfidenceBadge confidence={message.confidence} />
            <CopyButton text={message.content} />
            {message.createdAt && (
              <span
                className="text-[10px] text-brand-400/50 dark:text-white/25 ml-auto"
                title={new Date(message.createdAt).toLocaleString()}
              >
                {timeAgo(message.createdAt)}
              </span>
            )}
          </div>
        )}

        {/* User message timestamp */}
        {isUser && message.createdAt && (
          <p
            className="text-[10px] text-brand-300/60 dark:text-white/25 text-right mt-1 px-1"
            title={new Date(message.createdAt).toLocaleString()}
          >
            {timeAgo(message.createdAt)}
          </p>
        )}

        {/* Sources panel (assistant only, when sources exist) */}
        {!isUser && !message.isStreaming && message.sources && message.sources.length > 0 && (
          <SourcesPanel sources={message.sources} />
        )}

        {/* Follow-up questions */}
        {!isUser && !message.isStreaming && message.followUps?.length ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15, duration: 0.35 }}
            className="mt-3 space-y-1.5"
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider text-brand-400 dark:text-brand-300/50 px-1">
              Follow-up questions
            </p>
            <div className="flex flex-wrap gap-1.5">
              {message.followUps.map((q, i) => (
                <motion.button
                  key={i}
                  initial={{ opacity: 0, scale: 0.88 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{
                    delay: 0.18 + i * 0.07,
                    type: "spring",
                    stiffness: 380,
                    damping: 26,
                  }}
                  whileHover={{ scale: 1.05, y: -1 }}
                  whileTap={{ scale: 0.96 }}
                  onClick={() => onFollowUp?.(q)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium bg-brand-50 dark:bg-white/[0.04] border border-brand-200/60 dark:border-white/[0.06] text-brand-600 dark:text-brand-300 hover:bg-brand-100 dark:hover:bg-white/[0.08] hover:border-brand-300 dark:hover:border-brand-500/30 hover:shadow-sm transition-colors cursor-pointer"
                >
                  <ChevronRight size={10} />
                  {q}
                </motion.button>
              ))}
            </div>
          </motion.div>
        ) : null}
      </div>
    </motion.div>
  );
}

/* ── Sub-components ── */

/** Recursively walk React children and convert "[n]" text into citation badges. */
function processCitations(
  children: React.ReactNode,
  sources: Source[] | undefined
): React.ReactNode {
  return React.Children.map(children, (child): React.ReactNode => {
    if (typeof child === "string") {
      const parts = child.split(/(\[\d+\])/g);
      if (parts.length === 1) return child;
      return parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        if (!m) return part;
        const idx = parseInt(m[1], 10) - 1;
        const src = sources?.[idx];
        if (src?.document_name) {
          const href = `/documents/view/${encodeURIComponent(src.document_name)}${src.page ? `#page=${src.page}` : ""}`;
          return (
            <a
              key={i}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              title={src.page ? `Open ${src.document_name}, page ${src.page}` : src.document_name}
              className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-brand-600/15 text-brand-600 dark:bg-brand-400/20 dark:text-brand-300 border border-brand-400/40 hover:bg-brand-600/25 dark:hover:bg-brand-400/30 transition-colors cursor-pointer mx-0.5 align-super no-underline"
            >
              {m[1]}
            </a>
          );
        }
        return (
          <sup
            key={i}
            title={`Source ${m[1]}`}
            className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-gold-500/20 text-gold-500 border border-gold-500/40 cursor-default mx-0.5 align-super"
          >
            {m[1]}
          </sup>
        );
      });
    }
    if (React.isValidElement(child)) {
      const el = child as React.ReactElement<{ children?: React.ReactNode }>;
      if (el.props.children !== undefined) {
        return React.cloneElement(el, {
          children: processCitations(el.props.children, sources),
        } as React.HTMLAttributes<HTMLElement>);
      }
    }
    return child;
  });
}

function AnswerContent({
  content,
  sources,
}: {
  content: string;
  sources?: Source[];
}) {
  if (!content) return null;

  const components: Components = {
    p: ({ children }) => (
      <p className="mb-2 last:mb-0 leading-relaxed">
        {processCitations(children as React.ReactNode, sources)}
      </p>
    ),
    li: ({ children }) => (
      <li className="leading-relaxed">
        {processCitations(children as React.ReactNode, sources)}
      </li>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold">{children}</strong>
    ),
    em: ({ children }) => <em className="italic">{children}</em>,
    h1: ({ children }) => (
      <h1 className="text-base font-bold mt-3 mb-1 first:mt-0">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-sm font-bold mt-2 mb-1 first:mt-0">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-sm font-semibold mt-2 mb-1 first:mt-0">{children}</h3>
    ),
    ul: ({ children }) => (
      <ul className="list-disc list-outside space-y-0.5 my-1.5 pl-5">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal list-outside space-y-0.5 my-1.5 pl-5">
        {children}
      </ol>
    ),
    code: ({ children, className }) => {
      const isBlock = Boolean(className?.includes("language-"));
      return isBlock ? (
        <code className="block bg-brand-50 dark:bg-white/5 rounded p-2 text-xs font-mono my-1.5 whitespace-pre overflow-x-auto">
          {children}
        </code>
      ) : (
        <code className="px-1 py-0.5 rounded bg-brand-100/70 dark:bg-white/10 text-xs font-mono">
          {children}
        </code>
      );
    },
    pre: ({ children }) => <pre className="my-1.5">{children}</pre>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-brand-400/40 pl-3 my-1.5 text-brand-600/80 dark:text-brand-300/70 italic">
        {children}
      </blockquote>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto my-2">
        <table className="text-xs border-collapse w-full">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="border border-brand-300/50 dark:border-white/10 px-2 py-1 bg-brand-50 dark:bg-white/5 font-semibold text-left">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border border-brand-300/50 dark:border-white/10 px-2 py-1">
        {children}
      </td>
    ),
  };

  return (
    <div className="text-[0.9rem] leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  // Deduplicate: same doc+page counts as one source
  const unique = sources.reduce<Source[]>((acc, s) => {
    if (!acc.some((x) => x.document_name === s.document_name && x.page === s.page)) {
      acc.push(s);
    }
    return acc;
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, duration: 0.25 }}
      className="mt-2"
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 text-[11px] font-medium text-brand-500/70 dark:text-brand-300/50 hover:text-brand-600 dark:hover:text-brand-300 transition-colors cursor-pointer select-none"
      >
        <FileText size={11} />
        Sources ({unique.length})
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="inline-flex"
        >
          <ChevronDown size={11} />
        </motion.span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="mt-1.5 space-y-1.5">
              {unique.map((src, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 px-3 py-2 rounded-lg bg-brand-50/70 dark:bg-white/[0.03] border border-brand-100/60 dark:border-white/[0.05] text-[11px]"
                >
                  <FileText size={12} className="text-brand-400 dark:text-brand-300/60 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <a
                      href={`/documents/view/${encodeURIComponent(src.document_name)}${src.page ? `#page=${src.page}` : ""}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-brand-600 dark:text-brand-300 hover:underline truncate block"
                      title={src.page ? `Open ${src.document_name}, page ${src.page}` : src.document_name}
                    >
                      {src.document_name.replace(/\.pdf$/i, "")}
                      {src.page ? <span className="font-normal text-brand-400 dark:text-brand-300/50"> · p.{src.page}</span> : null}
                    </a>
                    {src.snippet && (
                      <p className="text-brand-500/70 dark:text-white/40 mt-0.5 line-clamp-2 leading-relaxed">
                        {src.snippet.slice(0, 160)}
                        {src.snippet.length > 160 ? "…" : ""}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function ConfidenceBadge({ confidence }: { confidence?: string }) {
  if (!confidence || !["high", "medium", "low"].includes(confidence))
    return null;

  const styles: Record<string, string> = {
    high: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20",
    medium: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    low: "bg-red-500/10 text-red-500 dark:text-red-400 border-red-500/20",
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide border ${styles[confidence]}`}
    >
      {confidence}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <motion.button
      onClick={copy}
      whileHover={{ scale: 1.06 }}
      whileTap={{ scale: 0.93 }}
      transition={{ type: "spring", stiffness: 400, damping: 20 }}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-brand-400 dark:text-brand-300/60 hover:bg-brand-100 dark:hover:bg-white/[0.06] transition-colors cursor-pointer"
    >
      <AnimatePresence mode="wait" initial={false}>
        {copied ? (
          <motion.span
            key="check"
            initial={{ scale: 0, rotate: -20 }}
            animate={{ scale: 1, rotate: 0 }}
            exit={{ scale: 0 }}
            transition={{ duration: 0.18, type: "spring", stiffness: 500 }}
          >
            <Check size={11} className="text-emerald-500" />
          </motion.span>
        ) : (
          <motion.span
            key="copy"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0 }}
            transition={{ duration: 0.18, type: "spring", stiffness: 500 }}
          >
            <Copy size={11} />
          </motion.span>
        )}
      </AnimatePresence>
      {copied ? "Copied" : "Copy"}
    </motion.button>
  );
}
