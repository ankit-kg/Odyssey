from __future__ import annotations

import traceback
from dataclasses import dataclass

from .reddit_client import ScrapedComment, build_reddit, fetch_all_threads, fetch_thread_comments
from .supabase_store import (
    ExistingComment,
    build_supabase,
    fetch_existing_comments,
    fetch_latest_versions_for_comments,
    fetch_versions_by_id,
    insert_log,
    insert_versions,
    mark_versions_not_latest,
    upsert_comments_metadata,
)
from .util import utc_now


@dataclass(frozen=True)
class RunResult:
    status: str  # success|failure
    error_message: str | None
    number_of_comments_processed: int


def run_scrape(*, config, run_type: str, dry_run: bool = False, thread_limit: int | None = None) -> RunResult:
    processed = 0

    try:
        reddit = build_reddit(config)

        threads = fetch_all_threads(reddit, config.subreddit)
        if thread_limit is not None:
            threads = threads[: max(0, int(thread_limit))]

        scraped: list[ScrapedComment] = []
        for i, submission in enumerate(threads, start=1):
            title = getattr(submission, "title", "") or ""
            print(f"Scanning thread {i}/{len(threads)}: t3_{submission.id} {title[:80]}")
            thread_comments = fetch_thread_comments(submission)
            print(f"  fetched_comments={len(thread_comments)}")
            scraped.extend(thread_comments)

        processed = len(scraped)

        if dry_run:
            # No database writes; just validate scraping.
            unique_threads = len({c.thread_id for c in scraped})
            unique_comments = len({c.comment_id for c in scraped})
            print(f"[DRY RUN] threads_found={len(threads)} threads_with_comments={unique_threads} comments_found={unique_comments}")
            return RunResult(status="success", error_message=None, number_of_comments_processed=processed)

        sb = build_supabase(config)

        # 1) Load existing comments + their latest version bodies
        print(f"Writing to Supabase: comments={len(scraped)}", flush=True)
        comment_ids = [c.comment_id for c in scraped]
        existing_map = fetch_existing_comments(sb, comment_ids)

        latest_version_id_by_comment: dict[str, str] = {}
        # Primary source: odyssey_comments.latest_version_id
        for e in existing_map.values():
            if e.latest_version_id:
                latest_version_id_by_comment[e.comment_id] = e.latest_version_id

        # Fallback source: odyssey_comment_versions where is_latest=true (handles partial runs)
        missing_ptr_ids = [cid for cid, e in existing_map.items() if not e.latest_version_id]
        if missing_ptr_ids:
            latest_rows = fetch_latest_versions_for_comments(sb, missing_ptr_ids)
            for cid, v in latest_rows.items():
                latest_version_id_by_comment[cid] = v.version_id

        versions_by_id = fetch_versions_by_id(sb, list(set(latest_version_id_by_comment.values())))
        latest_body_by_comment: dict[str, str] = {}
        for cid, vid in latest_version_id_by_comment.items():
            v = versions_by_id.get(vid)
            if v:
                latest_body_by_comment[cid] = v.body_text

        # 2) Upsert comment metadata (no version writes yet)
        now_iso = utc_now().isoformat()
        comment_rows = [
            {
                "comment_id": c.comment_id,
                "thread_id": c.thread_id,
                "parent_comment_id": c.parent_comment_id,
                "author_username": c.author_username,
                "created_utc": c.created_utc_iso,
                "score": c.score,
                "permalink": c.permalink,
                # Preserve deletion status once set true
                "is_deleted": bool(
                    c.is_deleted or (existing_map.get(c.comment_id).is_deleted if existing_map.get(c.comment_id) else False)
                ),
                "raw_comment_json": c.raw_comment_json,
                "last_seen_utc": now_iso,
            }
            for c in scraped
        ]
        upsert_comments_metadata(sb, comment_rows)

        # 3) Decide which versions to insert
        to_insert_versions: list[dict] = []
        to_demote_version_ids: list[str] = []

        for c in scraped:
            e: ExistingComment | None = existing_map.get(c.comment_id)
            effective_latest_vid = latest_version_id_by_comment.get(c.comment_id)

            # New comment: always create first version (even if already deleted)
            if e is None or effective_latest_vid is None:
                to_insert_versions.append(
                    {
                        "comment_id": c.comment_id,
                        "body_text": c.body_text,
                        "edited_utc": c.edited_utc_iso,
                        "retrieved_utc": now_iso,
                        "is_latest": True,
                    }
                )
                continue

            # Existing comment becomes deleted: mark deletion via metadata upsert, but
            # DO NOT create a new version that overwrites last known body text.
            if c.is_deleted or (e.is_deleted if e else False):
                continue

            latest_body = latest_body_by_comment.get(c.comment_id)
            if latest_body is None:
                # If we somehow have no latest body, treat it as insertable content.
                to_insert_versions.append(
                    {
                        "comment_id": c.comment_id,
                        "body_text": c.body_text,
                        "edited_utc": c.edited_utc_iso,
                        "retrieved_utc": now_iso,
                        "is_latest": True,
                    }
                )
                continue

            if c.body_text != latest_body:
                if effective_latest_vid:
                    to_demote_version_ids.append(effective_latest_vid)
                to_insert_versions.append(
                    {
                        "comment_id": c.comment_id,
                        "body_text": c.body_text,
                        "edited_utc": c.edited_utc_iso,
                        "retrieved_utc": now_iso,
                        "is_latest": True,
                    }
                )

        # 4) Apply version changes
        print(f"Updating versions: demote={len(to_demote_version_ids)} insert={len(to_insert_versions)}", flush=True)
        mark_versions_not_latest(sb, to_demote_version_ids)
        inserted = insert_versions(sb, to_insert_versions)

        # 5) Update latest_version_id pointers
        if inserted or to_demote_version_ids:
            print("Refreshing latest_version_id pointers in DB (SQL function)", flush=True)
            sb.rpc("odyssey_refresh_latest_version_ids", {}).execute()

        insert_log(
            sb,
            run_type=run_type,
            status="success",
            error_message=None,
            number_of_comments_processed=processed,
        )
        return RunResult(status="success", error_message=None, number_of_comments_processed=processed)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        try:
            # If we can't even build the Supabase client, logging will fail too.
            if not dry_run:
                sb = build_supabase(config)
                insert_log(
                    sb,
                    run_type=run_type,
                    status="failure",
                    error_message=err[:8000],
                    number_of_comments_processed=processed,
                )
        except Exception:
            # If logging also fails, we still want the process to exit with failure.
            pass
        return RunResult(status="failure", error_message=err, number_of_comments_processed=processed)


