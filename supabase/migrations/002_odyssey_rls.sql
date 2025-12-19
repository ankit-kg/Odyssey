-- Odyssey RLS: lock down tables so they are not publicly accessible
-- Default posture: only `service_role` can read/insert/update. No deletes.

-- Enable RLS
alter table public.odyssey_comments enable row level security;
alter table public.odyssey_comment_versions enable row level security;
alter table public.odyssey_logs enable row level security;

-- Revoke broad grants (defense-in-depth; RLS still applies for PostgREST)
revoke all on table public.odyssey_comments from anon, authenticated;
revoke all on table public.odyssey_comment_versions from anon, authenticated;
revoke all on table public.odyssey_logs from anon, authenticated;

-- Allow service_role to operate (scraper uses SUPABASE_SERVICE_ROLE_KEY)
grant select, insert, update on table public.odyssey_comments to service_role;
grant select, insert, update on table public.odyssey_comment_versions to service_role;
grant select, insert, update on table public.odyssey_logs to service_role;

-- Needed for bigserial on odyssey_logs
grant usage, select on sequence public.odyssey_logs_log_id_seq to service_role;

-- Policies: service_role only
drop policy if exists odyssey_comments_service_role_select on public.odyssey_comments;
create policy odyssey_comments_service_role_select
  on public.odyssey_comments
  for select
  to service_role
  using (true);

drop policy if exists odyssey_comments_service_role_insert on public.odyssey_comments;
create policy odyssey_comments_service_role_insert
  on public.odyssey_comments
  for insert
  to service_role
  with check (true);

drop policy if exists odyssey_comments_service_role_update on public.odyssey_comments;
create policy odyssey_comments_service_role_update
  on public.odyssey_comments
  for update
  to service_role
  using (true)
  with check (true);

drop policy if exists odyssey_comment_versions_service_role_select on public.odyssey_comment_versions;
create policy odyssey_comment_versions_service_role_select
  on public.odyssey_comment_versions
  for select
  to service_role
  using (true);

drop policy if exists odyssey_comment_versions_service_role_insert on public.odyssey_comment_versions;
create policy odyssey_comment_versions_service_role_insert
  on public.odyssey_comment_versions
  for insert
  to service_role
  with check (true);

drop policy if exists odyssey_comment_versions_service_role_update on public.odyssey_comment_versions;
create policy odyssey_comment_versions_service_role_update
  on public.odyssey_comment_versions
  for update
  to service_role
  using (true)
  with check (true);

drop policy if exists odyssey_logs_service_role_select on public.odyssey_logs;
create policy odyssey_logs_service_role_select
  on public.odyssey_logs
  for select
  to service_role
  using (true);

drop policy if exists odyssey_logs_service_role_insert on public.odyssey_logs;
create policy odyssey_logs_service_role_insert
  on public.odyssey_logs
  for insert
  to service_role
  with check (true);

drop policy if exists odyssey_logs_service_role_update on public.odyssey_logs;
create policy odyssey_logs_service_role_update
  on public.odyssey_logs
  for update
  to service_role
  using (true)
  with check (true);


