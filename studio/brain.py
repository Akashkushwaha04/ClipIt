"""AI LLM Layer and Moment Selection Engine ('The Brain').

Orchestrates multi-provider LLM inference (Gemini, Claude, OpenAI, Groq, Ollama)
with automatic ordered fallback chains, computes 3-5 minute sliding transcript windows
with loudness markers, snaps clip boundaries to sentence punctuation, and generates
high-CTR Big Text Hooks in English & Hinglish with game-specific viral intelligence.
"""
import difflib
import json
import logging
import math
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import httpx
import numpy as np

from . import config, db, games, roman
from .transcribe import make_lines, sentence_ends

logger = logging.getLogger("clipforge.brain")

CATEGORIES = {"funny", "clutch", "story", "shock", "fail", "rage", "highlight", "other"}

SYSTEM_PROMPT = """You are an elite short-form video scout & viral producer (YouTube Shorts, TikTok, Instagram Reels).
You are analyzing a timestamped transcript with (LOUD) markers indicating acoustic spikes (laughter, shouts, clutch action).

Your goal: Extract 3 to 8 standalone viral clips (15 to 60 seconds each).

For each clip:
1. `start` & `end`: in seconds from the transcript timestamps. Start at the beginning of the setup sentence. End on the punchline or payoff. Never cut off mid-sentence.
2. `score`: 0-100 virality rating based on humor, tension, surprise, or emotional reaction.
3. `category`: one of ["funny", "clutch", "story", "shock", "fail", "rage", "highlight"].
4. `hook`: 2 to 5 words, ALL CAPS. Punchy, curiosity-inducing hook for the top banner.
   - If Hindi/Urdu dialogue is spoken, use natural conversational Romanized Hinglish (e.g. "YE KYA HO GAYA?! 💀", "ASLI TWIST AAGE HAI", "BRO NE KYA KIYA").
   - Otherwise punchy English (e.g. "WAIT FOR THE END 💀", "HE ACTUALLY DID THIS", "BRO THOUGHT HE WAS SAFE").
5. `title`: High-CTR YouTube Shorts title (< 80 characters) with 1 relevant emoji.
6. `description`: 2-4 engaging sentences explaining the moment + CTA ("Subscribe for more daily shorts!") + 3 to 5 hashtags with #.
7. `tags`: 10 to 15 high-search-volume keywords without #.
8. `highlight_words`: 3 to 6 impactful words spoken in the clip.
9. `reason`: 1 sentence explaining why this moment is viral.

Output STRICTLY valid JSON with no conversational preamble or markdown code blocks:
[
  {
    "start": 12.5,
    "end": 44.0,
    "score": 95,
    "category": "shock",
    "hook": "WAIT FOR THE END 💀",
    "title": "His Reaction Was Completely Priceless! 😱",
    "description": "You won't believe what happened in this match! Watch until the final second. Subscribe for more crazy clips! #gaming #shorts #viral #clutch",
    "tags": ["gaming clips", "funny moments", "clutch play", "viral shorts", "reaction", "epic fail", "highlight", "streamer", "best moments", "tiktok viral"],
    "highlight_words": ["unbelievable", "reaction", "crazy", "clutch"],
    "reason": "Sudden unexpected twist with peak loudness reaction."
  }
]
"""

HINGLISH_KEYWORDS = {
    "bhai", "yaar", "kya", "kyun", "nahi", "accha", "theek", "arrey", "arre",
    "dekh", "dekho", "suno", "kaise", "ye", "yeh", "woh", "hai", "hain",
    "karna", "kar", "baat", "chalo", "asli", "abey", "saala", "kuch", "apna",
    "mujhe", "tum", "hum", "teri", "mera", "ruk", "rukna", "bol", "bata"
}


def detect_is_hinglish(words: List[dict]) -> bool:
    count = 0
    total = len(words)
    if total == 0:
        return False
    for w in words:
        clean = re.sub(r"\W", "", w["w"].lower())
        if clean in HINGLISH_KEYWORDS or roman.has_hindi(w["w"]):
            count += 1
    return (count / total) > 0.06 or count >= 2


# --- Multi-Provider Fallback & Local Ollama Support (Feature 5) ---

