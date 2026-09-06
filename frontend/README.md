# Season Tools Frontend

Vite + React + TypeScript app for in-season fantasy features (weekly lineup
optimizer, trades, waivers, etc. -- not yet built). This is a separate app
from the draft-day copilot's own page (`src/ui/templates/index.html`),
which stays local-only and unmodified. This one is deployed (Vercel) and
talks to a separately-deployed backend (`../backend`), authenticating via
Supabase Auth.

## Local dev

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in your Supabase project's URL/anon key
npm run dev
```

Runs on Vite's default port, 5173. Point `VITE_API_BASE_URL` at the backend
(`http://localhost:8001` for local dev, run alongside this from `../backend`
-- see its README).

## What's here so far

Just the vertical slice proving the stack works end to end: sign up/sign in
(`src/pages/Login.tsx`), connect a Sleeper league
(`src/pages/ConnectLeague.tsx`), and see your connected leagues
(`src/pages/Dashboard.tsx`). `src/lib/api.ts` is the one place that attaches
the Supabase session's JWT to backend requests -- any future feature page
should call the backend through it, not `fetch` directly.
