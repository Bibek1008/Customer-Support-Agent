# Support Desk — Next.js frontend

Next.js App Router, React, and TypeScript frontend for the existing FastAPI backend on Render. Includes customer chat, saved conversations, citations, human handoff, staff replies, staff inbox, ticket status updates, and evaluation/activity reports.

Live customer chat: https://customer-support-agent-c28c.vercel.app/

Live staff inbox: https://customer-support-agent-c28c.vercel.app/admin/inbox

Backend: https://customer-support-agent-k21j.onrender.com

## Local development

Use Node.js 20.9 or newer (Node 24 recommended).

```powershell
cd Customer-Support-Agent/frontend
Copy-Item .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Set `BACKEND_URL` in `.env.local` to your Render backend origin, for example `https://your-service.onrender.com`. Open http://localhost:3000. On macOS/Linux use `npm` instead of `npm.cmd`.

For a local backend use `http://localhost:8001`. Local development against a production backend retains its Secure session cookie; use localhost (supported by browsers as a secure development context), or an HTTPS Vercel preview if your browser blocks the cookie.

## Deploy to Vercel

1. Push the project, including `frontend/package-lock.json`, to your GitHub repository.
2. Import the repository in Vercel and set **Root Directory** to `frontend` if the repository root contains `src`, `website`, and `render.yaml`. If the GitHub repository contains the enclosing `Customer-Support-Agent` directory, set it to `Customer-Support-Agent/frontend` instead.
3. Select **Next.js** as the framework. Keep the default install/build/output settings. Use Node.js 24.
4. Add the server-only environment variable `BACKEND_URL=https://your-service.onrender.com` for Production and any Preview environments you use. It must match Render's `APP_ORIGIN` exactly, without a path or trailing slash. Do not prefix it with `NEXT_PUBLIC_`.
5. Deploy. Open `/` for customer chat and `/admin/inbox` for staff. Use your existing Render staff access key to unlock the inbox.

Keep Render's `APP_ORIGIN` set to the **Render backend origin**, not the Vercel URL. The proxy validates frontend request origins and forwards allowed API requests with the backend origin. The existing TrustedHost and origin checks remain enabled. No CORS changes are needed. Keep the existing database, persistence settings, and all AI/provider keys on Render. Do not copy the backend `.env` into the frontend.

Changing Vercel environment variables requires a new deployment. Vercel previews and production have separate first-party session cookies, so chats from the original Render domain will not automatically appear on the Vercel domain.

## Startup behavior and time limits

The page renders without waiting for Render. Chat checks `/readyz`, retries temporary startup failures for up to roughly four minutes, and shows a reconnect button if startup fails. Customers can draft a question while waiting. Chat submissions are not automatically repeated; a failed submission retains the request ID when the same question is retried, matching the backend's idempotency behavior.

The server proxy declares a 300-second maximum function duration; chat upstream requests time out after 230 seconds. Your Vercel project's plan/runtime must permit this duration (enable Fluid compute if needed). If your project's limit is shorter, long chat requests can still time out. Readiness checks use short requests and browser retries so a cold start does not depend on one long function invocation.

Moving the frontend does not remove Render's backend cold starts. An always-on backend instance is needed if the first answer must be available without waiting for startup. The API proxy also means Render sees the proxy's network address for its existing IP rate limit, so that limit can be shared across customers. Review the backend's trusted-proxy/rate-limit strategy before scaling traffic; never trust a client-supplied forwarded IP blindly.

## Verify

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:smoke
npm.cmd run start
```

After deployment check session creation, a new conversation, a chat answer with sources, a page refresh restoring history, a staff reply appearing in chat, and a status update. Also test reconnect after the backend has been idle. Existing `website/` files and the Python backend remain available for the current Render deployment.

The smoke check starts temporary local servers and verifies page serving, cookie and authorization forwarding, backend origin handling, CSRF rejection, endpoint restrictions, body limits, and backend status propagation. It uses a mock backend and does not exercise your deployed database or models.

References: [Next.js installation](https://nextjs.org/docs/app/getting-started/installation), [Render free-service startup behavior](https://render.com/docs/free), [Vercel function duration settings](https://vercel.com/docs/functions/configuring-functions/duration).
