"""What game is this?

A gaming stream or video identifies which game it is in its title, tags, or stream metadata.
Knowing the game changes two things:
1. The AI is instructed on what kind of viral moment to scout (e.g., a 1vX clutch in Valorant vs an MLG bucket in Minecraft).
2. Every generated clip automatically carries trending, high-traffic game tags and hashtags.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# name, words that mean it, tags to put on the post
GAMES: list[tuple[str, list[str], list[str]]] = [
    ("Grand Theft Auto VI", ["grand theft auto vi", "grand theft auto 6", "gta vi", "gta 6", "gta6"],
     ["GTA6", "GTA6Game", "ViceCity", "RockstarGames", "GTA6Launch"]),
    ("Grand Theft Auto V", ["grand theft auto v", "grand theft auto 5", "gta online", "gta v", "gta 5", "gta5", "gtav", "gta rp"],
     ["GTA5", "GTAOnline", "RockstarGames", "GTA5RP", "GTARP"]),
    ("Grand Theft Auto IV", ["grand theft auto iv", "gta 4", "gta4"], ["GTA4", "RockstarGames"]),
    ("Fortnite", ["fortnite"], ["Fortnite", "FortniteOG", "BattleRoyale", "FortniteClips"]),
    ("Minecraft", ["minecraft", "mc hardcore", "mc speedrun"], ["Minecraft", "MinecraftGame", "MinecraftClips", "MinecraftHardcore"]),
    ("Valorant", ["valorant", "val"], ["Valorant", "ValRadiant", "ValorantClips", "RiotGames"]),
    ("League of Legends", ["league of legends", "league of legend", "lol"], ["LeagueOfLegends", "LoL", "RiotGames"]),
    ("Counter-Strike", ["counter-strike", "counter strike", "cs2", "csgo"], ["CS2", "CounterStrike", "Esports", "CSClips"]),
    ("Elden Ring", ["elden ring", "shadow of the erdtree"], ["EldenRing", "SoulsLike", "FromSoftware", "Erdtree"]),
    ("Palworld", ["palworld"], ["Palworld", "Survival"]),
    ("Call of Duty", ["call of duty", "warzone", "cod", "black ops", "bo6"], ["CallOfDuty", "Warzone", "COD", "MW3", "BO6"]),
    ("Helldivers 2", ["helldivers 2", "helldivers2"], ["Helldivers2", "StarshipTroopers", "CoOp", "SuperEarth"]),
    ("Cyberpunk 2077", ["cyberpunk 2077", "cyberpunk", "phantom liberty"], ["Cyberpunk2077", "NightCity"]),
    ("Starfield", ["starfield"], ["Starfield", "Bethesda"]),
    ("Black Myth Wukong", ["black myth", "wukong", "black myth wukong"], ["BlackMythWukong", "ActionRPG"]),
    ("Marvel Rivals", ["marvel rivals"], ["MarvelRivals", "Heroes"]),
    ("Overwatch 2", ["overwatch 2", "overwatch", "ow2"], ["Overwatch2", "OW2", "Blizzard"]),
    ("ARK", ["ark: survival", "ark survival", "ark ascended"], ["ARK", "Survival"]),
    ("Dead by Daylight", ["dead by daylight", "dbd"], ["DeadByDaylight", "DBD"]),
    ("Rocket League", ["rocket league"], ["RocketLeague", "CarSports"]),
    ("Apex Legends", ["apex legends", "apex"], ["ApexLegends", "EApex"]),
    ("PUBG", ["pubg", "playerunknown"], ["PUBG", "BattleRoyale"]),
    ("Grand Theft Auto: San Andreas", ["grand theft auto san andreas", "gta sa"], ["GTA", "SanAndreas"]),
    ("Roblox", ["roblox"], ["Roblox", "RobloxClips", "RobloxMoments", "BloxFruits"]),
    ("Rust", ["rust", "rust game"], ["Rust", "RustSurvival", "RustClips"]),
    ("Dota 2", ["dota 2", "dota"], ["Dota2", "MOBA", "Esports"]),
    ("Team Fortress 2", ["team fortress 2", "tf2"], ["TF2", "TeamFortress2"]),
    ("Baldur's Gate 3", ["baldur's gate 3", "baldurs gate 3", "bg3"], ["BaldursGate3", "BG3", "RPG"]),
    ("Monster Hunter", ["monster hunter", "mh wilds", "monster hunter wilds"], ["MonsterHunter", "MHWilds"]),
    ("Destiny 2", ["destiny 2"], ["Destiny2", "Bungie"]),
    ("World of Warcraft", ["world of warcraft", "wow"], ["WorldOfWarcraft", "WoW"]),
    ("Rainbow Six Siege", ["rainbow six siege", "rainbow 6", "r6 siege", "r6s"], ["R6Siege", "RainbowSixSiege"]),
]

GENERIC = ["Gaming", "Gameplay", "GamingClips", "StreamHighlights"]

# Longest word first so specific titles match first
_ALIASES: list[tuple[str, str, list[str]]] = sorted(
    ((alias, name, tags) for name, aliases, tags in GAMES for alias in aliases),
    key=lambda a: -len(a[0]),
)

_WORD = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _WORD.sub(" ", str(text or "").lower()).strip()


def detect(*texts) -> tuple[str | None, list[str]]:
    """The game named in the text, and the tags that belong on its posts.

    Returns (None, []) when no known game is named.
    """
    hay = _norm(" ".join(str(t or "") for t in texts))
    if not hay:
        return None, []
    for alias, name, tags in _ALIASES:
        if re.search(r"(?:^| )" + re.escape(_norm(alias)) + r"(?: |$)", hay):
            return name, list(tags)
    return None, []


def name_of(game: str | None) -> str:
    """The game's proper name, from a name, a tag or a spelling of its own."""
    if not game:
        return ""
    g = _norm(game)
    for name, aliases, _tags in GAMES:
        if g == _norm(name) or g in {_norm(a) for a in aliases}:
            return name
    return str(game)[:40]


