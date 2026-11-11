"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, ChatResult, History, Message, Session } from "../lib/api";

const welcome: Message = { role: "assistant", content: "Hi! What can I help you with today? Choose a topic, or type your support question below." };
const topics = [
  ["↩", "Returns & refunds", "What is your return policy?"],
  ["◇", "Shipping & delivery", "How long does standard shipping take?"],
  ["▤", "Billing & subscriptions", "How do I cancel my subscription?"],
  ["✧", "Product warranty", "What does the product warranty cover?"],
];
type RequestBody = { conversation_id: string; message: string; request_id: string };

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([welcome]);
  const [question, setQuestion] = useState("");
  const [conversation, setConversation] = useState<string>();
  const [status, setStatus] = useState("Connecting to support…");
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [business, setBusiness] = useState("Support grounded in approved documents");
  const [attempt, setAttempt] = useState(0);
  const retry = useRef<RequestBody | null>(null);
  const busyRef = useRef(false);
  const generation = useRef(0);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages, busy]);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    async function connect() {
      setConnected(false); setError(""); setStatus("Connecting to support…");
      const deadline = Date.now() + 240000;
      try {
        while (true) {
          try { await api("readyz", { signal: controller.signal }); break; }
          catch (e) {
            if (stopped) return;
            if (e instanceof ApiError && e.status < 502) throw e;
            if (Date.now() > deadline) throw new Error("Support is taking longer than expected to start. Please reconnect in a moment.");
            setStatus("Starting support service. This can take a few minutes…");
            await new Promise<void>(resolve => {
              const timer = setTimeout(resolve, 4000);
              controller.signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
            });
            if (stopped) return;
          }
        }
        const session = await api<Session>("api/session", { method: "POST", signal: controller.signal });
        if (stopped) return;
        setBusiness(session.business_name + (session.business_mode === "demo" ? " · Demonstration with fictional policies and orders" : " · Approved support documents"));
        let saved: string | null = null;
        try { saved = localStorage.getItem("support_conversation"); } catch { /* Storage may be disabled. */ }
        let id = session.conversations.find(c => c.id === saved)?.id || session.conversations[0]?.id;
        if (!id) id = (await api<{ conversation_id: string }>("api/conversations", { method: "POST", signal: controller.signal })).conversation_id;
        const history = await api<History>(`api/conversations/${id}`, { signal: controller.signal });
        if (stopped) return;
        setConversation(id); setMessages(history.messages.length ? history.messages : [welcome]);
        try { localStorage.setItem("support_conversation", id); } catch { /* Session cookies still work. */ }
        setConnected(true); setStatus("Connected · Chats saved");
      } catch (e) {
        if (!stopped) { setError(e instanceof Error ? e.message : "Unable to connect."); setStatus("Support is unavailable"); }
      }
    }
    void connect();
    return () => { stopped = true; controller.abort(); };
  }, [attempt]);

  useEffect(() => {
    if (!conversation || !connected) return;
    const controller = new AbortController();
    const timer = setInterval(async () => {
      if (document.hidden || busyRef.current) return;
      const current = generation.current;
      try {
        const history = await api<History>(`api/conversations/${conversation}`, { signal: controller.signal });
        if (!controller.signal.aborted && !busyRef.current && current === generation.current && !retry.current) setMessages(history.messages.length ? history.messages : [welcome]);
      } catch { /* Keep the current conversation visible during network interruptions. */ }
    }, 12000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [conversation, connected]);

  function lock(value: boolean) { busyRef.current = value; setBusy(value); }

  async function send(text: string) {
    const message = text.trim();
    if (!message || !conversation || !connected || busyRef.current) return;
    generation.current++; lock(true); setError(""); setQuestion("");
    const same = retry.current?.message === message && retry.current?.conversation_id === conversation;
    if (!same) {
      setMessages(items => [...items, { role: "user", content: message }]);
      retry.current = { conversation_id: conversation, message, request_id: crypto.randomUUID() };
    }
    try {
      const result = await api<ChatResult>("chat", { method: "POST", body: JSON.stringify(retry.current), signal: AbortSignal.timeout(245000) });
      setMessages(items => [...items, { role: "assistant", content: result.answer, result }]);
      retry.current = null;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send your message."); setQuestion(message);
    } finally { lock(false); }
  }

  async function newChat() {
    if (busyRef.current || !connected) return;
    generation.current++; lock(true); setError("");
    try {
      const data = await api<{ conversation_id: string }>("api/conversations", { method: "POST" });
      setConversation(data.conversation_id); setMessages([welcome]); retry.current = null; setQuestion("");
      try { localStorage.setItem("support_conversation", data.conversation_id); } catch { /* Optional. */ }
    } catch (e) { setError(e instanceof Error ? e.message : "Could not create a conversation."); }
    finally { lock(false); }
  }

  function submit(e: FormEvent) { e.preventDefault(); void send(question); }

  return <div className="shell">
    <header className="topbar"><Link className="brand" href="/"><span className="logo">s<span>·</span></span>Support Desk</Link><div className={`connection ${connected ? "online" : ""}`} role="status"><span className="dot" />{status}</div></header>
    <main className="workspace">
      <aside className="sidebar"><div className="eyebrow">HERE TO HELP</div><h1>A little help.<br />A clear answer.</h1><p>From the first question to the next step.<br />Let’s get things sorted.</p>
        <div className="topics"><span className="section-label">WHAT CAN WE HELP WITH?</span>{topics.map(([icon, label, prompt]) => <button key={label} disabled={!connected || busy} onClick={() => void send(prompt)}><span className="topic-icon" aria-hidden="true">{icon}</span>{label}<span className="arrow">↗</span></button>)}</div>
        <div className="assurance"><span aria-hidden="true">✧</span><div><strong>Answers you can check.</strong><p>Our assistant uses approved support documents and shares its sources. Need more help? We’ll bring in the team.</p></div></div>
      </aside>
      <section className="chat-panel" aria-label="Support chat"><div className="chat-heading"><div className="avatar" aria-hidden="true">✳</div><div><strong>Let’s sort it out</strong><span>Support assistant · Staff replies appear here</span></div><button className="subtle" disabled={!connected || busy} onClick={() => void newChat()}>＋ New chat</button></div>
        <div className="messages" role="log" aria-live="polite" aria-relevant="additions text">{messages.map((message, i) => <article className={`message ${message.role}`} key={i}><span className="message-label">{message.role === "user" ? "You" : message.role === "staff" ? "Support team" : "Support assistant"}</span><div className="bubble">{message.content}</div>{message.result && <ResultDetails result={message.result} />}</article>)}{busy && <div className="thinking" role="status"><span className="pulse">●</span> Checking the support documents…</div>}<div ref={end} /></div>
        {error && <div className="error" role="alert">{error} {!connected && <button onClick={() => setAttempt(x => x + 1)}>Reconnect</button>}</div>}
        <form className="composer" onSubmit={submit}><div className="input-wrap"><textarea aria-label="Your support question" placeholder={connected ? "How can we help you today?" : "You can write your question while we connect…"} value={question} onChange={e => setQuestion(e.target.value)} maxLength={4000} disabled={busy} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(question); } }} /><button className="send" type="submit" disabled={!connected || busy || !question.trim()} aria-label="Send message">↑</button></div><div className="compose-hint"><span>Enter to send · Shift + Enter for a new line</span><span>{question.length}/4000</span></div></form>
      </section>
    </main><footer><span>{business}</span><Link href="/admin/inbox">Staff inbox ↗</Link></footer>
  </div>;
}

function ResultDetails({ result }: { result: ChatResult }) {
  return <div className="result"><span className={`badge ${result.handoff ? "handoff" : ""}`}>{result.handoff ? (result.ticket_id ? "Saved for support review" : "Request declined") : result.confidence === 0 && !result.citations?.length ? "Information unavailable" : "Answered"}</span>{result.ticket_id && <span className="badge handoff">Ticket {result.ticket_id}</span>}{!!result.citations?.length && <details><summary>View sources ({result.citations.length})</summary>{result.citations.map((source, i) => <div className="source" key={i}><strong>{source.source_title || source.source_id}</strong><p>{source.chunk}</p>{source.url && /^https?:\/\//i.test(source.url) && <a href={source.url} target="_blank" rel="noopener noreferrer">Open source ↗</a>}</div>)}</details>}</div>;
}
