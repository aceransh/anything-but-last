# Season Tools Backend

A separate FastAPI service for in-season fantasy features (weekly lineup
optimizer, trades, waivers, etc. -- not yet built). This is **not** the
draft-day copilot in `src/`, which stays local-only and unmodified; this
service is deployed and multi-user, backed by Supabase (Postgres + Auth).

## Local dev

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase project's URL/keys
uvicorn app.main:app --reload --port 8001
```

Runs on port 8001 (not 8000) so it can run alongside the draft tool's own
server during development.

## Applying the schema

Migrations live in `../supabase/migrations/`. Apply them to your Supabase
project with the Supabase CLI:

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

Or paste the migration SQL directly into the Supabase dashboard's SQL editor.

## Auth model

The frontend authenticates with Supabase Auth and sends the resulting JWT
as `Authorization: Bearer <token>` on every request. `app/deps.py` verifies
that JWT against Supabase's own JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`)
via `PyJWKClient` -- this project's Supabase instance uses rotating
asymmetric signing keys with no static legacy secret exposed, so there's no
shared-secret env var to verify against; the JWKS endpoint serves public
verification keys and handles key rotation (current + previous key)
transparently. Every route depends on `get_current_user` to get the
caller's `user_id`. The backend itself connects to Supabase with the
**service role (secret) key** (bypasses Row Level Security), so every query
must filter by that `user_id` explicitly -- RLS policies on each table are
the defense-in-depth backstop, not the only gate.
