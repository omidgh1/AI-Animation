"""
character_manager.py — Character Creator, Loader & Series Tracker
==================================================================
Manage reusable characters across multiple videos in a series.

THREE THINGS THIS MODULE DOES:

1. CHARACTER CREATOR
   Describe your character in plain English → Claude generates the full
   character JSON with visual description, personality, voice style,
   colour palette, and Flux image prompt anchor.

   Usage:
       python character_manager.py create

2. CHARACTER LOADER
   Load a saved character by ID and inject it into the pipeline
   (story_generator + scene_refiner) so every image shows the
   same character consistently.

3. SERIES TRACKER
   Every time a video is made with a character, the episode is logged
   to characters/<id>_series.json with title, slug, date, and episode number.

FOLDER STRUCTURE:
    D:\\AI-Animation\\
    └── characters\\
        ├── leo.json              ← character definition
        ├── leo_series.json       ← episode log for Leo
        ├── bella.json
        └── bella_series.json

USAGE IN run_pipeline.py / test.py:
    CHARACTER_ID    = "leo"           # loads characters/leo.json
    SUPPORTING_CHARACTERS = ["bella"] # optional — also locks in Bella's look
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

CHARACTERS_DIR = Path("characters")
CHARACTERS_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
#  CHARACTER MODEL  (plain dict — no Pydantic, stays JSON-serialisable)
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "id",                    # URL-safe slug, e.g. "leo"
    "name",                  # Display name, e.g. "Leo"
    "species",               # e.g. "lion cub", "teddy bear", "bunny"
    "visual_description",    # Full paragraph for Stage 1 main_character field
    "flux_anchor",           # Short 20-40 word Flux image anchor (consistent look)
    "personality",           # Tone and behaviour for story generation
    "voice_style",           # ElevenLabs tone hint: warm, energetic, soft, etc.
    "color_palette",         # List of 3 hex codes matching the character
    "series_name",           # e.g. "Leo's World Adventures"
    "episode_count",         # Auto-incremented each video
    "created_at",            # ISO timestamp
]


# ─────────────────────────────────────────────────────────────────────────────
#  CREATOR — Claude generates the full character JSON
# ─────────────────────────────────────────────────────────────────────────────

CREATOR_SYSTEM_PROMPT = dedent("""
    You are a children's character designer specialising in cute animated characters
    for YouTube Kids videos (ages 3-9). Your characters are used across an automated
    AI video pipeline where visual consistency is critical — every episode must show
    the SAME character with the SAME look.

    When given a character description, you produce a complete character definition
    JSON that will be embedded verbatim into image generation prompts (Flux/Stable
    Diffusion) and story generation prompts (Claude).

    DESIGN PRINCIPLES:
    - Pixar/Disney style: round faces, big expressive eyes, soft shapes
    - Simple colour palette (2-3 dominant colours max) so Flux stays consistent
    - Distinctive feature: one unique visual detail that makes them recognisable
      even in a tiny thumbnail (e.g. red scarf, star on forehead, mismatched socks)
    - Age-appropriate: cute, safe, friendly, no sharp features or dark tones

    OUTPUT FORMAT: Return ONLY valid JSON, no markdown, no explanation.
    Start with { and end with }.