def tags_of(game: str | None) -> list[str]:
    """The tags for a game, whether it is named in full, short, or by one of its tags."""
    if not game:
        return []
    g = _norm(game)
    for name, aliases, tags in GAMES:
        if g == _norm(name) or g in {_norm(a) for a in aliases} or g in {_norm(t) for t in tags}:
            return list(tags)
    return [re.sub(r"\W", "", str(game))[:30]] if re.sub(r"\W", "", str(game)) else []


def get_game_prompt_context(game_name: str | None) -> str:
    """Returns dynamic LLM scouting guidance tailored to the detected game."""
    if not game_name:
        return "Scout for clutch victories, hilarious fails, high-octane kills, intense screams, and team comedy moments."

    g = game_name.lower()
    if "grand theft auto" in g or "gta" in g:
        return (f"Detected Game: {game_name}. Focus on insane high-speed car chases, 5-star police shootouts, "
                "stunt fails, unexpected physics glitches, high-stakes RP moments, and funny character interactions.")
    if "valorant" in g:
        return (f"Detected Game: {game_name}. Focus on round-winning 1vX aces, clutch defuses, insane Operator flicks, "
                "funny voice comms, toxic whiffs, and high-energy streamer reactions.")
    if "minecraft" in g:
        return (f"Detected Game: {game_name}. Focus on clutch MLG water buckets, hardcore near-death moments, creeper jumpscares, "
                "speedrun records, hilarious trap pranks, and shocking Nether/End deaths.")
    if "fortnite" in g:
        return (f"Detected Game: {game_name}. Focus on fast 1v1 build battles, 200-pump headshots, trickshot snipes, "
                "hilarious vehicle chaos, and hype Victory Royales.")
    if "counter-strike" in g or "cs2" in g:
        return (f"Detected Game: {game_name}. Focus on 1vX clutch rounds, deagle one-taps, ninja defuses, flashbang whiffs, "
                "and intense shoutcaster / streamer screams.")
    if "elden ring" in g:
        return (f"Detected Game: {game_name}. Focus on boss battle final hits, shocking one-shot deaths, rage-quit moments, "
                "unexpected traps, and triumphant celebrations.")
    if "helldivers" in g:
        return (f"Detected Game: {game_name}. Focus on orbital strike friendly fire, massive bug swarm extractions, "
                "clutch 500kg bomb drops, and heroic last-second escapes.")
    if "call of duty" in g or "warzone" in g:
        return (f"Detected Game: {game_name}. Focus on gulag clutches, sniper feeds, squad wipes, hot-mic death reactions, "
                "and high-kill game highlights.")
    if "roblox" in g:
        return (f"Detected Game: {game_name}. Focus on unexpected funny glitches, dramatic roleplay scenes, obby rage fails, "
                "and viral creator moments.")

    return (f"Detected Game: {game_name}. Prioritize title-specific clutch highlights, hilarious fails, "
            "intense competitive turnaround plays, and high-energy audience reactions.")


def enhance_clip_metadata(clip: dict, game_name: Optional[str] = None, game_tags: Optional[List[str]] = None) -> dict:
    """Enriches clip title, tags, and hashtags with high-traffic gaming tags."""
    if not game_name and not game_tags:
        return clip

    gname = game_name or ""
    gtags = game_tags or tags_of(gname)

    existing_tags = clip.get("tags") or []
    if isinstance(existing_tags, str):
        try:
            existing_tags = json.loads(existing_tags)
        except Exception:
            existing_tags = [t.strip() for t in existing_tags.split(",") if t.strip()]

    # Merge tags without duplicates
    merged_tags = list(existing_tags)
    for t in gtags:
        if t not in merged_tags and len(merged_tags) < 18:
            merged_tags.append(t)
    clip["tags"] = merged_tags

    # Merge hashtags
    existing_hashtags = clip.get("hashtags") or []
    if isinstance(existing_hashtags, str):
        try:
            existing_hashtags = json.loads(existing_hashtags)
        except Exception:
            existing_hashtags = [h.strip() for h in existing_hashtags.split() if h.strip()]

    merged_hashtags = list(existing_hashtags)
    for t in gtags[:3]:
        ht = f"#{t}" if not t.startswith("#") else t
        if ht not in merged_hashtags and len(merged_hashtags) < 7:
            merged_hashtags.append(ht)
    clip["hashtags"] = merged_hashtags

    # Append to description if not already present
    desc = clip.get("description", "")
    for ht in merged_hashtags:
        if ht not in desc:
            desc = f"{desc} {ht}".strip()
    clip["description"] = desc

    return clip
