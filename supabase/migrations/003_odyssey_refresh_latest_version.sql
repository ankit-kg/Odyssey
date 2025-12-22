-- Helper function: refresh odyssey_comments.latest_version_id pointers from odyssey_comment_versions
-- This avoids thousands of client-side updates and is safe with "never delete" requirements.

create or replace function public.odyssey_refresh_latest_version_ids()
returns void
language sql
security definer
set search_path = public
as $$
  update public.odyssey_comments c
  set
    latest_version_id = v.version_id,
    last_seen_utc = now()
  from public.odyssey_comment_versions v
  where
    v.comment_id = c.comment_id
    and v.is_latest = true
    and (c.latest_version_id is distinct from v.version_id);
$$;

revoke all on function public.odyssey_refresh_latest_version_ids() from public;
grant execute on function public.odyssey_refresh_latest_version_ids() to service_role;


