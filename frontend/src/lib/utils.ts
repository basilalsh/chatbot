/** Detect Arabic text */
export function detectLang(text: string): "ar" | "en" {
  return /[\u0600-\u06FF]/.test(text) ? "ar" : "en";
}

/** Generate a unique ID */
export function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/** Human-readable relative time */
export function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "Just now";
  if (min < 60) return `${min}m ago`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(ts).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/**
 * Extract the "answer" field from a partially-streamed JSON string.
 * Falls back to the raw text if no JSON wrapper is found.
 */
export function extractPartialAnswer(raw: string): string {
  const text = (raw || "").trim();
  if (!text) return "";

  const key = '"answer"';
  const keyIdx = text.indexOf(key);
  if (keyIdx === -1) return text;

  let i = keyIdx + key.length;
  while (i < text.length && text[i] !== '"') i++;
  if (i >= text.length) return "";
  i++; // skip opening quote

  let result = "";
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\" && i + 1 < text.length) {
      const next = text[i + 1];
      if (next === '"') result += '"';
      else if (next === "n") result += "\n";
      else if (next === "t") result += "\t";
      else if (next === "\\") result += "\\";
      else result += next;
      i += 2;
      continue;
    }
    if (ch === '"') break;
    result += ch;
    i++;
  }
  return result;
}
