"""Creator Workspaces & Channel Profiles (Feature 3).

Provides creator-centric branding presets, channel handles (YouTube, Twitch, Kick),
caption styles, layout preferences, and automated posting policies backed by native SQLite.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from . import db

logger = logging.getLogger("clipforge.creators")

DEFAULTS = {
    "name": "Default Creator",
    "channels": {"youtube": "", "twitch": "", "kick": ""},
    "style": "bounce",
    "layout": "split",
    "min_len": 15,
    "max_len": 60,
    "min_score": 80,
    "autopost": False,
    "daily_cap": 5,
    "post_gap_min": 45,
    "default_tags": ["shorts", "viral", "clutch", "moments"],
}


def create_creator(
    name: str,
    channels: Optional[dict] = None,
    style: str = "bounce",
    layout: str = "split",
    min_len: int = 15,
    max_len: int = 60,
    min_score: int = 80,
    autopost: bool = False,
    daily_cap: int = 5,
    post_gap_min: int = 45,
    default_tags: Optional[list] = None,
    creator_id: Optional[str] = None
) -> dict:
    """Creates a new creator workspace in SQLite."""
    return db.create_creator(
        name=name,
        channels=channels or {},
        style=style,
        layout=layout,
        min_len=min_len,
        max_len=max_len,
        min_score=min_score,
        autopost=autopost,
        daily_cap=daily_cap,
        post_gap_min=post_gap_min,
        default_tags=default_tags or [],
        creator_id=creator_id
    )


def get_creator(creator_id: str) -> Optional[dict]:
    """Retrieves creator profile by ID."""
    return db.get_creator(creator_id)


def list_creators() -> List[dict]:
    """Lists all configured creator profiles."""
    creators = db.list_creators()
    if not creators:
        # Create initial default creator if table is empty
        def_creator = create_creator(
            name=DEFAULTS["name"],
            channels=DEFAULTS["channels"],
            style=DEFAULTS["style"],
            layout=DEFAULTS["layout"],
            min_len=DEFAULTS["min_len"],
            max_len=DEFAULTS["max_len"],
            min_score=DEFAULTS["min_score"],
            autopost=DEFAULTS["autopost"],
            daily_cap=DEFAULTS["daily_cap"],
            post_gap_min=DEFAULTS["post_gap_min"],
            default_tags=DEFAULTS["default_tags"],
            creator_id="creator_default"
        )
        return [def_creator]
    return creators


def update_creator(creator_id: str, **kwargs) -> Optional[dict]:
    """Updates creator settings."""
    return db.update_creator(creator_id, **kwargs)


def delete_creator(creator_id: str):
    """Deletes creator profile."""
    db.delete_creator(creator_id)


def on_job_completed(job_id: str, creator_id: Optional[str] = None) -> List[dict]:
    """Hook executed when a video job completes.

    If creator has `autopost` enabled, automatically schedules clips that meet `min_score`.
    """
    from . import posting

    cid = creator_id or ""
    if not cid:
        job = db.get_job(job_id)
        if job:
            cid = job.get("creator_id") or ""

    if not cid:
        return []

    creator = get_creator(cid)
    if not creator or not creator.get("autopost"):
        return []

    min_score = creator.get("min_score", 80)
    clips = db.list_clips(job_id)
    auto_queued = []

    # Get accounts
    accounts = db.list_accounts()
    if not accounts:
        return []

    # Auto-queue eligible clips
    for clip in clips:
        if clip.get("score", 0) >= min_score:
            for acc in accounts:
                try:
                    p = posting.enqueue_post(
                        clip_id=clip["id"],
                        platform=acc["platform"],
                        account_id=acc["id"],
                        title=clip.get("title", ""),
                        description=clip.get("description", ""),
                        tags=clip.get("tags", []),
                        privacy="public",
                        creator_id=cid
                    )
                    auto_queued.append(p)
                except Exception as e:
                    logger.warning(f"Auto-queue failed for clip {clip['id']}: {e}")

    logger.info(f"Auto-queued {len(auto_queued)} posts for creator {creator.get('name')}")
    return auto_queued