""").strip()


def _creator_prompt(description: str, series_name: str) -> str:
    return dedent(f"""
        Create a complete character definition for this kids YouTube series character:

        USER DESCRIPTION:
        {description}

        SERIES NAME: {series_name}

        Generate the following JSON exactly:
        {{
          "name": "<character display name>",
          "species": "<animal/creature type>",
          "visual_description": "<full 60-80 word paragraph describing the character for a story writer. Include: species, size, fur/skin colour, eye colour and size, distinctive features, clothing/accessories, personality shown through appearance. Written as: 'NAME is a [description]...'>",
          "flux_anchor": "<20-35 word Flux image anchor. CRITICAL: this is appended to EVERY scene prompt to lock in the character's look. Format: 'NAME: [distinctive visual features], [clothing], [colour], cute chibi Pixar style, consistent character design'>",
          "personality": "<2-3 sentences describing personality, fears, goals, and how they react to problems. Used by Claude to write the story narration>",
          "voice_style": "<one of: warm_and_gentle | energetic_and_bubbly | soft_and_shy | brave_and_bold | silly_and_funny>",
          "color_palette": ["<dominant hex>", "<secondary hex>", "<accent hex>"],
          "series_name": "{series_name}",
          "tagline": "<one fun sentence that could be a series tagline>",
          "catchphrase": "<short catchphrase the character says, in quotes, e.g. 'Adventure awaits!'>",
          "typical_settings": ["<3 typical settings for stories with this character>"],
          "story_themes": ["<5 good story themes that fit this character>"]
        }}
    """).strip()


def create_character(description: str, series_name: str) -> dict:
    """
    Use Claude to generate a full character definition from a plain-English description.
    Returns the character dict (also saved to characters/<id>.json).
    """
    import anthropic
    import re

    if not config.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    print(f"\n{'='*60}")
    print(f"  Character Creator")
    print(f"{'='*60}")
    print(f"  Description  : {description[:80]}...")
    print(f"  Series       : {series_name}")
    print(f"  Calling Claude...", end="", flush=True)

    t = time.time()
    response = client.messages.create(
        model=config.STORY_MODEL,
        max_tokens=1500,
        temperature=0.9,
        system=CREATOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _creator_prompt(description, series_name)}],
    )
    elapsed = time.time() - t
    print(f" done in {elapsed:.1f}s")

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]

    data = json.loads(raw.strip())

    # Build the character ID from the name
    char_id = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")
    data["id"]            = char_id
    data["episode_count"] = 0
    data["created_at"]    = datetime.now(timezone.utc).isoformat()

    # Save
    path = CHARACTERS_DIR / f"{char_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  ✅  Character created: {data['name']}")
    print(f"  ID         : {char_id}")
    print(f"  File       : {path}")
    print(f"  Flux anchor: {data['flux_anchor']}")
    print(f"  Palette    : {data['color_palette']}")
    print(f"  Themes     : {', '.join(data.get('story_themes', [])[:3])}")
    print(f"  Catchphrase: {data.get('catchphrase', '')}")
    print(f"\n  Add to run_pipeline.py or test.py:")
    print(f"    CHARACTER_ID = \"{char_id}\"")
    print(f"{'='*60}\n")

    return data


# ─────────────────────────────────────────────────────────────────────────────
#  LOADER — load a saved character by ID
# ─────────────────────────────────────────────────────────────────────────────

def load_character(character_id: str) -> dict:
    """Load a character definition from characters/<id>.json."""
    path = CHARACTERS_DIR / f"{character_id}.json"
    if not path.exists():
        available = list_characters()
        raise FileNotFoundError(
            f"Character '{character_id}' not found at {path}\n"
            f"Available characters: {available if available else '(none yet)'}\n"
            f"Run: python character_manager.py create"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def list_characters() -> list[str]:
    """Return list of all saved character IDs."""
    return [p.stem for p in CHARACTERS_DIR.glob("*.json") if not p.stem.endswith("_series")]


def load_supporting(character_ids: list[str]) -> list[dict]:
    """Load multiple supporting characters by ID list."""
    return [load_character(cid) for cid in character_ids if cid]


# ─────────────────────────────────────────────────────────────────────────────
#  SERIES TRACKER
# ─────────────────────────────────────────────────────────────────────────────

def log_episode(
    character_id: str,
    title: str,
    slug: str,
    topic: str,
    youtube_url: str = "",
) -> dict:
    """
    Log a completed episode to characters/<id>_series.json.
    Auto-increments episode_count in the character file.
    Returns the episode dict.
    """
    # Load and increment character file
    char_path = CHARACTERS_DIR / f"{character_id}.json"
    char = json.loads(char_path.read_text(encoding="utf-8"))
    char["episode_count"] = char.get("episode_count", 0) + 1
    episode_num = char["episode_count"]
    char_path.write_text(json.dumps(char, indent=2, ensure_ascii=False), encoding="utf-8")

    # Build episode entry
    episode = {
        "episode":      episode_num,
        "title":        title,
        "slug":         slug,
        "topic":        topic,
        "youtube_url":  youtube_url,
        "date":         datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }

    # Load or create series log
    series_path = CHARACTERS_DIR / f"{character_id}_series.json"
    if series_path.exists():
        series = json.loads(series_path.read_text(encoding="utf-8"))
    else:
        series = {
            "character_id":  character_id,
            "character_name": char["name"],
            "series_name":   char.get("series_name", f"{char['name']}'s Adventures"),
            "episodes":      [],
        }

    series["episodes"].append(episode)
    series["total_episodes"] = len(series["episodes"])
    series["last_updated"] = datetime.now(timezone.utc).isoformat()

    series_path.write_text(json.dumps(series, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  📺  Episode {episode_num} logged: '{title}'")
    print(f"      Series file: {series_path}")
    return episode


def print_series(character_id: str):
    """Print a formatted episode list for a character's series."""
    series_path = CHARACTERS_DIR / f"{character_id}_series.json"
    if not series_path.exists():
        print(f"  No series log found for '{character_id}'")
        return

    series = json.loads(series_path.read_text(encoding="utf-8"))
    print(f"\n{'='*60}")
    print(f"  📺  {series['series_name']}")
    print(f"  Character   : {series['character_name']}")
    print(f"  Total eps   : {series.get('total_episodes', 0)}")
    print(f"{'─'*60}")
    for ep in series.get("episodes", []):
        url_part = f"  {ep['youtube_url']}" if ep.get("youtube_url") else ""
        print(f"  Ep {ep['episode']:03d}  [{ep['date']}]  {ep['title']}{url_part}")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT BUILDER — inject character into Stage 1 and Stage 2 prompts
