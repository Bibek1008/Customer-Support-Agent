// Exercise the built frontend against a temporary local backend, without credentials.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const seen = [];
const backend = createServer(async (req, res) => {
  let body = "";
  for await (const chunk of req) body += chunk;
  seen.push({ path: req.url, method: req.method, headers: req.headers, body });
  res.setHeader("Content-Type", "application/json");
  if (req.url === "/api/session") res.setHeader("Set-Cookie", "support_session=smoke-token; HttpOnly; SameSite=Strict; Path=/; Secure");
  if (req.url === "/chat") { res.statusCode = 409; res.end(JSON.stringify({ detail: "Already processing." })); }
  else res.end(JSON.stringify({ status: "ready" }));
});
await new Promise(resolve => backend.listen(0, "127.0.0.1", resolve));
const backendOrigin = `http://127.0.0.1:${backend.address().port}`;
// Let Next choose an available port, then parse its startup output.
let origin;
let logs = "";
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "0"], {
  cwd: process.cwd(), windowsHide: true,
  env: { ...process.env, BACKEND_URL: backendOrigin }, stdio: ["ignore", "pipe", "pipe"],
});
child.on("error", error => { logs += error.message; });
child.stdout.on("data", chunk => { logs += chunk; origin = logs.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0]; });
child.stderr.on("data", chunk => { logs += chunk; });
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(logs);
    if (origin) { try { ready = (await fetch(origin)).ok; } catch { /* Starting. */ } }
    if (ready) break;
    await delay(200);
  }
  assert.ok(ready, `Frontend failed to start: ${logs}`);
  const page = await fetch(origin);
  assert.match(await page.text(), /A little help/);
  assert.equal(page.headers.get("x-frame-options"), "DENY");
  assert.equal((await fetch(`${origin}/admin/inbox`)).status, 200);
  const session = await fetch(`${origin}/api/backend/api/session`, { method: "POST", headers: { Origin: origin } });
  assert.equal(session.status, 200);
  assert.match(session.headers.get("set-cookie"), /support_session=smoke-token.*HttpOnly/);
  assert.equal(session.headers.get("cache-control"), "no-store");
  assert.equal(seen.at(-1).headers.origin, backendOrigin);
  await fetch(`${origin}/api/backend/api/admin/tickets`, { headers: { Cookie: "support_session=smoke-token; unrelated=secret", Authorization: "Bearer test-key" } });
  assert.equal(seen.at(-1).headers.cookie, "support_session=smoke-token");
  assert.equal(seen.at(-1).headers.authorization, "Bearer test-key");
  const chat = await fetch(`${origin}/api/backend/chat`, { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ message: "hello" }) });
  assert.equal(chat.status, 409);
  assert.equal((await chat.json()).detail, "Already processing.");
  assert.deepEqual(JSON.parse(seen.at(-1).body), { message: "hello" });
  const before = seen.length;
  assert.equal((await fetch(`${origin}/api/backend/api/session`, { method: "POST", headers: { Origin: "https://untrusted.example" } })).status, 403);
  assert.equal((await fetch(`${origin}/api/backend/api/session`, { method: "POST", headers: { "Sec-Fetch-Site": "cross-site" } })).status, 403);
  assert.equal((await fetch(`${origin}/api/backend/not-allowed`)).status, 404);
  assert.equal((await fetch(`${origin}/api/backend/chat`, { method: "POST", headers: { Origin: origin }, body: "x".repeat(16385) })).status, 413);
  assert.equal(seen.length, before, "Rejected requests must not reach the backend");
  console.log("Passed: pages, security headers, session cookies, backend origin, authorization, request/response forwarding, CSRF rejection, path allowlist, body limit.");
} finally {
  child.kill();
  backend.closeAllConnections();
  await new Promise(resolve => backend.close(resolve));
}
