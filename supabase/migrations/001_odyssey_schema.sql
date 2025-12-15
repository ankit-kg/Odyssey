-- Odyssey schema: comments + comment versions + run logs
-- Safe to run once on a fresh Supabase Postgres database.

create extension if not exists pgcrypto;

-- 1) Stable identity + metadata (never delete rows)
create table if not exists public.odyssey_comments (
  comment_id text primary key,                 -- Reddit comment ID (without t1_)
  thread_id text not null,                     -- Reddit submission ID (without t3_)
  parent_comment_id text null,                 -- Reddit parent comment ID (without t1_), null if top-level
  author_username text null,                   -- null when deleted/suspended
  created_utc timestamptz not null,
  score integer null,
  permalink text null,
  is_deleted boolean not null default false,
  latest_version_id uuid null,
  raw_comment_json jsonb not null,
  first_seen_utc timestamptz not null default now(),
  last_seen_utc timestamptz not null default now()
);

-- 2) Content history (never delete rows)
create table if not exists public.odyssey_comment_versions (
  version_id uuid primary key default gen_random_uuid(),
  comment_id text not null references public.odyssey_comments(comment_id) on delete restrict,
  body_text text not null,
  edited_utc timestamptz null,
  retrieved_utc timestamptz not null default now(),
  is_latest boolean not null default true
);

-- FK from comments.latest_version_id → versions.version_id
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'odyssey_comments_latest_version_id_fkey'
  ) then
    alter table public.odyssey_comments
      add constraint odyssey_comments_latest_version_id_fkey
      foreign key (latest_version_id)
      references public.odyssey_comment_versions(version_id)
      on delete restrict;
  end if;
end $$;

create index if not exists odyssey_comment_versions_comment_id_idx
  on public.odyssey_comment_versions(comment_id);

create index if not exists odyssey_comment_versions_is_latest_idx
  on public.odyssey_comment_versions(comment_id, is_latest)
  where is_latest = true;

create index if not exists odyssey_comments_thread_id_idx
  on public.odyssey_comments(thread_id);

-- Guardrail: only one "latest" version per comment
create unique index if not exists odyssey_comment_versions_one_latest_per_comment
  on public.odyssey_comment_versions(comment_id)
  where is_latest = true;

-- 3) Run logs
create table if not exists public.odyssey_logs (
  log_id bigserial primary key,
  run_timestamp timestamptz not null default now(),
  run_type text not null check (run_type in ('initial', 'scheduled')),
  status text not null check (status in ('success', 'failure')),
  error_message text null,
  number_of_comments_processed bigint not null default 0
);


