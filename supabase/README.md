# Supabase schema

Migrations for the season-tools app (`backend/` + `frontend/`) -- not
related to the draft-day copilot in `src/`, which has no database.

## Applying migrations

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

Or paste a migration file's SQL directly into the Supabase dashboard's SQL
editor -- fine for a single-developer project at this size.

If the Supabase CLI hasn't been run against this repo yet, `supabase init`
will fill in the rest of `config.toml`'s default sections; the checked-in
version only pins `project_id` so `supabase link` has something to attach to.

## Current tables

- `leagues` -- one row per Sleeper league a user has connected. RLS-scoped
  to `auth.uid() = user_id`.

## Deliberately not built yet

Rosters, matchups, trades, waiver alerts, and opponent behavioral profiles
all need their own tables eventually (see the season-tools feature
backlog), but none are created yet -- add each as its own migration when
that feature is actually implemented, scoped to what it actually needs.
Pre-creating empty tables for unbuilt features isn't worth the schema churn
risk of guessing wrong about their shape now.
