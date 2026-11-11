"use client";

import Link from "next/link";
import { FormEvent, useRef, useState } from "react";
import { api } from "../../../lib/api";

type Ticket = { id: string; subject: string; body: string; status: string; created_at: string; messages?: { role: string; content: string }[]; replies?: string[] };

export default function StaffInbox() {
  const key = useRef("");
  const [input, setInput] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<string | null>(null);

  async function staffApi<T>(path: string, options: RequestInit = {}) {
    return api<T>(path, { ...options, headers: { Authorization: `Bearer ${key.current}` } });
  }
  async function load() { setTickets(await staffApi<Ticket[]>("api/admin/tickets")); }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Request failed."); }
    finally { setBusy(false); }
  }
  function login(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      key.current = input; setInput("");
      try { await load(); setUnlocked(true); } catch (e) { key.current = ""; throw e; }
    });
  }
  return <main className="staff-shell"><header className="staff-header"><div><h1>Staff inbox</h1><p className="muted">Review escalations, reply to customers, and update ticket status.</p></div><Link href="/">Customer chat ↗</Link></header>
    {!unlocked && <form className="card login" onSubmit={login}><label htmlFor="key">Staff access key</label><input id="key" type="password" autoComplete="off" required value={input} onChange={e => setInput(e.target.value)} /><button className="primary" disabled={busy}>{busy ? "Connecting…" : "Unlock inbox"}</button><p className="muted">Your access key stays in this tab’s memory until you sign out or close the page.</p></form>}
    {error && <p className="error" role="alert">{error}</p>}
    {unlocked && <><div className="actions"><button disabled={busy} onClick={() => void run(load)}>Refresh tickets</button>{["evaluations", "activity"].map(name => <button key={name} disabled={busy} onClick={() => void run(async () => { const data = await staffApi<unknown[]>(`api/admin/${name}`); setReport(data.length ? JSON.stringify(data, null, 2) : "No records yet."); })}>{name === "evaluations" ? "View evaluations" : "Recent activity"}</button>)}<button disabled={busy} onClick={() => { key.current = ""; setUnlocked(false); setTickets([]); setReport(null); setError(""); }}>Sign out</button></div>{report !== null && <><button className="subtle" onClick={() => setReport(null)}>Close report</button><pre className="report">{report}</pre></>}{tickets.length === 0 && <p className="muted">No support tickets yet.</p>}{tickets.map(ticket => <TicketCard key={ticket.id} ticket={ticket} disabled={busy} onAction={action => void run(action)} onReply={async message => { await staffApi(`api/admin/tickets/${encodeURIComponent(ticket.id)}/replies`, { method: "POST", body: JSON.stringify({ message }) }); await load(); }} onStatus={async status => { await staffApi(`api/admin/tickets/${encodeURIComponent(ticket.id)}`, { method: "PATCH", body: JSON.stringify({ status }) }); await load(); }} />)}</>}
  </main>;
}

function TicketCard({ ticket, disabled, onAction, onReply, onStatus }: { ticket: Ticket; disabled: boolean; onAction: (action: () => Promise<void>) => void; onReply: (text: string) => Promise<void>; onStatus: (status: string) => Promise<void> }) {
  const [reply, setReply] = useState("");
  const [status, setStatus] = useState(ticket.status);
  const [notice, setNotice] = useState("");
  return <article className="card"><h2>{ticket.subject}</h2><p className="muted">{ticket.id} · {ticket.status} · {new Date(ticket.created_at).toLocaleString()}</p><pre>{ticket.body}</pre>{!!ticket.messages?.length && <details><summary>Full saved conversation</summary><pre>{ticket.messages.map(m => `${m.role}: ${m.content}`).join("\n\n")}</pre></details>}{!!ticket.replies?.length && <pre>{"Previous staff replies:\n\n" + ticket.replies.join("\n\n")}</pre>}<textarea aria-label={`Reply for ${ticket.id}`} placeholder="Write a reply to the customer…" maxLength={4000} value={reply} onChange={e => setReply(e.target.value)} /><div className="actions"><button disabled={disabled || !reply.trim()} onClick={() => onAction(async () => { await onReply(reply); setReply(""); setNotice("Reply saved. The customer can see it in their chat."); })}>Send reply</button><select aria-label={`Status for ${ticket.id}`} value={status} onChange={e => setStatus(e.target.value)}>{["open", "escalated", "resolved"].map(s => <option key={s}>{s}</option>)}</select><button disabled={disabled} onClick={() => onAction(async () => { await onStatus(status); setNotice("Status saved."); })}>Update status</button></div><p className="muted" role="status">{notice}</p></article>;
}
