-- Season Tools app -- first and only table for this phase.
--
-- Future tables (rosters, matchups, trades, waiver_alerts,
-- opponent_profiles) are intentionally NOT created here. Add each as its
-- own migration when that feature is actually implemented, scoped to what
-- that feature needs -- see supabase/README.md.

create table public.leagues (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users(id) on delete cascade,
  sleeper_league_id  text not null,
  league_name        text not null,
  season             text not null,
  created_at         timestamptz not null default now(),
  unique (user_id, sleeper_league_id)
);

alter table public.leagues enable row level security;

create policy "Users can view their own leagues"
  on public.leagues for select
  using (auth.uid() = user_id);

create policy "Users can insert their own leagues"
  on public.leagues for insert
  with check (auth.uid() = user_id);

create policy "Users can delete their own leagues"
  on public.leagues for delete
  using (auth.uid() = user_id);