# ─────────────────────────────────────────────────────────────────────────────

def build_character_block(
    main_character: dict,
    supporting: list[dict] | None = None,
) -> str:
    """
    Build the character instruction block that gets injected into
    Stage 1's system prompt and Stage 2's image prompt instructions.

    This locks the character appearance so Claude cannot invent a new look.
    """
    lines = [
        "═" * 50,
        "CHARACTER LOCK — DO NOT CHANGE THESE DESCRIPTIONS",
        "═" * 50,
        "",
        f"MAIN CHARACTER — {main_character['name'].upper()}:",
        main_character["visual_description"],
        "",
        f"FLUX IMAGE ANCHOR (copy verbatim into every image prompt):",
        main_character["flux_anchor"],
        "",
        f"PERSONALITY:",
        main_character.get("personality", ""),
        "",
        f"CATCHPHRASE: {main_character.get('catchphrase', '')}",
        "",
    ]

    if supporting:
        lines.append("SUPPORTING CHARACTERS:")
        for char in supporting:
            lines += [
                f"",
                f"  {char['name'].upper()}:",
                f"  Visual: {char['visual_description']}",
                f"  Flux anchor: {char['flux_anchor']}",
            ]
        lines.append("")

    lines += [
        "RULES:",
        "- Use the EXACT visual descriptions above — never invent new looks",
        "- Keep the character design consistent across ALL scenes",
        "- The flux_anchor text MUST appear in every scene image_prompt",
        "- Supporting characters appear only in relevant scenes, not all",
        "═" * 50,
    ]

    return "\n".join(lines)


def build_main_character_string(main_character: dict) -> str:
    """
    Build the main_character string for the VideoScript model.
    This replaces whatever Claude would invent.
    """
    return main_character["visual_description"]


def build_topic_with_character(
    topic: str,
    main_character: dict,
    supporting: list[dict] | None = None,
    episode_num: int | None = None,
) -> str:
    """
    Augment the user's topic string with character series context
    for Stage 1's user prompt.
    """
    parts = [f'Topic: "{topic}"']

    series = main_character.get("series_name", f"{main_character['name']}'s Adventures")
    ep_str = f" (Episode {episode_num})" if episode_num else ""
    parts.append(f'Series: "{series}"{ep_str}')
    parts.append(f'Main character: {main_character["name"]} — {main_character["visual_description"]}')
    parts.append(f'Character themes: {", ".join(main_character.get("story_themes", [])[:3])}')

    if supporting:
        sup_names = ", ".join(c["name"] for c in supporting)
        parts.append(f'Supporting characters available: {sup_names}')
        for char in supporting:
            parts.append(f'  {char["name"]}: {char["visual_description"][:100]}...')

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI — python character_manager.py create / list / show <id>
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Kids Video — Character Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
            Examples:
              python character_manager.py create
              python character_manager.py list
              python character_manager.py show leo
              python character_manager.py series leo
        """)
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("create",  help="Create a new character using Claude")
    sub.add_parser("list",    help="List all saved characters")
    show_p = sub.add_parser("show",   help="Show full character definition")
    show_p.add_argument("id", help="Character ID")
    series_p = sub.add_parser("series", help="Show episode list for a character")
    series_p.add_argument("id", help="Character ID")

    args = parser.parse_args()

    if args.command == "create":
        print("\n  ── Character Creator ─────────────────────────────────")
        print("  Describe your character in plain English.")
        print("  The more detail the better. Examples:")
        print("    'A small lion cub with golden fur and big amber eyes,")
        print("     wearing a tiny red backpack, always nervous but brave'")
        print("  ─────────────────────────────────────────────────────\n")
        description  = input("  Character description: ").strip()
        series_name  = input("  Series name (e.g. 'Leo's World Adventures'): ").strip()
        if not description or not series_name:
            print("  Both fields required.")
            sys.exit(1)
        create_character(description, series_name)

    elif args.command == "list":
        chars = list_characters()
        if not chars:
            print("\n  No characters yet. Run: python character_manager.py create")
        else:
            print(f"\n  Saved characters ({len(chars)}):")
            for cid in chars:
                c = load_character(cid)
                print(f"    {cid:20s}  {c['name']:15s}  {c['species']:20s}  "
                      f"Ep: {c.get('episode_count', 0):3d}  "
                      f"Series: {c.get('series_name', '')}")

    elif args.command == "show":
        c = load_character(args.id)
        print(f"\n{'='*60}")
        print(f"  {c['name']} ({c['id']})")
        print(f"{'='*60}")
        for key, val in c.items():
            if key in ("created_at", "id"):
                continue
            if isinstance(val, list):
                print(f"  {key:25s}: {', '.join(str(v) for v in val)}")
            else:
                print(f"  {key:25s}: {str(val)[:70]}")
        print(f"{'='*60}")

    elif args.command == "series":
        print_series(args.id)

    else:
        parser.print_help()