PROVIDER_PRICING = {
    "gemini": {"prompt": 0.075 / 1e6, "completion": 0.30 / 1e6},
    "claude": {"prompt": 3.00 / 1e6, "completion": 15.00 / 1e6},
    "anthropic": {"prompt": 3.00 / 1e6, "completion": 15.00 / 1e6},
    "openai": {"prompt": 0.15 / 1e6, "completion": 0.60 / 1e6},
    "groq": {"prompt": 0.05 / 1e6, "completion": 0.08 / 1e6},
    "openrouter": {"prompt": 0.20 / 1e6, "completion": 0.80 / 1e6},
    "ollama": {"prompt": 0.0, "completion": 0.0},
}


def _parse_model_target(raw: str) -> Tuple[str, str]:
    """Extracts (provider, model_name) from string like 'groq/llama-3.3-70b' or 'gemini-2.5-flash'."""
    raw = str(raw or "").strip()
    if "/" in raw:
        parts = raw.split("/", 1)
        return parts[0].lower(), parts[1]
    low = raw.lower()
    if "gemini" in low:
        return "gemini", raw
    if "claude" in low:
        return "claude", raw
    if "gpt" in low:
        return "openai", raw
    if "llama" in low:
        return "groq" if "versatile" in low or "70b" in low else "ollama", raw
    if "mistral" in low or "qwen" in low:
        return "ollama", raw
    return config.AI_PROVIDER, raw


def get_ai_fallback_chain() -> List[Tuple[str, str]]:
    """Builds an ordered list of (provider, model) pairs to attempt."""
    chain_str = (
        os.environ.get("CLIPFORGE_AI_MODELS")
        or os.environ.get("PEAKCUT_AI_MODELS")
        or db.get_setting("ai_models_chain")
        or ""
    ).strip()

    targets: List[Tuple[str, str]] = []
    if chain_str:
        for item in chain_str.split(","):
            item = item.strip()
            if item:
                targets.append(_parse_model_target(item))

    # Add primary configured provider/model
    primary = (config.AI_PROVIDER.lower(), config.AI_MODEL)
    if primary not in targets:
        targets.insert(0, primary)

    # Standard fallback candidates
    fallbacks = [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
        ("ollama", "llama3.2"),
        ("openai", "gpt-4o-mini"),
    ]
    for fb in fallbacks:
        if fb not in targets:
            targets.append(fb)

    return targets


