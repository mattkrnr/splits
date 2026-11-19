alter table public.splits_body_notes
  add column if not exists workouts jsonb not null default '[]'::jsonb;
comment on column public.splits_body_notes.workouts is
  'Workouts this note is about: [{key, at, label}]. key is garmin:<activity id>, fitbod_run:<start time ISO>, or fitbod_lift:<YYYY-MM-DD local day>.';
