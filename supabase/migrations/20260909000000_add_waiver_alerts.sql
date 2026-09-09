-- FAAB waiver bid valuation + event-driven alerts (roadmap item 7).
--
-- discord_webhook_url is per-league (like sleeper_roster_id), not
-- per-user -- a user's leagues can point at different Discord channels.
alter table public.leagues
  add column discord_webhook_url text;

-- One row per (league, player, week) actually alerted -- the scheduled
-- scan's dedupe key, so a still-trending player doesn't re-alert every
-- run. Written by the scan job via the service-role client (bypasses
-- RLS, same as every other backend write); RLS below is what a signed-in
-- user's own read of their alert inbox is scoped by.
create table public.waiver_alerts (
  id                 uuid primary key default gen_random_uuid(),
  league_id          uuid not null references public.leagues(id) on delete cascade,
  sleeper_player_id  text not null,
  week               integer not null,
  alerted_at         timestamptz not null default now(),
  read_at            timestamptz,
  unique (league_id, sleeper_player_id, week)
);

alter table public.waiver_alerts enable row level security;

create policy "Users can view alerts for their own leagues"
  on public.waiver_alerts for select
  using (
    exists (
      select 1 from public.leagues
      where leagues.id = waiver_alerts.league_id
        and leagues.user_id = auth.uid()
    )
  );

create policy "Users can mark their own alerts read"
  on public.waiver_alerts for update
  using (
    exists (
      select 1 from public.leagues
      where leagues.id = waiver_alerts.league_id
        and leagues.user_id = auth.uid()
    )
  );
