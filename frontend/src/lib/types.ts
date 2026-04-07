export interface Source {
  document_name: string;
  snippet: string;
  chunk_id: string | null;
  page: number | null;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  followUps?: string[];
  language?: "en" | "ar";
  confidence?: "high" | "medium" | "low";
  isStreaming?: boolean;
  /** Unix ms timestamp when the message was created. */
  createdAt?: number;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}
