alter table public.splits_lift_sets
  add column if not exists multiplier double precision not null default 1,  -- Fitbod: 2 = pair of dumbbells, 0 = timed/cardio
  add column if not exists duration_s double precision,
  add column if not exists distance_m double precision;
comment on column public.splits_lift_sets.weight_lb is 'Weight per implement as entered in Fitbod (per dumbbell), converted to lb';
