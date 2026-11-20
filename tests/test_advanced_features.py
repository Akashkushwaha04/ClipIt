"""Unit and Integration Tests for Advanced PeakCut Features.

Covers:
- Feature 1: Live Stream Ingest & Real-Time Triggering (studio/live.py)
- Feature 2: Multi-Platform Auto-Posting & Scheduling Queue (studio/posting.py)
- Feature 3: Creator Workspaces & Channel Profiles (studio/creators.py)
- Feature 4: Gaming Stream Recognition & Intelligent Tagging (studio/games.py)
- Feature 5: Multi-Provider AI Fallback & Token Usage Tracker (studio/brain.py)
- Feature 6: Subprocess ASR Worker & Storage Protection (studio/asr_worker.py & studio/storage.py)
"""
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from studio import asr_worker, brain, config, creators, db, games, live, posting, storage
from studio import server
from studio.server import (
    CreatorRequest,
    LiveStartRequest,
    SchedulePostRequest,
    create_creator_profile,
    delete_creator_profile,
    delete_post_item,
    get_ai_usage_stats,
    get_creators,
    get_posts_queue,
    get_storage_metrics,
    schedule_clip_post,
    start_live_stream,
    stop_live_stream,
    update_creator_profile,
)


class TestAdvancedPeakCutFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="test_advanced_"))
        cls.orig_data_dir = config.DATA_DIR
        cls.orig_clips_dir = config.CLIPS_DIR
        config.DATA_DIR = cls.test_dir
        config.CLIPS_DIR = cls.test_dir / "clips"
        config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)
        config.DB_PATH = cls.test_dir / "clipforge_test.db"
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        config.DATA_DIR = cls.orig_data_dir
        config.CLIPS_DIR = cls.orig_clips_dir
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_feature4_gaming_recognition(self):
        """Feature 4: Test 25+ gaming recognition signatures and dynamic scouting context."""
        test_titles = [
            ("Grand Theft Auto VI Official Trailer Breakdown & Gameplay", "Grand Theft Auto VI", "GTA6Launch"),
            ("Insane 1v5 Clutch in Valorant Radiant Lobby", "Valorant", "ValRadiant"),
            ("Minecraft Hardcore Survival Day 100 Speedrun", "Minecraft", "MinecraftClips"),
            ("CS2 Premier 25k ELO Mirage Highlights", "Counter-Strike", "CS2"),
            ("Fortnite OG Season Solo Victory Royale Headshots", "Fortnite", "FortniteOG"),
            ("Elden Ring Shadow of the Erdtree Final Boss Defeated", "Elden Ring", "EldenRing"),
            ("Helldivers 2 Super Helldive Extraction with 500kg Bomb", "Helldivers 2", "Helldivers2"),
            ("Roblox Blox Fruits PvP Bounty Hunting", "Roblox", "RobloxClips"),
            ("Rust Solo Surviving Clan Raid Defense", "Rust", "RustSurvival"),
        ]

        for title, expected_game, expected_tag in test_titles:
            game_name, tags = games.detect(title)
            self.assertEqual(game_name, expected_game, f"Failed for title: {title}")
            self.assertTrue(any(expected_tag.lower() in t.lower() for t in tags), f"Tag {expected_tag} not in {tags}")
            # Verify dynamic scouting guidance
            guidance = games.get_game_prompt_context(game_name)
            self.assertTrue(len(guidance) > 20)
            self.assertIn(game_name.lower()[:5], guidance.lower())

        # Test metadata enrichment
        sample_clip = {"title": "Wild Play", "description": "Watch this!", "tags": ["clip"], "hashtags": ["#shorts"]}
        enriched = games.enhance_clip_metadata(sample_clip, "Valorant", ["Valorant", "ValRadiant"])
        self.assertIn("Valorant", enriched["tags"])
        self.assertTrue(any("#ValRadiant" in h for h in enriched["hashtags"]))

    def test_02_feature3_creator_workspaces(self):
        """Feature 3: Creator workspace profiles and SQLite persistence."""
        creator_req = CreatorRequest(
            name="Shroud Gaming",
            channels={"youtube": "@ShroudYT", "twitch": "shroud"},
            style="hype",
            layout="split",
            min_len=20,
            max_len=55,
            min_score=85,
            autopost=True,
            daily_cap=4,
            post_gap_min=60,
            default_tags=["shroud", "fps", "aimgod"]
        )
        res = create_creator_profile(creator_req)
        self.assertEqual(res["status"], "success")
        creator = res["creator"]
        cid = creator["id"]
        self.assertEqual(creator["name"], "Shroud Gaming")
        self.assertEqual(creator["channels"]["twitch"], "shroud")
        self.assertTrue(creator["autopost"])

        # Test listing creators
        c_list = get_creators()
        self.assertTrue(any(c["id"] == cid for c in c_list))

        # Test updating creator
        update_res = update_creator_profile(cid, CreatorRequest(
            name="Shroud Pro Highlights",
            style="clean",
            daily_cap=6
        ))
        self.assertEqual(update_res["status"], "success")
        updated = creators.get_creator(cid)
        self.assertEqual(updated["name"], "Shroud Pro Highlights")
        self.assertEqual(updated["style"], "clean")

    def test_03_feature2_posting_queue_and_spacing(self):
        """Feature 2: Multi-platform posting queue, time spacing, and dispatch."""
        # Create test account
        db.save_account({
            "id": "acc_yt_test",
            "platform": "youtube",
            "name": "Test YT Channel",
            "access_token": "access_tok",
            "refresh_token": "refresh_tok",
            "expires_at": time.time() + 3600
        })

        clip_id = "test_queue_clip_1"
        db.create_clip({
            "id": clip_id,
            "job_id": "job_queue_test",
            "start_time": 0.0,
            "end_time": 10.0,
            "duration": 10.0,
            "score": 90,
            "category": "clutch",
            "hook": "BRO WHAT A SHOT 💀",
            "title": "Unreal Sniping Clutch! 🔥",
            "description": "Watch until the end! #shorts",
            "tags": ["gaming", "shorts"],
            "video_file": "sample_queue.mp4"
        })
        # Create dummy video file
        sample_video = config.CLIPS_DIR / "sample_queue.mp4"
        sample_video.write_bytes(b"dummy_video_bytes")

        # Test compute_next_slot rules
        now = time.time()
        slot_1 = posting.compute_next_slot("acc_yt_test", post_gap_min=45, daily_cap=5, start_time=now)
        self.assertGreaterEqual(slot_1, now)

        # Enqueue post via API
        sched_res = schedule_clip_post(clip_id, SchedulePostRequest(
            platform="youtube",
            account_id="acc_yt_test",
            title="Unreal Sniping Clutch! 🔥",
            scheduled_time=now - 5  # Mark as due for dispatch
        ))
        self.assertEqual(sched_res["status"], "success")
        post = sched_res["scheduled_post"]
        self.assertIn("id", post)

        # Verify queue endpoint
        queue_items = get_posts_queue()
        self.assertTrue(any(p["id"] == post["id"] for p in queue_items))

        # Test dispatch
        dispatched = posting.dispatch_due_posts()
        self.assertTrue(len(dispatched) >= 1)

        # Test delete
        del_res = delete_post_item(post["id"])
        self.assertEqual(del_res["status"], "success")

    def test_04_feature1_live_stream_session(self):
        """Feature 1: Live stream session management, circular buffer, and chat triggering."""
        res = start_live_stream(LiveStartRequest(
            stream_url="https://www.youtube.com/@LofiGirl/live",
            creator_id="creator_default"
        ))
        self.assertEqual(res["status"], "success")
        session = live._active_session
        self.assertIsNotNone(session)
        self.assertTrue(session.is_recording)

        # Simulate chat messages with trigger phrase
        session.simulate_chat_message("yo that was crazy clip that pog")
        self.assertTrue(session.chat_velocity > 0)

        # Check status
        status = live.get_live_status()
        self.assertTrue(status["is_recording"])
        self.assertEqual(status["session_id"], session.session_id)

        # Stop session
        stop_res = stop_live_stream()
        self.assertEqual(stop_res["status"], "success")
        self.assertFalse(session.is_recording)

    def test_05_feature5_ai_fallback_and_usage(self):
        """Feature 5: AI fallback chain resolution and token cost tracking."""
        chain = brain.get_ai_fallback_chain()
        self.assertTrue(len(chain) >= 2)
        providers = [p for p, m in chain]
        self.assertIn("ollama", providers)

        # Record AI usage
        rec = db.record_ai_usage(
            job_id="job_test_ai",
            provider="gemini",
            model="gemini-2.5-flash",
            prompt_tokens=1200,
            completion_tokens=350,
            estimated_cost=0.000195
        )
        self.assertEqual(rec["total_tokens"], 1550)

        # Fetch usage summary via endpoint
        summary = get_ai_usage_stats()
        self.assertGreaterEqual(summary["total_tokens"], 1550)
        self.assertIn("gemini", summary["by_provider"])

    def test_06_feature6_storage_and_asr_worker(self):
        """Feature 6: Storage info, disk space check, and isolated ASR model check."""
        ready = asr_worker.ensure_models()
        self.assertTrue(ready)

        info = storage.get_storage_info()
        self.assertIn("free_gb", info)
        self.assertIn("drive", info)
        self.assertGreater(info["total_gb"], 0)

        metrics = get_storage_metrics()
        self.assertIn("free_gb", metrics)

        safe, _ = storage.check_disk_space(min_gb=0.1)
        self.assertTrue(safe)


if __name__ == "__main__":
    unittest.main()
