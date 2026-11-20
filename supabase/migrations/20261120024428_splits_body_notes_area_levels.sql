alter table public.splits_body_notes
  add column if not exists area_levels jsonb not null default '{}'::jsonb;
comment on column public.splits_body_notes.area_levels is
  'Pain 0-10 per area, e.g. {"plantar_fascia": 9, "hips": 2}. severity holds the highest of these (or the overall score when no area is tagged).';
-- Existing notes had one score for the whole note: copy it to each tagged area.
update public.splits_body_notes n
   set area_levels = (select coalesce(jsonb_object_agg(a, n.severity), '{}'::jsonb) from unnest(n.areas) a)
 where n.area_levels = '{}'::jsonb and n.severity is not null and cardinality(n.areas) > 0;