def _query_ollama(model: str, prompt: str, system: str, host: str = "http://localhost:11434") -> Optional[Tuple[str, int, int]]:
    """Direct query to local Ollama instance for 100% offline, zero-cost inference."""
    try:
        url = f"{host.rstrip('/')}/api/chat"
        payload = {
            "model": model or "llama3.2",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "format": "json"
        }
        with httpx.Client(timeout=35.0) as client:
            r = client.post(url, json=payload)
            if r.status_code == 200:
                data = r.json()
                msg = data.get("message", {}).get("content", "")
                p_tok = data.get("prompt_eval_count") or (len(prompt) // 4)
                c_tok = data.get("eval_count") or (len(msg) // 4)
                return msg, int(p_tok), int(c_tok)
    except Exception as e:
        logger.debug(f"Ollama local query failed ({model}): {e}")
    return None


def call_llm(prompt: str, system: str = SYSTEM_PROMPT, job_id: str = "adhoc") -> Optional[str]:
    """Dispatches prompt through ordered fallback chains across multi-provider LLMs.

    If a provider hits 429 rate limits or quota depletion, automatically falls back
    to the next provider without failing the job, and tracks token usage in SQLite.
    """
    chain = get_ai_fallback_chain()
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    for provider, model in chain:
        key = (
            db.get_setting("ai_key")
            or config.AI_KEY
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or ""
        )

        try:
            # 1. Local Ollama (Zero Cost, Offline)
            if provider == "ollama":
                res = _query_ollama(model, prompt, system, host=ollama_host)
                if res:
                    msg, p_tok, c_tok = res
                    db.record_ai_usage(job_id, "ollama", model, p_tok, c_tok, estimated_cost=0.0)
                    return msg
                continue

            # Cloud providers require an API key
            if not key and provider != "ollama":
                continue

            # 2. Google Gemini
            if provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                payload = {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}
                }
                with httpx.Client(timeout=45.0) as client:
                    r = client.post(url, json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            text = candidates[0]["content"]["parts"][0]["text"]
                            usage = data.get("usageMetadata", {})
                            p_tok = usage.get("promptTokenCount") or (len(prompt) // 4)
                            c_tok = usage.get("candidatesTokenCount") or (len(text) // 4)
                            pricing = PROVIDER_PRICING["gemini"]
                            cost = (p_tok * pricing["prompt"]) + (c_tok * pricing["completion"])
                            db.record_ai_usage(job_id, "gemini", model, p_tok, c_tok, estimated_cost=cost)
                            return text
                    elif r.status_code in (429, 403, 503):
                        logger.warning(f"Gemini {r.status_code} limit hit for {model}. Falling back to next provider...")
                        continue

            # 3. OpenAI, Groq, OpenRouter
            elif provider in ("openai", "groq", "openrouter"):
                base = "https://api.openai.com/v1" if provider == "openai" else (
                    "https://api.groq.com/openai/v1" if provider == "groq" else "https://openrouter.ai/api/v1"
                )
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"} if provider == "openai" else None
                }
                with httpx.Client(timeout=45.0) as client:
                    r = client.post(f"{base}/chat/completions", headers=headers, json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        text = data["choices"][0]["message"]["content"]
                        usage = data.get("usage", {})
                        p_tok = usage.get("prompt_tokens") or (len(prompt) // 4)
                        c_tok = usage.get("completion_tokens") or (len(text) // 4)
                        pricing = PROVIDER_PRICING.get(provider, PROVIDER_PRICING["openai"])
                        cost = (p_tok * pricing["prompt"]) + (c_tok * pricing["completion"])
                        db.record_ai_usage(job_id, provider, model, p_tok, c_tok, estimated_cost=cost)
                        return text
                    elif r.status_code in (429, 403, 503):
                        logger.warning(f"{provider} {r.status_code} limit hit for {model}. Falling back...")
                        continue

            # 4. Anthropic Claude
            elif provider in ("claude", "anthropic"):
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": model or "claude-3-5-sonnet-20241022",
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 4096,
                    "temperature": 0.4
                }
                with httpx.Client(timeout=45.0) as client:
                    r = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
                    if r.status_code == 200:
                        data = r.json()
                        text = data["content"][0]["text"]
                        usage = data.get("usage", {})
                        p_tok = usage.get("input_tokens") or (len(prompt) // 4)
                        c_tok = usage.get("output_tokens") or (len(text) // 4)
                        pricing = PROVIDER_PRICING["claude"]
                        cost = (p_tok * pricing["prompt"]) + (c_tok * pricing["completion"])
                        db.record_ai_usage(job_id, "claude", model, p_tok, c_tok, estimated_cost=cost)
                        return text
                    elif r.status_code in (429, 403, 503):
                        logger.warning(f"Claude {r.status_code} limit hit for {model}. Falling back...")
                        continue

        except Exception as e:
            logger.debug(f"LLM attempt failed ({provider}/{model}): {e}. Checking next fallback...")
            continue

    return None


def _snap(clip: dict, lines: List[dict], words: List[dict], min_len: float, max_len: float, duration: float) -> Tuple[float, float]:
    """Boundary snapping: Automatically adjusts clip start to the beginning of a line
    and snaps the end to sentence-terminating punctuation (. ? !) without mid-word cutoffs.
    """
    s = float(clip.get("start", 0))
    e = float(clip.get("end", s + 30.0))
    if s < 0 or e <= s:
        return 0.0, min(duration, 30.0)

    # Snap start to closest line start within 4 seconds
    starts = [l["s"] for l in lines if abs(l["s"] - s) <= 4.0]
    if starts:
        s = min(starts, key=lambda x: abs(x - s))

    lo = s + min_len
    hi = min(s + max_len, duration)

    stops = [x for x in sentence_ends(words) if lo <= x <= hi]
    if stops:
        after = [x for x in stops if x >= e - 1.0]
        e = after[0] if after and (after[0] - e <= 10.0) else min(stops, key=lambda x: abs(x - e))
    else:
        ends = [w["e"] for w in words if lo <= w["e"] <= hi and abs(w["e"] - e) <= 4.0]
        if ends:
            e = min(ends, key=lambda x: abs(x - e))

    e = max(e, s + min_len)
    e = min(e, s + max_len, duration)

    # Brief tail pad (0.2s) without entering next sentence
    nxt = next((w["s"] for w in words if w["s"] > e - 0.01), None)
    tail = 0.25 if nxt is None else min(0.25, max(0.05, nxt - e - 0.05))

    return round(max(0.0, s - 0.1), 2), round(min(duration, e + tail), 2)


def _heuristic_moment_picker(words: List[dict], loud_z: np.ndarray, duration: float, n_clips: int = 5, is_hinglish: bool = False) -> List[dict]:
    """Offline heuristic engine: identifies peaks in loudness z-scores and speech activity."""
    if len(loud_z) == 0:
        step = max(20.0, duration / max(1, n_clips))
        return [
            {
                "start": round(i * step, 2),
                "end": round(min(duration, (i + 1) * step), 2),
                "score": 85 - i * 3,
                "category": "highlight",
                "hook": "YE DEKHO KYA HUA! 💀" if is_hinglish else "WAIT TILL THE END 💀",
                "title": "Bhai Yeh Kya Kar Diya! 😱" if is_hinglish else f"Unbelievable Moment #{i+1} 😱",
                "description": "Crazy moment from the stream! Subscribe for more daily clips! #shorts #viral #gaming",
                "tags": ["shorts", "viral", "clutch", "moments", "gaming"],
                "hashtags": ["shorts", "viral", "gaming"],
                "highlight_words": ["crazy", "moment"],
                "reason": "Segment with continuous audio activity.",
            }
            for i in range(min(n_clips, max(1, int(duration // 20))))
        ]

    # Find peaks in 1-second z-score chunks
    peaks = []
    for sec_idx, z in enumerate(loud_z):
        if z >= 1.0:
            peaks.append((sec_idx, float(z)))

    peaks.sort(key=lambda p: -p[1])

    min_len = 15.0
    max_len = 60.0
    clips = []
    chosen_intervals = []

    lines = make_lines(words, loud_z)

    for sec, zscore in peaks:
        target_start = max(0.0, sec - 10.0)
        target_end = min(duration, sec + 20.0)

        snap_s, snap_e = _snap({"start": target_start, "end": target_end}, lines, words, min_len, max_len, duration)
        if snap_e - snap_s < min_len:
            continue

        overlap = False
        for cs, ce in chosen_intervals:
            if max(snap_s, cs) < min(snap_e, ce):
                overlap = True
                break
        if overlap:
            continue

        chosen_intervals.append((snap_s, snap_e))
        clip_words = [w for w in words if snap_s <= w["s"] <= snap_e]
        score = min(98, int(75 + min(20, zscore * 6)))

        idx = len(clips) + 1
        if is_hinglish:
            hinglish_hooks = ["YE KYA HO GAYA?! 💀", "ASLI TWIST TOH AAGE HAI", "BHAI KYA CLUTCH KIYA", "END TAK RUKNA 💀", "BRO NE KYA KIYA"]
            hinglish_titles = ["Bhai Yeh Kisine Nahi Socha Tha! 😱", "Asli Twist Toh Ab Shuru Hua! 🔥", "Bhai Ne Poora Match Palat Diya! 💀", "Khatarnak Game Moment! ⚡"]
            hook = hinglish_hooks[(idx - 1) % len(hinglish_hooks)]
            title = hinglish_titles[(idx - 1) % len(hinglish_titles)]
        else:
            english_hooks = ["WAIT TILL THE END 💀", "BRO THOUGHT HE WAS SAFE", "WORST MISTAKE EVER", "HE COULD NOT BELIEVE IT", "WAIT FOR IT 💀"]
            english_titles = ["Nobody Expected This To Happen! 😱", "The Craziest Moment of The Match! 🔥", "He Thought He Had Won! 💀", "Absolute Insane Reaction! ⚡"]
            hook = english_hooks[(idx - 1) % len(english_hooks)]
            title = english_titles[(idx - 1) % len(english_titles)]

        desc = (
            f"Watch what happens at the turning point of this match! Full reaction inside. "
            f"Subscribe for more daily shorts and viral clips! #shorts #viral #clutch #moments"
        )
        tags = [
            "shorts", "viral clips", "funny moments", "clutch", "trending", "streamer highlights",
            "tiktok video", "best shorts", "epic moments", "gaming highlight"
        ]
        category = "clutch" if score > 85 else ("funny" if idx % 2 == 0 else "shock")

        clips.append({
            "start": snap_s,
            "end": snap_e,
            "score": score,
            "category": category,
            "hook": hook,
            "title": title,
            "description": desc,
            "tags": tags,
            "hashtags": ["shorts", "viral", "clutch", "moments"],
            "highlight_words": [w["w"] for w in clip_words[:4]],
            "reason": "Loudness energy peak with high audience engagement.",
        })
        if len(clips) >= n_clips:
            break

    return sorted(clips, key=lambda c: c["start"])


def extract_clips(
    words: List[dict],
    loud_z: np.ndarray,
    duration: float,
    title: str = "",
    uploader: str = "",
    game: str = "",
    job_id: str = "adhoc"
) -> List[dict]:
    """Finds 3-8 viral clips using LLM sliding windows with gaming recognition,
    token cost tracking, and boundary snapping.
    """
    is_hinglish = detect_is_hinglish(words)
    lines = make_lines(words, loud_z)

    # Detect game from title, uploader, or explicit game param
    detected_game, detected_tags = games.detect(title, game, uploader)
    game_guidance = games.get_game_prompt_context(detected_game)

    # Format transcript lines with timestamps and (LOUD) markers
    formatted_transcript = "\n".join(
        f"[{l['s']:.1f}] {'(LOUD) ' if l['loud'] else ''}{roman.to_roman(l['text'])}"
        for l in lines
    )

    llm_prompt = f"""Video Title: {title or 'Stream / Video'}
Channel / Creator: {uploader or 'Creator'}
Game Context: {detected_game or 'General / Variety'} ({game_guidance})
Total Duration: {duration:.1f} seconds
Language Tone: {'Conversational Hinglish / Hindi' if is_hinglish else 'English'}

Timestamped Transcript:
{formatted_transcript[:12000]}
"""

    raw_response = call_llm(llm_prompt, job_id=job_id)
    proposals = []

    if raw_response:
        try:
            cleaned = re.sub(r"^```json\s*", "", raw_response.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "clips" in parsed:
                parsed = parsed["clips"]
            if isinstance(parsed, list):
                proposals = parsed
        except Exception as e:
            logger.warning(f"Could not parse LLM output: {e}. Raw was: {raw_response[:200]}")

    if not proposals:
        logger.info("Using heuristic peak loudness moment picker")
        base_clips = _heuristic_moment_picker(words, loud_z, duration, n_clips=5, is_hinglish=is_hinglish)
        return [games.enhance_clip_metadata(c, detected_game, detected_tags) for c in base_clips]

    # Clean & snap LLM proposals
    min_len = 15.0
    max_len = 60.0
    final_clips = []

    for p in sorted(proposals, key=lambda x: -float(x.get("score", 70))):
        snap_s, snap_e = _snap(p, lines, words, min_len, max_len, duration)
        if snap_e - snap_s < min_len:
            continue
        # Deduplicate overlapping clips
        if any(min(snap_e, c["end"]) - max(snap_s, c["start"]) > 0.3 * (snap_e - snap_s) for c in final_clips):
            continue

        hook_text = roman.to_roman(str(p.get("hook", "WAIT FOR IT"))).upper()
        clean_title = roman.to_roman(str(p.get("title", "Insane Moment! 🔥")))[:80]
        desc = roman.to_roman(str(p.get("description", "Watch until the end! Subscribe for more. #shorts")))
        tags = p.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)]
        tags = [re.sub(r"[#\W]", " ", str(t)).strip() for t in tags if str(t).strip()][:15]

        clip_dict = {
            "start": snap_s,
            "end": snap_e,
            "score": max(50, min(100, int(float(p.get("score", 85))))),
            "category": str(p.get("category", "highlight")).lower(),
            "hook": hook_text,
            "title": clean_title,
            "description": desc,
            "tags": tags,
            "hashtags": p.get("hashtags", ["shorts", "viral", "clutch"]),
            "highlight_words": p.get("highlight_words", []),
            "reason": str(p.get("reason", "Engaging action sequence")),
        }
        # Enrich with gaming context tags
        clip_dict = games.enhance_clip_metadata(clip_dict, detected_game, detected_tags)
        final_clips.append(clip_dict)
        if len(final_clips) >= 8:
            break

    if not final_clips:
        base_clips = _heuristic_moment_picker(words, loud_z, duration, n_clips=4, is_hinglish=is_hinglish)
        return [games.enhance_clip_metadata(c, detected_game, detected_tags) for c in base_clips]

    return sorted(final_clips, key=lambda c: c["start"])


def regenerate_seo(clip: dict, clip_words: List[dict], context_title: str = "", job_id: str = "adhoc") -> dict:
    """Analyzes full conversation context, jokes, emotional turning points, and climaxes
    to generate high-CTR Title, Description, 12-15 Tags, and Hashtags in English or Hinglish.
    """
    is_hinglish = detect_is_hinglish(clip_words)
    transcript_text = " ".join(w["w"] for w in clip_words)

    # Detect game if present in context
    detected_game, detected_tags = games.detect(context_title, clip.get("title", ""))

    prompt = f"""You are an elite short-form video strategist analyzing a viral moment.
Analyze the full dialogue context, comedic timing, emotional tension, and climax payoff:

Spoken Transcript: "{transcript_text}"
Video Context: "{context_title}"
Gaming Context: "{detected_game or 'General'}"
Language Detected: {'Hindi / Urdu (Output strictly conversational Hinglish in Roman alphabet)' if is_hinglish else 'English (Output strictly standard punchy English)'}

Generate a viral, high-CTR YouTube Shorts metadata package following this exact JSON schema:
{{
  "hook": "2 to 5 words ALL CAPS for top banner ({'Hinglish Romanized e.g. YE KYA HO GAYA?! 💀' if is_hinglish else 'English e.g. WAIT FOR THE END 💀'})",
  "title": "High-curiosity YouTube title under 80 characters with 1 relevant emoji",
  "description": "2 to 4 engaging sentences capturing the turning point + CTA 'Subscribe for more daily clips!' + 3-5 hashtags",
  "tags": ["12 to 15 high-ranking search keywords without # symbols"],
  "hashtags": ["5 single-word hashtags with #"]
}}
"""
    raw = call_llm(prompt, job_id=job_id)
    if raw:
        try:
            cleaned = re.sub(r"^```json\s*", "", raw.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE)
            data = json.loads(cleaned)

            hook_raw = str(data.get("hook", clip.get("hook", "WAIT FOR IT")))
            title_raw = str(data.get("title", clip.get("title", "Insane Moment! 🔥")))
            desc_raw = str(data.get("description", clip.get("description", "")))

            hook = roman.to_roman(hook_raw).upper()[:50]
            title = roman.to_roman(title_raw)[:80]
            description = roman.to_roman(desc_raw)

            raw_tags = data.get("tags", clip.get("tags", []))
            if not isinstance(raw_tags, list):
                raw_tags = [str(raw_tags)]
            tags = [re.sub(r"[#\W]+", " ", str(t)).strip() for t in raw_tags if re.sub(r"[#\W]+", " ", str(t)).strip()]
            tags = tags[:15]
            if len(tags) < 12:
                defaults = ["shorts", "viral", "reaction", "highlights", "gaming", "trending", "tiktok", "reels", "best moments", "epic"]
                for d in defaults:
                    if d not in tags:
                        tags.append(d)
                    if len(tags) >= 14:
                        break

            raw_hashtags = data.get("hashtags", ["#shorts", "#viral", "#clutch", "#trending", "#reels"])
            if not isinstance(raw_hashtags, list):
                raw_hashtags = ["#shorts", "#viral"]
            hashtags = [("#" + re.sub(r"\W", "", str(h))) for h in raw_hashtags if re.sub(r"\W", "", str(h))][:5]

            res = {
                "hook": hook,
                "title": title,
                "description": description,
                "tags": tags,
                "hashtags": hashtags,
                "is_hinglish": is_hinglish
            }
            if detected_game:
                res = games.enhance_clip_metadata(res, detected_game, detected_tags)
                res["hashtags"] = res["hashtags"][:5]
            return res
        except Exception as e:
            logger.warning(f"Failed to parse regenerated SEO: {e}")

    # Fallback refinement adhering to output schema
    if is_hinglish:
        res = {
            "hook": "YE KYA HO GAYA?! 💀",
            "title": "Asli Twist Toh Ab Shuru Hua! 😱"[:78],
            "description": "Bhai ne jo kiya kisine socha nahi tha! Watch till the very end for the crazy reaction. Subscribe for more daily clips! #shorts #viral #reaction #hinglish #gaming",
            "tags": [
                "shorts", "viral shorts", "funny moments", "clutch", "trending", "streamer reaction",
                "epic play", "hindi gaming", "best shorts", "tiktok viral", "reels", "crazy twist", "ytshorts"
            ],
            "hashtags": ["#shorts", "#viral", "#clutch", "#trending", "#reaction"],
            "is_hinglish": True
        }
    else:
        res = {
            "hook": "WAIT FOR THE END 💀",
            "title": "The Craziest Moment Nobody Expected! 😱"[:78],
            "description": "You won't believe how this match turned around at the last second! Full reaction inside. Subscribe for more daily clips! #shorts #viral #clutch #gaming #epic",
            "tags": [
                "shorts", "viral clips", "funny moments", "clutch play", "trending", "streamer highlights",
                "tiktok video", "best shorts", "epic reaction", "gaming clips", "highlight", "unbelievable", "ytshorts"
            ],
            "hashtags": ["#shorts", "#viral", "#clutch", "#trending", "#reaction"],
            "is_hinglish": False
        }
    if detected_game:
        res = games.enhance_clip_metadata(res, detected_game, detected_tags)
        res["hashtags"] = res["hashtags"][:5]
    return res


def research_channel_keywords(topic: str, niche: str = "") -> dict:
    """Channel Keyword Research (Feature 8): Generates high-CTR keywords and viral video ideas."""
    prompt = f"""You are a YouTube Shorts & Viral Content Algorithm Specialist.
Channel Niche/Topic: "{topic}" (Category: "{niche or 'General'}")

Generate a comprehensive viral SEO strategy in JSON format:
{{
  "keywords": ["15-20 high search volume keywords without #"],
  "channel_tags": ["8-12 core channel tags for settings"],
  "content_ideas": [
    {{"title": "Punchy video hook/title < 75 chars with emoji", "format": "15-30s Short", "angle": "Curiosity gap angle"}}
  ]
}}
"""
    raw = call_llm(prompt)
    if raw:
        try:
            cleaned = re.sub(r"^```json\s*", "", raw.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE)
            parsed = json.loads(cleaned)
            kw = parsed.get("keywords") or parsed.get("target_keywords") or []
            tags = parsed.get("channel_tags") or parsed.get("trending_tags") or []
            ideas = parsed.get("content_ideas") or parsed.get("viral_angles") or []
            formatted_ideas = []
            for idea in ideas:
                if isinstance(idea, dict):
                    formatted_ideas.append({
                        "title": idea.get("title", ""),
                        "format": idea.get("format", "15–30s Short"),
                        "angle": idea.get("angle", ""),
                        "emotion": idea.get("emotion") or idea.get("format") or "Viral",
                        "hook": idea.get("hook") or idea.get("angle") or idea.get("title", "")
                    })
            return {
                "keywords": kw,
                "target_keywords": kw,
                "channel_tags": tags,
                "trending_tags": tags,
                "content_ideas": formatted_ideas,
                "viral_angles": formatted_ideas
            }
        except Exception as e:
            logger.warning(f"Failed to parse keyword research: {e}")

    # Fallback recommendations
    clean_topic = topic.strip() or "Gaming Highlights"
    keywords = [
        f"{clean_topic} shorts", f"best {clean_topic} moments", f"{clean_topic} funny clips",
        f"viral {clean_topic}", f"{clean_topic} reaction", f"{clean_topic} 2026",
        "gaming shorts", "trending clips", "tiktok viral", "shorts feed", "clutch plays"
    ]
    tags = [
        clean_topic, f"{clean_topic} clips", "shorts", "gaming", "viral", "highlights"
    ]
    ideas = [
        {"title": f"He Really Thought He Could Win This! 💀", "format": "15–30s Short", "angle": "Unexpected twist/fail", "emotion": "Shock", "hook": "HE REALLY THOUGHT HE WON 💀"},
        {"title": f"The 1 in a Million {clean_topic} Play! 😱", "format": "30–45s Short", "angle": "Peak skill & hype", "emotion": "Hype", "hook": "1 IN A MILLION PLAY 🔥"},
        {"title": f"Nobody Believed This Actually Happened! 🔥", "format": "20–30s Short", "angle": "Instant shock value", "emotion": "Curiosity", "hook": "WAIT FOR THE END 💀"}
    ]
    return {
        "keywords": keywords,
        "target_keywords": keywords,
        "channel_tags": tags,
        "trending_tags": tags,
        "content_ideas": ideas,
        "viral_angles": ideas
    }
