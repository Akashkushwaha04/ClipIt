"""Multi-Platform Auto-Posting & Scheduling Queue (Feature 2).

Manages scheduling rules:
- `post_gap_min`: Spaces uploads by at least N minutes (default 45 min).
- `daily_cap`: Limits maximum posts per day per channel (default 5 posts/day).
- Status progression: `queued` ➔ `scheduled` ➔ `publishing` ➔ `published` ➔ `failed`.
Dispatches to YouTube Shorts, Instagram Reels, and TikTok via `studio/accounts.py`.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from . import accounts, config, creators, db

logger = logging.getLogger("clipforge.posting")


def _day_key(ts: float) -> str:
    """Returns YYYY-MM-DD for a unix timestamp in local time."""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def compute_next_slot(
    account_id: str,
    post_gap_min: int = 45,
    daily_cap: int = 5,
    start_time: Optional[float] = None
) -> float:
    """Calculates earliest post time respecting post_gap_min and daily_cap for the account."""
    now = time.time()
    earliest = max(now, float(start_time or now))

    # Fetch existing scheduled and published posts for this account
    all_posts = db.list_scheduled_posts()
    account_posts = [
        p for p in all_posts
        if p["account_id"] == account_id and p["status"] in ("queued", "scheduled", "published", "publishing")
    ]

    gap_seconds = max(5, int(post_gap_min)) * 60
    cap = max(1, int(daily_cap))

    # Calculate candidate timestamp
    candidate = earliest
    if account_posts:
        latest_time = max(p["scheduled_time"] for p in account_posts)
        candidate = max(candidate, latest_time + gap_seconds)

    # Respect daily cap: if candidate day already has >= cap posts, push to next day 09:00 AM
    for _ in range(30):
        c_day = _day_key(candidate)
        posts_on_day = sum(1 for p in account_posts if _day_key(p["scheduled_time"]) == c_day)
        if posts_on_day < cap:
            break
        # Shift to 9:00 AM next day
        lt = time.localtime(candidate + 86400)
        candidate = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 9, 0, 0, 0, 0, -1))

    return float(candidate)


def enqueue_post(
    clip_id: str,
    platform: str,
    account_id: str,
    title: str,
    description: str = "",
    tags: Optional[list] = None,
    scheduled_time: Optional[float] = None,
    creator_id: Optional[str] = None,
    privacy: str = "public"
) -> dict:
    """Enqueues or schedules a clip for automated publishing."""
    clip = db.get_clip(clip_id)
    if not clip:
        raise ValueError(f"Clip '{clip_id}' does not exist.")

    # Get creator spacing settings if creator is associated
    post_gap_min = 45
    daily_cap = 5
    if creator_id:
        c = creators.get_creator(creator_id)
        if c:
            post_gap_min = c.get("post_gap_min", 45)
            daily_cap = c.get("daily_cap", 5)

    # Determine slot
    if scheduled_time is not None and scheduled_time > time.time():
        slot = float(scheduled_time)
    else:
        slot = compute_next_slot(account_id, post_gap_min=post_gap_min, daily_cap=daily_cap)

    post_title = title or clip.get("title") or clip.get("hook") or "Short Video"
    post_desc = description or clip.get("description") or ""
    post_tags = tags or clip.get("tags") or []

    post_record = db.create_scheduled_post(
        clip_id=clip_id,
        platform=platform.lower(),
        account_id=account_id,
        title=post_title,
        description=post_desc,
        tags=post_tags,
        scheduled_time=slot,
        privacy=privacy
    )
    # Update status to scheduled or queued
    status = "scheduled" if slot > time.time() + 60 else "queued"
    db.update_scheduled_post(post_record["id"], status=status)
    post_record["status"] = status
    return post_record


def list_queue(status: Optional[str] = None) -> List[dict]:
    """Retrieves full post queue with clip details and live countdown timers."""
    return db.list_scheduled_posts(status=status)


def delete_post(post_id: str):
    """Cancels and deletes a queued post."""
    db.delete_scheduled_post(post_id)


def dispatch_due_posts() -> List[dict]:
    """Background engine: processes due items from queued / scheduled to publishing / published."""
    now = time.time()
    all_posts = db.list_scheduled_posts()
    due_posts = [
        p for p in all_posts
        if p["status"] in ("queued", "scheduled", "pending") and p["scheduled_time"] <= now
    ]

    dispatched = []
    for post in due_posts:
        pid = post["id"]
        clip = db.get_clip(post["clip_id"])
        if not clip:
            db.update_scheduled_post(pid, status="failed", error="Source clip missing from database")
            continue

        clip_video_path = config.CLIPS_DIR / clip["video_file"]
        if not clip_video_path.exists():
            db.update_scheduled_post(pid, status="failed", error="Rendered video file not found on disk")
            continue

        # Mark as publishing
        db.update_scheduled_post(pid, status="publishing")
        platform = post["platform"].lower()
        acc_id = post["account_id"]
        title = post["title"]
        desc = post.get("description", "")
        tags = post.get("tags", [])
        privacy = post.get("privacy", "public")

        try:
            if platform == "youtube":
                res = accounts.youtube_upload(
                    account_id=acc_id,
                    video_path=clip_video_path,
                    title=title,
                    description=desc,
                    tags=tags,
                    privacy=privacy
                )
                db.update_scheduled_post(pid, status="published", published_url=res["url"], error="")
                dispatched.append({"id": pid, "url": res["url"], "platform": "youtube"})

            elif platform == "instagram":
                res = accounts.instagram_upload(
                    account_id=acc_id,
                    video_path=clip_video_path,
                    caption=f"{title}\n\n{desc}"
                )
                db.update_scheduled_post(pid, status="published", published_url=res["url"], error="")
                dispatched.append({"id": pid, "url": res["url"], "platform": "instagram"})

            elif platform == "tiktok":
                res = accounts.tiktok_upload(
                    account_id=acc_id,
                    video_path=clip_video_path,
                    title=title
                )
                db.update_scheduled_post(pid, status="published", published_url=res["url"], error="")
                dispatched.append({"id": pid, "url": res["url"], "platform": "tiktok"})

            else:
                db.update_scheduled_post(pid, status="failed", error=f"Unsupported platform: {platform}")

        except Exception as e:
            logger.error(f"Posting failed for post {pid} ({platform}): {e}")
            db.update_scheduled_post(pid, status="failed", error=str(e)[:300])

    return dispatched
