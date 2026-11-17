-- Splits (fitness app) tables. Every row belongs to one signed-in user.
-- Applied to the "Personal" Supabase project, which other personal apps share (each uses its own table prefix).
create table if not exists public.splits_activities (
  user_id    uuid        not null default auth.uid() references auth.users(id) on delete cascade,
  id         text        not null,
  start_time timestamptz not null,
  type       text        not null,
  name       text,
  meters     double precision,
  seconds    double precision,
  avg_hr     double precision,
  raw        jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);
create index if not exists splits_activities_user_time on public.splits_activities (user_id, start_time);

create table if not exists public.splits_sleep_nights (
  user_id    uuid    not null default auth.uid() references auth.users(id) on delete cascade,
  cal        date    not null,
  seconds    integer not null,
  deep       integer,
  light      integer,
  rem        integer,
  awake      integer,
  score      integer,
  updated_at timestamptz not null default now(),
  primary key (user_id, cal)
);

create table if not exists public.splits_lift_sets (
  id           bigint generated always as identity primary key,
  user_id      uuid        not null default auth.uid() references auth.users(id) on delete cascade,
  performed_at timestamptz not null,
  exercise     text        not null,
  reps         double precision not null default 0,
  weight_lb    double precision not null default 0,
  warmup       boolean     not null default false
);
create index if not exists splits_lift_sets_user_time on public.splits_lift_sets (user_id, performed_at);

create table if not exists public.splits_sync_status (
  user_id  uuid primary key references auth.users(id) on delete cascade,
  last_run timestamptz not null default now(),
  ok       boolean not null,
  message  text
);

-- Write-only sync tokens. Only a hash is stored; no client can read this table.
create table if not exists public.splits_sync_tokens (
  token_hash text primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

alter table public.splits_activities   enable row level security;
alter table public.splits_sleep_nights enable row level security;
alter table public.splits_lift_sets    enable row level security;
alter table public.splits_sync_status  enable row level security;
alter table public.splits_sync_tokens  enable row level security;

create policy "splits own rows" on public.splits_activities for all to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "splits own rows" on public.splits_sleep_nights for all to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "splits own rows" on public.splits_lift_sets for all to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "splits read own status" on public.splits_sync_status for select to authenticated
  using ((select auth.uid()) = user_id);
-- splits_sync_tokens: no policies on purpose (no client access at all).

-- Signed-in user creates a new sync token; any older token for them stops working.
create or replace function public.splits_new_sync_token()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_token text;
begin
  if v_uid is null then
    raise exception 'Sign in first';
  end if;
  v_token := 'splits_' || replace(pg_catalog.gen_random_uuid()::text, '-', '') || replace(pg_catalog.gen_random_uuid()::text, '-', '');
  delete from public.splits_sync_tokens where user_id = v_uid;
  insert into public.splits_sync_tokens (token_hash, user_id)
    values (pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v_token, 'UTF8')), 'hex'), v_uid);
  return v_token;
end $$;

-- The GitHub Action calls this with the token. It can only add/update fitness rows
-- for the token's owner and record sync status. It cannot read anything.
create or replace function public.splits_ingest(
  p_token text,
  p_activities jsonb default '[]'::jsonb,
  p_sleep jsonb default '[]'::jsonb,
  p_ok boolean default null,
  p_message text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid;
  v_acts integer := 0;
  v_sleep integer := 0;
begin
  select user_id into v_uid from public.splits_sync_tokens
   where token_hash = pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(coalesce(p_token, ''), 'UTF8')), 'hex');
  if v_uid is null then
    raise exception 'Invalid sync token' using errcode = '28000';
  end if;

  insert into public.splits_activities as t (user_id, id, start_time, type, name, meters, seconds, avg_hr, raw, updated_at)
  select distinct on (a->>'id')
         v_uid, a->>'id', (a->>'start_time')::timestamptz, coalesce(nullif(a->>'type', ''), 'other'), a->>'name',
         (a->>'meters')::double precision, (a->>'seconds')::double precision, (a->>'avg_hr')::double precision, a->'raw', now()
    from pg_catalog.jsonb_array_elements(coalesce(p_activities, '[]'::jsonb)) a
   where a->>'id' is not null and a->>'start_time' is not null
  on conflict (user_id, id) do update set
    start_time = excluded.start_time, type = excluded.type, name = excluded.name, meters = excluded.meters,
    seconds = excluded.seconds, avg_hr = excluded.avg_hr, raw = excluded.raw, updated_at = now();
  get diagnostics v_acts = row_count;

  insert into public.splits_sleep_nights as t (user_id, cal, seconds, deep, light, rem, awake, score, updated_at)
  select distinct on (s->>'cal')
         v_uid, (s->>'cal')::date, (s->>'seconds')::integer, (s->>'deep')::integer, (s->>'light')::integer,
         (s->>'rem')::integer, (s->>'awake')::integer, (s->>'score')::integer, now()
    from pg_catalog.jsonb_array_elements(coalesce(p_sleep, '[]'::jsonb)) s
   where s->>'cal' is not null and s->>'seconds' is not null
  on conflict (user_id, cal) do update set
    seconds = excluded.seconds, deep = excluded.deep, light = excluded.light, rem = excluded.rem,
    awake = excluded.awake, score = excluded.score, updated_at = now();
  get diagnostics v_sleep = row_count;

  if p_ok is not null then
    insert into public.splits_sync_status (user_id, last_run, ok, message)
    values (v_uid, now(), p_ok, left(p_message, 500))
    on conflict (user_id) do update set last_run = now(), ok = excluded.ok, message = excluded.message;
  end if;

  return pg_catalog.jsonb_build_object('activities', v_acts, 'sleep', v_sleep);
end $$;

revoke all on function public.splits_new_sync_token() from public, anon;
grant execute on function public.splits_new_sync_token() to authenticated;
revoke all on function public.splits_ingest(text, jsonb, jsonb, boolean, text) from public;
grant execute on function public.splits_ingest(text, jsonb, jsonb, boolean, text) to anon, authenticated;
