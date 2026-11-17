revoke execute on function public.splits_ingest(text, jsonb, jsonb, boolean, text) from authenticated;
comment on function public.splits_ingest(text, jsonb, jsonb, boolean, text) is 'Splits Garmin sync: token-gated, write-only. Intentionally callable by anon; rejects calls without a valid sync token.';
comment on table public.splits_sync_tokens is 'Hashes of Splits sync tokens. No RLS policies on purpose: only security-definer functions touch it.';
