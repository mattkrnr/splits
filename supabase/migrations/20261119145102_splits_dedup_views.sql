-- Is a Fitbod exercise name a run? Whole words only, so "Crunches" is not a run.
create or replace function public.splits_is_run_exercise(p_exercise text)
returns boolean
language sql
immutable
set search_path = ''
as $$ select coalesce(p_exercise, '') ~* '\m(running|jogging|run|jog)\M' $$;

-- All activities, de-duplicated across sources. USE THIS (not the raw tables) for any analysis.
-- Rule: every Garmin activity, plus each Fitbod run that is not already on Garmin.
--  * Fitbod run = a Fitbod set whose exercise is a run and that has a distance or duration.
--  * Fitbod often imports the same run twice: rows with the same start time and distance within 2% are one run.
--  * A Fitbod run is the same as a Garmin run if it starts within 15 minutes of it, or within 3 hours
--    with distance within 10%. Those Fitbod copies are dropped.
create or replace view public.splits_activities_all with (security_invoker = true) as
with fb_raw as (
  select l.id, l.user_id, l.performed_at, l.exercise, l.distance_m, l.duration_s
    from public.splits_lift_sets l
   where public.splits_is_run_exercise(l.exercise)
     and (coalesce(l.distance_m, 0) > 0 or coalesce(l.duration_s, 0) > 0)
),
fb as (
  select a.* from fb_raw a
   where not exists (
     select 1 from fb_raw b
      where b.user_id = a.user_id and b.performed_at = a.performed_at and b.id < a.id
        and abs(coalesce(b.distance_m, 0) - coalesce(a.distance_m, 0))
            <= greatest(coalesce(a.distance_m, 0), coalesce(b.distance_m, 0), 1) * 0.02)
),
fb_only as (
  select f.* from fb f
   where not exists (
     select 1 from public.splits_activities g
      where g.user_id = f.user_id and g.type like '%run%'
        and (abs(extract(epoch from g.start_time - f.performed_at)) <= 900
             or (abs(extract(epoch from g.start_time - f.performed_at)) <= 10800
                 and coalesce(g.meters, 0) > 0 and coalesce(f.distance_m, 0) > 0
                 and abs(g.meters - f.distance_m) <= greatest(g.meters, f.distance_m) * 0.1)))
)
select g.user_id, 'garmin'::text as source, g.id, g.start_time, g.type, g.name,
       g.meters, g.seconds, g.avg_hr
  from public.splits_activities g
union all
select f.user_id, 'fitbod'::text, 'fitbod-' || f.id, f.performed_at,
       case when f.exercise ~* 'treadmill' then 'treadmill_running' else 'running' end,
       f.exercise || ' (Fitbod)', nullif(f.distance_m, 0), f.duration_s, null::double precision
  from fb_only f;

-- Strength sets without runs (runs live in splits_activities_all). USE THIS for lifting analysis.
create or replace view public.splits_strength_sets with (security_invoker = true) as
select l.* from public.splits_lift_sets l
 where not (public.splits_is_run_exercise(l.exercise)
            and (coalesce(l.distance_m, 0) > 0 or coalesce(l.duration_s, 0) > 0));

comment on view public.splits_activities_all is
  'Splits: all activities de-duplicated across Garmin and Fitbod. Use for analysis instead of the raw tables. Every Garmin activity, plus Fitbod runs not already on Garmin (same run = start within 15 min, or within 3 h with distance within 10%). Fitbod''s own double imports (same start, distance within 2%) count once. Raw data stays in splits_activities and splits_lift_sets.';
comment on view public.splits_strength_sets is
  'Splits: Fitbod sets excluding runs (runs are in splits_activities_all). Use for lifting analysis. weight_lb is per implement; multiplier 2 = pair of dumbbells, 0 = timed set.';
comment on table public.splits_activities is 'Splits raw Garmin activities. For analysis use the view splits_activities_all, which merges in Fitbod-only runs without duplicates.';
comment on table public.splits_lift_sets is 'Splits raw Fitbod export rows (includes runs Fitbod copied from the watch). For analysis use splits_strength_sets and splits_activities_all.';

revoke all on public.splits_activities_all, public.splits_strength_sets from anon;
grant select on public.splits_activities_all, public.splits_strength_sets to authenticated;
revoke all on function public.splits_is_run_exercise(text) from anon;
