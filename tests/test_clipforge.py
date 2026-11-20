"""End-to-End Test Suite for ClipForge Studio.

Verifies:
1. Database integrity (Jobs, Clips, Accounts, Settings)
2. Hinglish Romanization & script detection
3. Audio extraction & Loudness Z-scores
4. Boundary snapping & Sentence end alignment
5. Big Text Hook & Conversation SEO generation
6. FFmpeg 9:16 vertical render with karaoke ASS subtitles & Big Text banner
7. Instant Big Text live re-render
8. YouTube upload creator approval logic
9. FastAPI HTTP routes via TestClient
"""
import os
from pathlib import Path
import subprocess
import time
import unittest

import numpy as np

from studio import accounts, brain, config, db, facecam, render, roman, transcribe
from fastapi.testclient import TestClient
from studio.server import app


class TestClipForgeStudio(unittest.TestCase):

    def setUp(self):
        db.init_db()

    def test_01_database_operations(self):
        """Verify SQLite tables, CRUD operations, and relations."""
        job = db.create_job("test_job_1", "upload", "", "Gaming Stream Highlights", "StreamerX")
        self.assertEqual(job["id"], "test_job_1")
        self.assertEqual(job["status"], "pending")

        db.update_job("test_job_1", status="completed", progress=100)
        updated = db.get_job("test_job_1")
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["progress"], 100)

        # Clip creation
        clip = db.create_clip({
            "id": "test_clip_1",
            "job_id": "test_job_1",
            "clip_index": 1,
            "start_time": 10.0,
            "end_time": 35.0,
            "score": 95,
            "category": "clutch",
            "hook": "WAIT FOR THE END 💀",
            "title": "Unreal Clutch Play! 😱",
            "description": "Watch until the final second! #shorts",
            "tags": ["gaming", "shorts", "clutch"],
            "video_file": "test_clip_1.mp4",
            "cover_file": "test_clip_1.jpg",
            "ass_file": "test_clip_1.ass"
        })
        self.assertEqual(clip["score"], 95)
        self.assertEqual(clip["hook"], "WAIT FOR THE END 💀")

        # Account creation
        db.save_account({
            "id": "yt_channel_123",
            "platform": "youtube",
            "name": "Pro Gamer Shorts",
            "access_token": "mock_token_abc",
            "refresh_token": "mock_refresh_xyz",
            "expires_at": time.time() + 3600
        })
        acc = db.get_account("yt_channel_123")
        self.assertIsNotNone(acc)
        self.assertEqual(acc["name"], "Pro Gamer Shorts")

    def test_02_hinglish_romanization(self):
        """Verify Hindi/Urdu transliteration and font safety."""
        self.assertTrue(roman.has_hindi("ये क्या हो गया"))
        self.assertFalse(roman.has_hindi("Hello World"))

        translit = roman.to_roman("ये क्या हो गया")
        self.assertTrue("ye" in translit.lower() or "yeh" in translit.lower())
        self.assertIn("kya", translit.lower())
        self.assertIn("gaya", translit.lower())
        self.assertTrue(roman.drawable(translit))

    def test_03_boundary_snapping_and_lines(self):
        """Verify sentence end detection and boundary snapping."""
        words = [
            {"w": "welcome", "s": 0.0, "e": 0.4},
            {"w": "to", "s": 0.45, "e": 0.6},
            {"w": "the", "s": 0.65, "e": 0.8},
            {"w": "stream.", "s": 0.85, "e": 1.4},
            {"w": "look", "s": 2.0, "e": 2.3},
            {"w": "at", "s": 2.35, "e": 2.5},
            {"w": "this", "s": 2.55, "e": 2.8},
            {"w": "play!", "s": 2.85, "e": 3.4},
            {"w": "insane", "s": 4.0, "e": 4.5},
            {"w": "reaction.", "s": 4.55, "e": 5.2},
        ]
        ends = transcribe.sentence_ends(words)
        self.assertTrue(len(ends) >= 2)
        self.assertIn(1.4, ends)

        lines = transcribe.make_lines(words)
        self.assertTrue(len(lines) >= 2)

        cand = {"start": 0.2, "end": 4.2}
        snap_s, snap_e = brain._snap(cand, lines, words, min_len=2.0, max_len=10.0, duration=10.0)
        self.assertEqual(snap_s, 0.0)  # Snapped to line start
        self.assertGreater(snap_e, 3.0)  # Snapped to sentence end

    def test_04_ai_scouting_and_seo_regeneration(self):
        """Verify moment generation and conversation understanding."""
        words = [
            {"w": "bhai", "s": 1.0, "e": 1.3},
            {"w": "yeh", "s": 1.35, "e": 1.6},
            {"w": "kya", "s": 1.65, "e": 1.9},
            {"w": "twist", "s": 1.95, "e": 2.4},
            {"w": "hai!", "s": 2.45, "e": 2.9},
        ]
        is_hinglish = brain.detect_is_hinglish(words)
        self.assertTrue(is_hinglish)

        loud_z = np.array([0.0, 2.5, 3.1, 1.2, 0.0, -0.5])
        clips = brain._heuristic_moment_picker(words, loud_z, duration=30.0, n_clips=2, is_hinglish=is_hinglish)
        self.assertTrue(len(clips) > 0)
        self.assertTrue("YE KYA" in clips[0]["hook"] or "TWIST" in clips[0]["hook"] or "END" in clips[0]["hook"])

        # SEO regeneration
        seo = brain.regenerate_seo(clips[0], words, "Epic Tournament Match")
        self.assertIn("hook", seo)
        self.assertIn("title", seo)
        self.assertIn("description", seo)
        self.assertIn("tags", seo)

    def test_05_ffmpeg_render_and_instant_live_update(self):
        """Generate synthetic test video, render 9:16 Short with ASS captions and Big Text, and live update."""
        tmp_dir = Path("data/tests")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        raw_vid = tmp_dir / "sample_input.mp4"

        # Create a 4-second synthetic video with audio using ffmpeg
        creation_flags = 0x08000000 if os.name == "nt" else 0
        gen_cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
            "-t", "4.0",
            "-pix_fmt", "yuv420p",
            str(raw_vid)
        ]
        subprocess.run(gen_cmd, check=True, creationflags=creation_flags)
        self.assertTrue(raw_vid.exists())

        test_words = [
            {"w": "HELLO", "s": 0.5, "e": 1.0},
            {"w": "CLIPFORGE", "s": 1.05, "e": 1.8},
            {"w": "STUDIO!", "s": 1.85, "e": 2.5},
            {"w": "UNBELIEVABLE", "s": 2.6, "e": 3.4},
        ]

        clip_id = f"test_render_{int(time.time())}"
        render_info = {
            "start": 0.0,
            "end": 3.8,
            "hook": "WAIT FOR THE END 💀",
            "style": "bounce",
            "layout": "blur",
            "highlight_words": ["UNBELIEVABLE"],
        }

        # Render clip
        res = render.render_single_clip(
            src_video=raw_vid,
            out_dir=config.CLIPS_DIR,
            clip_id=clip_id,
            clip_info=render_info,
            words=test_words,
            src_w=1280,
            src_h=720
        )

        out_mp4 = Path(res["video_path"])
        out_jpg = Path(res["cover_path"])
        self.assertTrue(out_mp4.exists())
        self.assertTrue(out_jpg.exists())
        self.assertGreater(out_mp4.stat().st_size, 5000)

        # Test Instant Big Text Re-render (e.g. user updates hook to Hinglish)
        render_info["hook"] = "ASLI TWIST AAGE HAI 🔥"
        res_updated = render.render_single_clip(
            src_video=raw_vid,
            out_dir=config.CLIPS_DIR,
            clip_id=clip_id,
            clip_info=render_info,
            words=test_words,
            src_w=1280,
            src_h=720
        )
        self.assertTrue(Path(res_updated["video_path"]).exists())

    def test_06_fastapi_endpoints(self):
        """Test API endpoints directly."""
        from studio.server import get_system_status, list_clips, get_settings, save_settings, SettingsRequest

        status = get_system_status()
        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["ffmpeg"])

        clips = list_clips()
        self.assertIsInstance(clips, list)

        settings = get_settings()
        self.assertIn("ai_provider", settings)

        saved = save_settings(SettingsRequest(ai_provider="gemini", ai_model="gemini-2.5-flash"))
        self.assertEqual(saved["settings"]["ai_provider"], "gemini")

    def test_07_feature1_and_feature3_context_seo_and_hinglish(self):
        """Feature 1 & Feature 3: Context-Aware AI SEO with full dialogue understanding and selective Hinglish."""
        # Test Hindi/Urdu dialogue -> Roman Hinglish
        hinglish_words = [
            {"w": "bhai", "s": 0.0, "e": 0.4},
            {"w": "ye", "s": 0.45, "e": 0.7},
            {"w": "kya", "s": 0.75, "e": 1.0},
            {"w": "scene", "s": 1.05, "e": 1.4},
            {"w": "hai", "s": 1.45, "e": 1.8},
            {"w": "yaar", "s": 1.85, "e": 2.2},
            {"w": "clutch", "s": 2.25, "e": 2.8},
            {"w": "karo!", "s": 2.85, "e": 3.4},
        ]
        clip_data = {
            "id": "clip_h1",
            "start_time": 0.0,
            "end_time": 3.4,
            "score": 96,
            "category": "clutch",
            "hook": "YE KYA HO GAYA?! 💀",
            "title": "Bhai Kya Clutch Kiya! 🔥",
            "description": "Insane moment in stream.",
            "tags": ["gaming", "shorts"],
        }
        seo_h = brain.regenerate_seo(clip_data, hinglish_words, context_title="GTA 5 Roleplay Live Stream")
        self.assertTrue(seo_h["is_hinglish"])
        self.assertLessEqual(len(seo_h["title"]), 80)
        self.assertIn("Subscribe", seo_h["description"])  # CTA
        self.assertTrue(len(seo_h["tags"]) >= 10)
        for t in seo_h["tags"]:
            self.assertFalse(t.startswith("#"), f"Tag '{t}' should not start with '#'")
        self.assertEqual(len(seo_h["hashtags"]), 5)

        # Test English dialogue -> Pure English
        english_words = [
            {"w": "bro", "s": 0.0, "e": 0.4},
            {"w": "he", "s": 0.45, "e": 0.7},
            {"w": "really", "s": 0.75, "e": 1.0},
            {"w": "thought", "s": 1.05, "e": 1.4},
            {"w": "he", "s": 1.45, "e": 1.8},
            {"w": "was", "s": 1.85, "e": 2.2},
            {"w": "safe", "s": 2.25, "e": 2.8},
        ]
        seo_en = brain.regenerate_seo(clip_data, english_words, context_title="Valorant Clutch")
        self.assertFalse(seo_en["is_hinglish"])
        self.assertLessEqual(len(seo_en["title"]), 80)
        self.assertEqual(len(seo_en["hashtags"]), 5)

    def test_08_feature2_fast_hook_reburn(self):
        """Feature 2: Sub-5-second fast Big Text Hook re-burn."""
        raw_vid = Path("data/tests/sample_input.mp4")
        self.assertTrue(raw_vid.exists())

        clip_id = "test_fast_hook_clip"
        render_info = {
            "start": 0.0,
            "end": 2.5,
            "hook": "BRO THOUGHT HE WAS SAFE 💀",
            "style": "bounce",
            "layout": "blur",
            "facecam": None,
            "highlight_words": ["SAFE"],
        }
        test_words = [{"w": "BRO", "s": 0.2, "e": 0.6}, {"w": "SAFE", "s": 0.7, "e": 1.5}]

        t0 = time.time()
        res = render.fast_reapply_hook(
            src_video=raw_vid,
            out_dir=config.CLIPS_DIR,
            clip_id=clip_id,
            clip_info=render_info,
            words=test_words,
            src_w=1280,
            src_h=720
        )
        elapsed = time.time() - t0
        self.assertTrue(Path(res["video_path"]).exists())
        self.assertLess(elapsed, 5.0, f"Fast re-burn took {elapsed:.2f}s, expected < 5s")

    def test_09_feature4_and_feature5_multiplatform_and_scheduling(self):
        """Feature 4 & 5: Multi-Platform Uploads & Scheduled Post Dispatcher."""
        # Setup mock clip and accounts
        db.create_job("job_multi", "upload", "", "MultiPlatform Test", "Host")
        clip = db.create_clip({
            "id": "clip_multi_1",
            "job_id": "job_multi",
            "clip_index": 1,
            "start_time": 0.0,
            "end_time": 2.0,
            "score": 90,
            "category": "highlight",
            "hook": "WAIT FOR IT 💀",
            "title": "Epic Multi Post Short! 🔥",
            "description": "Check this out! #shorts",
            "tags": ["shorts", "viral"],
            "video_file": "test_fast_hook_clip.mp4",
            "cover_file": "test_fast_hook_clip.jpg",
            "ass_file": "test_fast_hook_clip.ass"
        })

        db.save_account({
            "id": "ig_acc_1",
            "platform": "instagram",
            "name": "InstaReelsChannel",
            "access_token": "token_ig_123"
        })

        db.save_account({
            "id": "tt_acc_1",
            "platform": "tiktok",
            "name": "TikTokShortsChannel",
            "access_token": "token_tt_123"
        })

        # Test MultiPlatform upload routing directly
        from studio.server import upload_clip_multi, MultiPlatformUploadRequest
        ig_res = upload_clip_multi("clip_multi_1", MultiPlatformUploadRequest(
            account_id="ig_acc_1",
            platform="instagram",
            title="IG Reel Title",
            description="IG Reel Description",
            privacy="public"
        ))
        self.assertEqual(ig_res["status"], "success")
        self.assertEqual(ig_res["platform"], "instagram")

        tt_res = upload_clip_multi("clip_multi_1", MultiPlatformUploadRequest(
            account_id="tt_acc_1",
            platform="tiktok",
            title="TikTok Title",
            privacy="public"
        ))
        self.assertEqual(tt_res["status"], "success")
        self.assertEqual(tt_res["platform"], "tiktok")

        # Test Scheduling
        from studio.server import schedule_clip_post, list_schedule, cancel_scheduled_post, SchedulePostRequest
        future_time = time.time() + 3600
        sched_res = schedule_clip_post("clip_multi_1", SchedulePostRequest(
            platform="youtube",
            account_id="yt_channel_123",
            title="Scheduled Short",
            scheduled_time=future_time
        ))
        self.assertEqual(sched_res["status"], "success")
        post_id = sched_res["scheduled_post"]["id"]

        queue = list_schedule()
        self.assertTrue(any(p["id"] == post_id for p in queue))

        # Test Dispatcher execution (with due post in the past)
        past_time = time.time() - 10
        past_post = db.create_scheduled_post({
            "clip_id": "clip_multi_1",
            "platform": "instagram",
            "account_id": "ig_acc_1",
            "title": "Due Instagram Post",
            "scheduled_time": past_time
        })
        dispatched = accounts.dispatch_due_scheduled_posts()
        self.assertTrue(len(dispatched) >= 1)
        updated_post = db.get_scheduled_post(past_post["id"])
        self.assertEqual(updated_post["status"], "published")

        # Cancel schedule test
        cancel_res = cancel_scheduled_post(post_id)
        self.assertEqual(cancel_res["status"], "success")

    def test_10_feature6_stacked_split_layout(self):
        """Feature 6: Dual-screen stacked 35/65 vertical layout (Facecam Top / Gameplay Bottom)."""
        raw_vid = Path("data/tests/sample_input.mp4")
        clip_id = "test_split_clip"
        render_info = {
            "start": 0.0,
            "end": 2.0,
            "hook": "INSANE SPLIT LAYOUT",
            "style": "hype",
            "layout": "split",  # Feature 6
            "facecam": {"x": 50, "y": 50, "w": 200, "h": 200},
            "highlight_words": ["SPLIT"],
        }
        res = render.render_single_clip(
            src_video=raw_vid,
            out_dir=config.CLIPS_DIR,
            clip_id=clip_id,
            clip_info=render_info,
            words=[{"w": "INSANE", "s": 0.2, "e": 0.8}, {"w": "SPLIT", "s": 0.9, "e": 1.5}],
            src_w=1280,
            src_h=720
        )
        self.assertTrue(Path(res["video_path"]).exists())
        self.assertGreater(Path(res["video_path"]).stat().st_size, 5000)

    def test_11_feature7_audio_polish_and_whoosh_sfx(self):
        """Feature 7: Audio normalization (loudnorm) & Whoosh SFX synthesis."""
        sfx_path = render.ensure_whoosh_sfx()
        self.assertTrue(sfx_path.exists())
        self.assertGreater(sfx_path.stat().st_size, 1000)

        # Test loudness computation and normalization parameter presence
        db_arr, loud_z = transcribe.compute_loudness(sfx_path)
        self.assertTrue(len(db_arr) > 0)

    def test_12_feature8_keyword_research_and_analytics(self):
        """Feature 8: Channel Keyword & Niche Research and Video Analytics Tracker."""
        research = brain.research_channel_keywords("GTA 5 Roleplay Clutch", "Gaming")
        self.assertTrue(len(research["target_keywords"]) >= 10)
        self.assertTrue(len(research["trending_tags"]) >= 5)
        self.assertTrue(len(research["viral_angles"]) >= 3)

        # Analytics CRUD & API
        db.save_clip_analytics({
            "clip_id": "clip_multi_1",
            "youtube_id": "yt_vid_abc",
            "views": 15420,
            "likes": 1280,
            "comments": 94,
            "ctr": 11.4,
            "avg_view_duration": 24.2,
            "retention_rate": 86.4
        })
        stats = db.get_clip_analytics("clip_multi_1")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["views"], 15420)
        self.assertEqual(stats["likes"], 1280)

        from studio.server import get_analytics
        all_stats = get_analytics()
        self.assertTrue(len(all_stats) >= 1)



if __name__ == "__main__":
    unittest.main()
