from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import praw
import prawcore
import threading
import time

from .config import Config
from .util import ensure_jsonable_dict, from_utc_timestamp, to_iso, utc_now, with_retry_once


DELETED_MARKERS = {"[deleted]", "[removed]"}
RAW_DROP_KEYS = {
    # Only used if we must fall back to vars(comment) (should be rare).
    # Never persist client internals / cyclic structures.
    "_reddit",
    "_submission",
    "_mod",
    "mod",
    "subreddit",
    "replies",
    "_replies",
    "_comments_by_id",
}


@dataclass(frozen=True)
class ScrapedComment:
    comment_id: str
    thread_id: str
    parent_comment_id: str | None
    author_username: str | None
    created_utc_iso: str
    body_text: str
    edited_utc_iso: str | None
    score: int | None
    permalink: str | None
    is_deleted: bool
    raw_comment_json: dict[str, Any]


def build_reddit(config: Config) -> praw.Reddit:
    kwargs = dict(
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
        user_agent=config.reddit_user_agent,
        check_for_async=False,
        # Avoid hanging forever on slow network calls.
        requestor_kwargs={"timeout": 30},
    )
    # If the subreddit is private, Reddit will return 403 unless we authenticate as a user
    # who has access. Prefer refresh tokens (works with 2FA); fall back to password grant.
    if config.reddit_refresh_token:
        kwargs["refresh_token"] = config.reddit_refresh_token
    elif config.reddit_username and config.reddit_password:
        kwargs["username"] = config.reddit_username
        kwargs["password"] = config.reddit_password
    return praw.Reddit(**kwargs)


def _normalize_fullname(fullname: str) -> tuple[str, str]:
    """
    fullname: t1_xxx (comment) or t3_xxx (submission)
    returns (kind, id_without_prefix)
    """
    if "_" not in fullname:
        return ("", fullname)
    kind, raw_id = fullname.split("_", 1)
    return (kind, raw_id)


def fetch_all_threads(reddit: praw.Reddit, subreddit_name: str) -> list[praw.models.Submission]:
    """
    Required: do not rely on hardcoded IDs. Treat every post as a thread.

    Reddit listing endpoints can have practical limits; for this subreddit (few fixed threads),
    this is sufficient. We union multiple sorts to reduce odds of missing stickies/old threads.
    """
    sub = reddit.subreddit(subreddit_name)
    seen: dict[str, praw.models.Submission] = {}

    def add_all(it: Iterable[praw.models.Submission]) -> None:
        for s in it:
            seen[s.id] = s

    def do_fetch() -> None:
        add_all(sub.new(limit=None))
        add_all(sub.hot(limit=None))
        add_all(sub.top(time_filter="all", limit=None))

    with_retry_once(lambda: _praw_guard(do_fetch))
    return list(seen.values())


def fetch_thread_comments(submission: praw.models.Submission) -> list[ScrapedComment]:
    """
    Fully expand the comment tree and return a flat list of all comments.
    """

    def do_fetch() -> list[ScrapedComment]:
        # Always work with a fresh Submission instance for this thread. This prevents
        # PRAW's DuplicateReplaceException in cases where replace_more partially mutates
        # internal state and we retry.
        fresh = submission._reddit.submission(id=submission.id)  # type: ignore[attr-defined]

        # IMPORTANT:
        # Do NOT call replace_more() with a small limit in a loop.
        # PRAW's implementation will "skip and remove" remaining MoreComments once the limit is hit,
        # which drops comments and causes under-counting.
        #
        # Expand in a single call with a very high limit so we don't hit the limit (which would
        # cause PRAW to drop remaining MoreComments).
        #
        # We keep a heartbeat that DOES NOT touch PRAW internals, only prints liveness.
        try:
            mc = fresh.comments._gather_more_comments(fresh.comments._comments)  # type: ignore[attr-defined]
            if mc is not None:
                print(f"    expanding_morecomments: initial≈{len(mc)}", flush=True)
        except Exception:
            pass

        stop = threading.Event()
        start = time.monotonic()

        def heartbeat() -> None:
            while not stop.is_set():
                elapsed_s = int(time.monotonic() - start)
                print(f"    expanding_morecomments: still working... elapsed={elapsed_s}s", flush=True)
                stop.wait(30)

        t = threading.Thread(target=heartbeat, daemon=True)
        t.start()
        try:
            fresh.comments.replace_more(limit=100000, threshold=0)
        finally:
            stop.set()
            t.join(timeout=1)
        all_comments = fresh.comments.list()

        out: list[ScrapedComment] = []
        for c in all_comments:
            if not isinstance(c, praw.models.Comment):
                continue

            _, thread_id = _normalize_fullname(getattr(c, "link_id", f"t3_{fresh.id}"))
            parent_kind, parent_id = _normalize_fullname(getattr(c, "parent_id", ""))
            parent_comment_id = parent_id if parent_kind == "t1" else None

            author = getattr(c, "author", None)
            author_username = getattr(author, "name", None) if author else None

            body_text = getattr(c, "body", "") or ""
            is_deleted = (body_text in DELETED_MARKERS) or (author_username is None)

            created_utc = getattr(c, "created_utc", None)
            if created_utc is None:
                # Fallback: treat as "now" if missing (should be rare)
                created_utc_iso = to_iso(utc_now())
            else:
                created_utc_iso = to_iso(from_utc_timestamp(created_utc))

            edited = getattr(c, "edited", None)
            edited_utc_iso = None
            if edited and isinstance(edited, (int, float)):
                edited_utc_iso = to_iso(from_utc_timestamp(float(edited)))

            permalink = getattr(c, "permalink", None)
            if permalink and permalink.startswith("/"):
                permalink = "https://www.reddit.com" + permalink

            # Best-effort "raw Reddit API response":
            # In PRAW, the actual payload from Reddit is stored on the object as `_data`.
            raw_payload = getattr(c, "_data", None)
            if isinstance(raw_payload, dict) and raw_payload:
                raw = ensure_jsonable_dict(raw_payload)
            else:
                # Fallback (lossy): object snapshot minus cyclic internals.
                raw_src = {k: v for k, v in vars(c).items() if k not in RAW_DROP_KEYS}
                if "author" in raw_src:
                    author_obj = raw_src.get("author")
                    raw_src["author"] = getattr(author_obj, "name", None) if author_obj else None
                raw = ensure_jsonable_dict(raw_src)

            out.append(
                ScrapedComment(
                    comment_id=str(getattr(c, "id")),
                    thread_id=str(thread_id),
                    parent_comment_id=parent_comment_id,
                    author_username=author_username,
                    created_utc_iso=str(created_utc_iso),
                    body_text=body_text,
                    edited_utc_iso=edited_utc_iso,
                    score=getattr(c, "score", None),
                    permalink=permalink,
                    is_deleted=is_deleted,
                    raw_comment_json=raw,
                )
            )
        return out

    # Retry once (required behavior). Each attempt uses a fresh Submission object.
    return with_retry_once(lambda: _praw_guard(do_fetch))


def _praw_guard(fn: Any):
    """
    Normalize PRAW rate-limit errors so the caller's single-retry policy applies.
    """
    try:
        return fn()
    except prawcore.exceptions.TooManyRequests as e:
        # Required: treat rate limits as failures, but allow a single retry.
        # If Reddit tells us how long to wait, honor it.
        import time

        retry_after = None
        try:
            retry_after = int(e.response.headers.get("retry-after"))  # type: ignore[union-attr]
        except Exception:
            retry_after = None
        time.sleep(retry_after or 2)
        raise
    except (prawcore.exceptions.PrawcoreException, Exception):
        raise


