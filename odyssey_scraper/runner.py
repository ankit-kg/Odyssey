from __future__ import annotations

import traceback
from dataclasses import dataclass

from .reddit_client import ScrapedComment, build_reddit, fetch_all_threads, fetch_thread_comments
from .supabase_store import (
    ExistingComment,
    build_supabase,
    fetch_existing_comments,
    fetch_versions_by_id,
    insert_log,
    insert_versions,
    mark_versions_not_latest,
    update_comments_latest_version,
    upsert_comments_metadata,
)
from .util import utc_now


@dataclass(frozen=True)
class RunResult:
    status: str  # success|failure
    error_message: str | None
    number_of_comments_processed: int


def run_scrape(*, config, run_type: str) -> RunResult:
    processed = 0

    try:
        reddit = build_reddit(config)
        sb = build_supabase(config)

        threads = fetch_all_threads(reddit, config.subreddit)

        scraped: list[ScrapedComment] = []
        for submission in threads:
            scraped.extend(fetch_thread_comments(submission))

        processed = len(scraped)

        # 1) Load existing comments + their latest version bodies
        comment_ids = [c.comment_id for c in scraped]
        existing_map = fetch_existing_comments(sb, comment_ids)

        latest_version_ids = [
            e.latest_version_id for e in existing_map.values() if e.latest_version_id is not None
        ]
        versions_by_id = fetch_versions_by_id(sb, [v for v in latest_version_ids if v is not None])

        latest_body_by_comment: dict[str, str] = {}
        for e in existing_map.values():
            if not e.latest_version_id:
                continue
            v = versions_by_id.get(e.latest_version_id)
            if v:
                latest_body_by_comment[e.comment_id] = v.body_text

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

            # New comment: always create first version (even if already deleted)
            if e is None or e.latest_version_id is None:
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
                if e.latest_version_id:
                    to_demote_version_ids.append(e.latest_version_id)
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
        mark_versions_not_latest(sb, to_demote_version_ids)
        inserted = insert_versions(sb, to_insert_versions)

        # 5) Update latest_version_id pointers
        latest_updates = [
            {"comment_id": row["comment_id"], "latest_version_id": row["version_id"]} for row in inserted
        ]
        update_comments_latest_version(sb, latest_updates)

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


