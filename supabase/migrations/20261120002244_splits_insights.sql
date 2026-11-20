-- Insights Claude writes after analysing the Splits data; the app's Insights tab reads them.
create table if not exists public.splits_insights (
  id           bigint generated always as identity primary key,
  user_id      uuid not null references auth.users(id) on delete cascade,
  generated_at timestamptz not null default now(),
  sort         smallint not null default 0,
  topic        text not null check (topic in ('running', 'strength', 'sleep', 'body', 'overall')),
  tone         text not null default 'info' check (tone in ('good', 'watch', 'info')),
  title        text not null,
  stat         text,
  stat_label   text,
  body         text not null,
  series       jsonb,          -- optional small bar chart: [{"l": label, "v": number}]
  series_label text
);
create index if not exists splits_insights_user on public.splits_insights (user_id, sort);
alter table public.splits_insights enable row level security;
create policy "splits read own insights" on public.splits_insights for select to authenticated
  using ((select auth.uid()) = user_id);
revoke all on public.splits_insights from anon;
comment on table public.splits_insights is 'Splits: insights written by Claude from the Splits views (refresh by replacing all rows for the user). The app only reads them.';
