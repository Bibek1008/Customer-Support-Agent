export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...options, credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : "The request could not be completed. Please try again.", response.status);
  return data as T;
}

export type ChatResult = {
  answer: string; handoff: boolean; ticket_id?: string; confidence: number;
  citations: { source_id: string; source_title: string; chunk: string; url?: string }[];
};
export type Message = { role: string; content: string; result?: ChatResult };
export type History = { messages: Message[] };
export type Session = { business_name: string; business_mode: string; conversations: { id: string }[] };
