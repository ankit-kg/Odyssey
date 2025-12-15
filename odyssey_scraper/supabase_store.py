from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from supabase import Client, create_client

from .config import Config
from .util import utc_now


COMMENTS_TABLE = "odyssey_comments"
VERSIONS_TABLE = "odyssey_comment_versions"
LOGS_TABLE = "odyssey_logs"


@dataclass(frozen=True)
class ExistingComment:
    comment_id: str
    latest_version_id: str | None
    is_deleted: bool


@dataclass(frozen=True)
class ExistingVersion:
    version_id: str
    comment_id: str
    body_text: str


def build_supabase(config: Config) -> Client:
    return create_client(config.supabase_url, config.supabase_service_role_key)


def insert_log(
    sb: Client,
    *,
    run_type: str,
    status: str,
    error_message: str | None,
    number_of_comments_processed: int,
) -> None:
    sb.table(LOGS_TABLE).insert(
        {
            "run_type": run_type,
            "status": status,
            "error_message": error_message,
            "number_of_comments_processed": number_of_comments_processed,
        }
    ).execute()


def chunked(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_existing_comments(sb: Client, comment_ids: list[str]) -> dict[str, ExistingComment]:
    """
    Batch-load existing comments and their latest_version_id.
    """
    out: dict[str, ExistingComment] = {}
    if not comment_ids:
        return out

    for batch in chunked(comment_ids, 500):
        resp = (
            sb.table(COMMENTS_TABLE)
            .select("comment_id,latest_version_id,is_deleted")
            .in_("comment_id", batch)
            .execute()
        )
        for row in resp.data or []:
            out[str(row["comment_id"])] = ExistingComment(
                comment_id=str(row["comment_id"]),
                latest_version_id=str(row["latest_version_id"]) if row.get("latest_version_id") else None,
                is_deleted=bool(row.get("is_deleted") or False),
            )
    return out


def fetch_versions_by_id(sb: Client, version_ids: list[str]) -> dict[str, ExistingVersion]:
    out: dict[str, ExistingVersion] = {}
    if not version_ids:
        return out

    for batch in chunked(version_ids, 500):
        resp = (
            sb.table(VERSIONS_TABLE)
            .select("version_id,comment_id,body_text")
            .in_("version_id", batch)
            .execute()
        )
        for row in resp.data or []:
            out[str(row["version_id"])] = ExistingVersion(
                version_id=str(row["version_id"]),
                comment_id=str(row["comment_id"]),
                body_text=str(row.get("body_text") or ""),
            )
    return out


def upsert_comments_metadata(sb: Client, rows: list[dict[str, Any]]) -> None:
    """
    Upsert metadata only. We intentionally do NOT include latest_version_id here,
    to avoid accidental overwrites.
    """
    if not rows:
        return
    sb.table(COMMENTS_TABLE).upsert(rows, on_conflict="comment_id").execute()


def insert_versions(sb: Client, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Inserts version rows and returns inserted rows (including version_id).
    """
    if not rows:
        return []
    resp = sb.table(VERSIONS_TABLE).insert(rows).execute()
    return resp.data or []


def mark_versions_not_latest(sb: Client, version_ids: list[str]) -> None:
    if not version_ids:
        return
    for batch in chunked(version_ids, 500):
        sb.table(VERSIONS_TABLE).update({"is_latest": False}).in_("version_id", batch).execute()


def update_comments_latest_version(sb: Client, updates: list[dict[str, Any]]) -> None:
    """
    updates: [{comment_id, latest_version_id}]
    """
    if not updates:
        return
    # Supabase/PostgREST doesn't support bulk update by multiple PKs in one call;
    # we do individual updates (still fine for this subreddit size).
    for u in updates:
        sb.table(COMMENTS_TABLE).update(
            {"latest_version_id": u["latest_version_id"], "last_seen_utc": utc_now().isoformat()}
        ).eq("comment_id", u["comment_id"]).execute()


def update_comments_deleted_flag(sb: Client, comment_ids: list[str], is_deleted: bool) -> None:
    if not comment_ids:
        return
    for batch in chunked(comment_ids, 500):
        sb.table(COMMENTS_TABLE).update({"is_deleted": is_deleted, "last_seen_utc": utc_now().isoformat()}).in_(
            "comment_id", batch
        ).execute()


