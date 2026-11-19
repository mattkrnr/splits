-- How Matt's body feels: free text plus confirmed tags, for the Splits plan and later analysis.
create table if not exists public.splits_body_notes (
  id        bigint generated always as identity primary key,
  user_id   uuid not null default auth.uid() references auth.users(id) on delete cascade,
  noted_at  timestamptz not null default now(),
  note      text not null default '',
  areas     text[] not null default '{}',      -- e.g. plantar_fascia, calves, it_band, hips, knees, shins, back, shoulders
  feeling   text not null default 'sore' check (feeling in ('good', 'ok', 'tight', 'sore', 'pain')),
  severity  smallint check (severity between 0 and 10),  -- 0 = no pain, 10 = worst
  context   text not null default 'none' check (context in ('none', 'during_run', 'after_run', 'during_lift', 'after_lift', 'other'))
);
create index if not exists splits_body_notes_user_time on public.splits_body_notes (user_id, noted_at desc);
alter table public.splits_body_notes enable row level security;
create policy "splits own rows" on public.splits_body_notes for all to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
revoke all on public.splits_body_notes from anon;
comment on table public.splits_body_notes is 'Splits: body notes (how it feels, pain by area). areas are tags like plantar_fascia, calves, it_band, hips; severity 0-10; context says if it was during/after a run or lift.';
