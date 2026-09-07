-- Connecting a league and claiming which of its teams is yours are two
-- separate steps (a league has many teams) -- nullable until claimed.
alter table public.leagues
  add column sleeper_roster_id integer;
