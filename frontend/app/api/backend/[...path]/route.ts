import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

// A fixed upstream and explicit allowlist prevent this becoming an open proxy.
function allowed(path: string, method: string) {
  if (method === "GET") return /^(readyz|api\/conversations\/[a-f0-9-]{36}|api\/admin\/(tickets|evaluations|activity))$/i.test(path);
  if (method === "POST") return /^(chat|api\/session|api\/conversations|api\/admin\/tickets\/[\w-]+\/replies)$/.test(path);
  return method === "PATCH" && /^api\/admin\/tickets\/[\w-]+$/.test(path);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!allowed(path, request.method)) return NextResponse.json({ detail: "Not found." }, { status: 404 });
  // Validate the browser origin before substituting the backend origin below.
  const origin = request.headers.get("origin");
  // Next may normalize nextUrl's hostname to localhost behind a proxy.
  // Use the actual HTTP Host and deployment-forwarded protocol for comparison.
  const protocol = request.headers.get("x-forwarded-proto") || request.nextUrl.protocol.slice(0, -1);
  const frontendOrigin = `${protocol}://${request.headers.get("host")}`;
  if (request.method !== "GET" && ((origin && origin !== frontendOrigin) || request.headers.get("sec-fetch-site") === "cross-site")) {
    return NextResponse.json({ detail: "Origin is not allowed." }, { status: 403 });
  }
  let backend: URL;
  try {
    backend = new URL(process.env.BACKEND_URL || "");
    if (!['http:', 'https:'].includes(backend.protocol) || backend.username || backend.password || backend.pathname !== "/" || backend.search || backend.hash) throw new Error();
  } catch {
    return NextResponse.json({ detail: "Configure BACKEND_URL in the frontend deployment settings." }, { status: 500 });
  }
  const headers = new Headers({ Origin: backend.origin });
  for (const name of ["content-type", "authorization"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const session = request.cookies.get("support_session");
  if (session) headers.set("cookie", `support_session=${encodeURIComponent(session.value)}`);
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && new TextEncoder().encode(body).length > 16384) return NextResponse.json({ detail: "Request is too large." }, { status: 413 });
    const upstream = await fetch(new URL(path, backend), {
      method: request.method, headers, body, cache: "no-store", redirect: "manual",
      signal: AbortSignal.timeout(path === "chat" ? 230000 : 20000),
    });
    const responseHeaders = new Headers({ "Cache-Control": "no-store" });
    responseHeaders.set("Content-Type", upstream.headers.get("content-type") || "application/json");
    for (const cookie of upstream.headers.getSetCookie()) {
      // Backend cookies become first-party cookies on the Vercel hostname.
      responseHeaders.append("Set-Cookie", cookie);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: "The support service is starting or could not be reached. Please try again." }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH };
