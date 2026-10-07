# AI Travel Assistant: frontend

Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, shadcn/ui (Base UI),
TanStack Query, React Hook Form and Zod.

The browser only talks to this app. `app/api/[...path]/route.ts` forwards `/api/*` to the
FastAPI backend at `BACKEND_URL` (read at request time), so the auth cookies are
first-party and httpOnly. State-changing requests send the `X-CSRF-Token` header
(`lib/api.ts`).

```bash
npm install
cp .env.example .env.local   # BACKEND_URL=http://127.0.0.1:8000
npm run dev                  # http://localhost:3000
npm run lint && npm run typecheck && npm run build
```

See [../PLATFORM.md](../PLATFORM.md) for the overall architecture and roadmap.
