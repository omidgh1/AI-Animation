"""
test.py — AI Kids Video Generator — Stage-by-Stage Test Runner
===============================================================
Run individual pipeline stages one at a time for testing and debugging.

STAGE ORDER (always run in this sequence):
    Stage 1  → Story generation          (Claude)
    Stage 2  → Scene refinement          (Claude art director)
    Stage 3  → Image generation          (Fal.ai Flux)
    Stage 4  → Voice narration           (ElevenLabs)
    Stage 5  → Background music          (Bensound)
    Stage 6  → Video render              (FFmpeg) ← was Stage 8
    Stage 7  → SRT subtitles             (free, script-based) ← was Stage 7
    Stage 8  → Thumbnail generation      (Fal.ai Flux + Pillow) ← was Stage 9
    Stage 9  → Metadata optimisation     (Claude SEO) ← was Stage 10
    Stage 10 → YouTube upload            (YouTube Data API v3) ← was Stage 11

HOW TO USE:
    1. Set TEST_STAGE below (1 through 10)
    2. Set TEST_TOPIC for a fresh story, OR set LOAD_EXISTING_SLUG to reuse one
    3. Run: python test.py
    4. After Stage 1, copy the printed slug into LOAD_EXISTING_SLUG
       so all following stages reuse the same story (saves API cost)

IMPORTANT — Stage 6 must run BEFORE Stage 7:
    Stage 6 produces render_manifest.json with exact per-scene durations.
    Stage 7 reads that file for frame-accurate subtitle timing.
    Running Stage 7 first gives a less accurate but still usable result.

VIDEO FORMAT:
    Set VIDEO_FORMAT = "short" for 60-second Shorts (12 scenes × 5s)
    Set VIDEO_FORMAT = "long"  for 8-15 min YouTube (60 scenes × 10s)
    All stages handle both formats automatically.
"""

import json
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  ✏️  EDIT THESE — everything you need to configure
# ─────────────────────────────────────────────────────────────────────────────

# ── SUBJECT / NICHE ──────────────────────────────────────────────────────────
# Controls which prompts are used. Must match a folder name in prompts/.
#   "kids"    → default kids animated stories  (prompts/*.txt)
#   "facts"   → surprising facts for adults    (prompts/facts/*.txt)
#
# To add a new niche (e.g. "finance"):
#   1. Create folder: prompts/finance/
#   2. Copy + edit any .txt files from prompts/facts/ as a starting point
#   3. Change SUBJECT = "finance" here and run
SUBJECT = "facts"

# Which stage to run (1–10)
TEST_STAGE = 8

# Your story idea — used when LOAD_EXISTING_SLUG is None
TEST_TOPIC    = "octopuses have three hearts and blue blood"
TEST_CATEGORY = None        # None = Claude auto-selects
                            # kids:  "animal_adventure" | "friendship_and_emotions" | "magic_and_fantasy" | "learning_and_educational" | "bedtime_and_calming"
                            # facts: "science" | "history" | "nature" | "psychology" | "technology" | "space" | "animals" | "general"

# After Stage 1 runs, paste the slug it prints here (e.g. "brave-little-dragon")
# This reuses the saved script for all later stages — saves API calls and cost
LOAD_EXISTING_SLUG = "octopuses-have-three-hearts-and-blue-blood" # e.g. "timmys-big-ship-adventure"

# ── CHARACTER SERIES ───────────────────────────────────────────────────────────
# USE_CHARACTER = False  →  no character system at all (facts, finance, history, etc.)
#                           Claude invents visuals freely per scene, no locked design
# USE_CHARACTER = True   →  enables the character pipeline below
#                           (kids series, branded mascots, recurring characters)
USE_CHARACTER = False

CHARACTER_ID             = None    # e.g. "spark" | None = Claude invents a new character
SUPPORTING_CHARACTER_IDS = []         # e.g. ["bella"] | [] = no supporting chars
LOG_EPISODE              = True       # Log this video to the character's series file
AUTO_SAVE_CHARACTER      = True       # True = auto-save new character after Stage 1
                                      #        (only applies when CHARACTER_ID = None)

# Video format — applies to Stages 1-3
VIDEO_FORMAT      = "short"     # "short" = 60s Shorts / "long" = 8-15 min YouTube
VIDEO_ORIENTATION = "vertical"  # "vertical" (9:16) / "horizontal" (16:9) / "square" (1:1)

# Short video settings
SHORT_NUM_SCENES     = 12   # 12 × 5s ≈ 60s
SHORT_SCENE_DURATION = 5

# Long video settings
LONG_NUM_SCENES      = 60   # 60 × 10s ≈ 10 min
LONG_SCENE_DURATION  = 10

# Stage 4 (voice): use fast/cheap Flash model for testing, multilingual for final
USE_FAST_VOICE = False

# Stage 6 (render): burn subtitles directly into video
BURN_SUBTITLES = True

# Stage 7 (subtitles): also generate ASS file for burn-in
GENERATE_ASS = True

# Stage 10 (upload): privacy setting
YOUTUBE_PRIVACY   = "private"   # "private" to review before going public
YOUTUBE_THUMBNAIL = True
YOUTUBE_SUBTITLES = True

# Misc
PRINT_JSON   = False    # True = print raw JSON output from Stages 1-2
SAVE_OUTPUT  = True     # False = dry-run (no files written)

# ─────────────────────────────────────────────────────────────────────────────
#  END OF CONFIG — no need to edit below this line
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config


# ─────────────────────────────────────────────────────────────────────────────
#  RUNTIME CONFIG — apply video format and orientation before any stage runs
# ─────────────────────────────────────────────────────────────────────────────

def _load_characters() -> tuple[dict | None, list[dict]]:
    """
    Resolve CHARACTER_ID into loaded character dicts.

    USE_CHARACTER = False → returns (None, []) immediately — no character pipeline
    CHARACTER_ID = None   → returns (None, []) — Claude invents the character freely
    CHARACTER_ID = "leo"  → loads characters/leo.json
    CHARACTER_ID = "new"  → interactive: shows existing characters, then either
                            picks one or runs Claude character creator
    """
    if not USE_CHARACTER:
        return None, []

    if not CHARACTER_ID:
        return None, []

    from pipeline.character_manager import (
        load_character, load_supporting, list_characters,
        create_character, print_series,
    )

    char_id = CHARACTER_ID

    if char_id == "new":
        # Interactive flow — show what exists, then ask
        existing = list_characters()
        print()
        print("  ── Character Selection ──────────────────────────────")
        if existing:
            print(f"  Existing characters ({len(existing)}):")
            for cid in existing:
                try:
                    c = load_character(cid)
                    print(f"    [{cid}]  {c['name']:15s}  "
                          f"Ep:{c.get('episode_count',0):3d}  "
                          f"{c.get('series_name','')}")
                except Exception:
                    print(f"    [{cid}]  (error reading)")
        else:
            print("  No characters saved yet.")
        print()
        choice = input(
            "  Type an existing ID to use it, or press Enter to create a new one: "
        ).strip().lower()

        if choice and choice in existing:
            char_id = choice
        else:
            # Create new character interactively
            print()
            description = input("  Describe your character: ").strip()
            series_name = input("  Series name: ").strip()
            if not description or not series_name:
                print("  Both fields required — aborting character creation.")
                return None, []
            char_data = create_character(description, series_name)
            char_id   = char_data["id"]

    # Load the resolved character
    main = load_character(char_id)
    supporting = load_supporting(SUPPORTING_CHARACTER_IDS) if SUPPORTING_CHARACTER_IDS else []
    return main, supporting


def _auto_save_character(script) -> str | None:
    """
    Auto-save the character Claude invented in Stage 1 to characters/<id>.json.
    Called after Stage 1 when CHARACTER_ID is None and AUTO_SAVE_CHARACTER is True.
    Uses the main_character description from the script and derives a series name
    from the character's name, then calls create_character() to generate and save
    the full character card (flux anchor, personality, palette, etc.).
    Returns the new character ID, or None if saving failed.
    """
    from pipeline.character_manager import create_character

    description = script.main_character.strip()
    # Derive series name from character's first name  e.g. "Spark's Adventures"
    first_name  = description.split(",")[0].split(" is ")[0].strip()
    series_name = f"{first_name}'s Adventures"

    print(f"\n  ─── AUTO-SAVING CHARACTER ──────────────────────────────")
    print(f"  Character   : {description[:80]}...")
    print(f"  Series name : {series_name}")
    print(f"  (Claude will generate flux anchor, palette, personality...)")
    print()

    try:
        char = create_character(description, series_name)
        char_id = char["id"]
        print(f"\n  ✅  Character saved!  For next episode, set:")
        print(f'      CHARACTER_ID = "{char_id}"')
        print(f"  ────────────────────────────────────────────────────────")
        return char_id
    except Exception as e:
        print(f"  ⚠️  Auto-save failed (non-fatal): {e}")
        print(f"  You can still create manually:  python pipeline/character_manager.py create")
        print(f"  ────────────────────────────────────────────────────────")
        return None


def apply_video_config():
    """Apply VIDEO_FORMAT and VIDEO_ORIENTATION to config at runtime."""
    if VIDEO_FORMAT == "short":
        config.NUM_SCENES        = SHORT_NUM_SCENES
        config.SCENE_DURATION_SEC = SHORT_SCENE_DURATION
        config.TARGET_VIDEO_SEC  = SHORT_NUM_SCENES * SHORT_SCENE_DURATION
    else:
        config.NUM_SCENES        = LONG_NUM_SCENES
        config.SCENE_DURATION_SEC = LONG_SCENE_DURATION
        config.TARGET_VIDEO_SEC  = LONG_NUM_SCENES * LONG_SCENE_DURATION

    orientation_map = {
        "vertical":   (1080, 1920, "9:16",  "portrait_9_16"),
        "horizontal": (1920, 1080, "16:9",  "landscape_16_9"),
        "square":     (1080, 1080, "1:1",   "square_hd"),
    }
    w, h, ar, fal_size = orientation_map.get(VIDEO_ORIENTATION, orientation_map["vertical"])
    config.VIDEO_WIDTH        = w
    config.VIDEO_HEIGHT       = h
    config.VIDEO_ASPECT_RATIO = ar
    config.FAL_IMAGE_SIZE     = fal_size

    # Scale Claude token budget to scene count — prevents truncation on long videos
    config.STORY_MAX_TOKENS = config.story_max_tokens_for(config.NUM_SCENES)


# Apply subject/niche — must happen BEFORE pipeline modules are imported
# so prompts/loader.py picks up config.SUBJECT when resolving prompt files.
config.SUBJECT          = SUBJECT
config.STORY_CATEGORIES = config._CATEGORIES_BY_SUBJECT.get(SUBJECT, config._CATEGORIES_BY_SUBJECT["kids"])
config.MUSIC_MOODS      = config._MUSIC_MOODS_BY_SUBJECT.get(SUBJECT, config._MUSIC_MOODS_BY_SUBJECT["kids"])

# Voice — pick adult or kids voices based on subject
_voices = getattr(config, f"_VOICES_{SUBJECT.upper()}", config._VOICES_KIDS)
config.VOICE_WARM_NARRATOR = _voices["warm_narrator"]
config.VOICE_ENERGETIC     = _voices["energetic"]
config.VOICE_CHARACTER     = _voices["character"]
config.VOICE_DEFAULT       = _voices["warm_narrator"]
config.VOICE_EMOTION_MAP   = getattr(config, f"_EMOTION_MAP_{SUBJECT.upper()}", config._EMOTION_MAP_KIDS)
config.VOICE_SETTINGS      = getattr(config, f"_VOICE_SETTINGS_{SUBJECT.upper()}", config._VOICE_SETTINGS_KIDS)

# Music — pick search keywords and volume matching the subject style
config.MUSIC_MOOD_KEYWORDS = getattr(config, f"_MUSIC_KEYWORDS_{SUBJECT.upper()}", config._MUSIC_KEYWORDS_KIDS)
config.MUSIC_VOLUME = 0.12 if SUBJECT != "kids" else 0.20   # quieter for adult narration

apply_video_config()


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def separator(title: str = "", width: int = 60):
    if title:
        pad = max(0, (width - len(title) - 2) // 2)
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'═' * width}")


def header():
    total_sec = config.NUM_SCENES * config.SCENE_DURATION_SEC
    duration_label = (
        f"~{total_sec}s" if total_sec < 120
        else f"~{total_sec // 60}m {total_sec % 60}s"
    )
    print("\n" + "═" * 60)
    print("   🎬  Video Generator — Test Runner")
    print("═" * 60)
    print(f"   Stage      : {TEST_STAGE}")
    print(f"   Topic      : {TEST_TOPIC}")
    print(f"   Category   : {TEST_CATEGORY or 'auto'}")
    print(f"   Slug       : {LOAD_EXISTING_SLUG or 'generate fresh'}")
    print(f"   Format     : {VIDEO_FORMAT} ({duration_label}, {config.NUM_SCENES} scenes)")
    print(f"   Orientation: {VIDEO_ORIENTATION} ({config.VIDEO_ASPECT_RATIO}  "
          f"{config.VIDEO_WIDTH}×{config.VIDEO_HEIGHT})")
    print(f"   max_tokens : {config.STORY_MAX_TOKENS}")
    print("═" * 60)


def load_refined():
    """Load refined script — required by most stages after Stage 2."""
    from pipeline.scene_refiner import SceneRefiner
    slug = LOAD_EXISTING_SLUG
    if not slug:
        print("  ❌  LOAD_EXISTING_SLUG is not set.")
        print("  Run Stage 1 first, then paste the slug into LOAD_EXISTING_SLUG.")
        sys.exit(1)
    try:
        refined = SceneRefiner.load_refined(slug)
        print(f"  Loaded refined script: '{refined.title}' ({len(refined.scenes)} scenes)")
        return refined
    except FileNotFoundError:
        print(f"  ❌  Refined script not found for slug: '{slug}'")
        print(f"  Run Stage 2 first with LOAD_EXISTING_SLUG = '{slug}'")
        sys.exit(1)


def check_file(path: Path, label: str) -> bool:
    ok = path.exists() and path.stat().st_size > 100
    icon = "✅" if ok else "❌"
    size = f"  [{path.stat().st_size // 1024}KB]" if ok else ""
    print(f"  {icon}  {label}: {path}{size}")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 1 — Story Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_1():
    separator("STAGE 1 — Story Generation")
    from pipeline.story_generator import StoryGenerator, print_script_summary

    gen = StoryGenerator()
    main_char, supporting = _load_characters()

    if main_char:
        ep = main_char.get("episode_count", 0) + 1
        print(f"  Character : {main_char['name']} — Episode {ep}")
        print(f"  Series    : {main_char.get('series_name', '')}")
        if supporting:
            print(f"  Supporting: {', '.join(c['name'] for c in supporting)}")
        print()

    if LOAD_EXISTING_SLUG:
        print(f"  Loading saved script: {LOAD_EXISTING_SLUG}")
        script = StoryGenerator.load_script(LOAD_EXISTING_SLUG)
    else:
        script = gen.generate(
            topic=TEST_TOPIC,
            category=TEST_CATEGORY,
            save=SAVE_OUTPUT,
            main_character=main_char,
            supporting_characters=supporting if supporting else None,
        )

    if PRINT_JSON:
        separator("RAW JSON OUTPUT")
        print(script.model_dump_json(indent=2))
    else:
        print_script_summary(script)

    separator("VALIDATION REPORT")
    checks = [
        ("Title present",                bool(script.title)),
        ("Slug is URL-safe",             script.slug.replace("-", "").isalnum()),
        (f"Exactly {config.NUM_SCENES} scenes", len(script.scenes) == config.NUM_SCENES),
        ("All scenes have narration",    all(s.narration for s in script.scenes)),
        ("All scenes have image_prompt", all(s.image_prompt for s in script.scenes)),
        ("All scenes have emotion",      all(s.emotion for s in script.scenes)),
        ("Not all emotion=happy",        len({s.emotion for s in script.scenes}) > 1),
        ("All scenes have camera_move",  all(s.camera_movement for s in script.scenes)),
        ("Duration plausible",           script.total_duration_seconds >= config.NUM_SCENES * 3),
        ("Has YouTube tags",             len(script.youtube_tags) >= 5),
        ("Has thumbnail concept",        bool(script.thumbnail_concept)),
        ("Has moral",                    bool(script.moral)),
    ]
    passed = _print_checks(checks)
    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result: {status}")

    if SAVE_OUTPUT:
        print(f"\n  ─── NEXT STEP ───────────────────────────────────────")
        print(f"  Set LOAD_EXISTING_SLUG = \"{script.slug}\"")
        print(f"  Then run Stage 2")
        print(f"  ────────────────────────────────────────────────────")

    # Auto-save the character Claude invented so it can be reused in future episodes
    if USE_CHARACTER and AUTO_SAVE_CHARACTER and not CHARACTER_ID and SAVE_OUTPUT:
        _auto_save_character(script)

    separator()
    return script


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 2 — Scene Refinement
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_2():
    separator("STAGE 2 — Scene Refinement (Art Direction)")
    from pipeline.story_generator import StoryGenerator
    from pipeline.scene_refiner import SceneRefiner, print_refined_summary
    import re

    # Load Stage 1 script
    if LOAD_EXISTING_SLUG:
        print(f"  Loading Stage 1 script: {LOAD_EXISTING_SLUG}")
        script = StoryGenerator.load_script(LOAD_EXISTING_SLUG)
    else:
        print("  No LOAD_EXISTING_SLUG — generating Stage 1 first...")
        gen = StoryGenerator()
        script = gen.generate(topic=TEST_TOPIC, category=TEST_CATEGORY, save=SAVE_OUTPUT)

    print(f"  Loaded: '{script.title}' ({len(script.scenes)} scenes)")
    print()

    main_char, supporting = _load_characters()
    refiner = SceneRefiner()
    refined = refiner.refine(
        script,
        save=SAVE_OUTPUT,
        main_character=main_char,
        supporting_characters=supporting if supporting else None,
    )

    if PRINT_JSON:
        separator("RAW REFINED JSON")
        print(refined.model_dump_json(indent=2))
    else:
        print_refined_summary(refined)

    separator("VALIDATION REPORT")
    hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
    checks = [
        ("Title preserved",                 refined.title == script.title),
        ("Slug preserved",                  refined.slug == script.slug),
        (f"Exactly {config.NUM_SCENES} refined scenes", len(refined.scenes) == config.NUM_SCENES),
        ("Global style suffix present",     bool(refined.global_style_suffix)),
        ("Global negative prompt present",  bool(refined.global_negative_prompt)),
        ("Colour story present",            bool(refined.colour_story)),
        ("Thumbnail concept refined",       bool(refined.thumbnail_concept)),
        ("Thumbnail negative prompt set",   bool(refined.thumbnail_negative_prompt)),
        ("All narrations preserved",        all(
            rs.narration == os.narration
            for rs, os in zip(refined.scenes, script.scenes)
        )),
        ("All on_screen_text ≤ 5 words",   all(
            len(s.on_screen_text.split()) <= 5
            for s in refined.scenes
        )),
        ("All scenes have negative_prompt", all(
            bool(s.negative_prompt) for s in refined.scenes
        )),
        ("All scenes have colour_palette",  all(
            len(s.colour_palette) == 3 for s in refined.scenes
        )),
        ("All palette colours valid hex",   all(
            all(hex_re.match(c) for c in s.colour_palette)
            for s in refined.scenes
        )),
        ("All image prompts ≥ 60 words",    all(
            len(s.image_prompt.split()) >= 60
            for s in refined.scenes
        )),
        ("All aspect ratios 9:16",          all(
            s.fal_aspect_ratio == "9:16" for s in refined.scenes
        )),
    ]
    passed = _print_checks(checks)
    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result: {status}")
    if SAVE_OUTPUT:
        saved = Path(config.STORIES_DIR) / f"{refined.slug}_refined.json"
        print(f"  Saved : {saved}")

    separator()
    return refined


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 3 — Image Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_3():
    separator("STAGE 3 — Image Generation (Fal.ai Flux)")
    from pipeline.image_generator import ImageGenerator

    refined = load_refined()
    n_scenes = len(refined.scenes)
    est_cost = n_scenes * 0.04

    print(f"  Model      : fal-ai/flux-pro/v1.1")
    print(f"  Scenes     : {n_scenes}")
    print(f"  Est. cost  : ~${est_cost:.2f}")
    print()

    gen = ImageGenerator(max_concurrent=4)
    results = gen.generate(refined)

    separator("VALIDATION REPORT")
    out_dir   = Path(config.RAW_DIR) / refined.slug
    successful = [r for r in results if r.get("status") == "success"]
    failed     = [r for r in results if r.get("status") == "failed"]

    checks = [
        (f"All {n_scenes} images attempted",  len(results) == n_scenes),
        (f"All {n_scenes} images succeeded",  len(successful) == n_scenes),
        ("Output folder exists",              out_dir.exists()),
        ("manifest.json saved",              (out_dir / "manifest.json").exists()),
        ("All PNG files on disk",            all(
            Path(r["file"]).exists() for r in successful
        )),
        ("All PNGs > 50KB (not blank)",      all(
            r.get("size_kb", 0) > 50 for r in successful
        )),
        (f"Scene numbers 1–{n_scenes}",      sorted(
            r["scene_number"] for r in results
        ) == list(range(1, n_scenes + 1))),
    ]
    passed = _print_checks(checks)

    if failed:
        separator("FAILED SCENES")
        for r in failed:
            print(f"  Scene {r['scene_number']:02d}: {r.get('error', 'unknown error')}")

    if successful:
        separator("TIMING (slowest to fastest)")
        for r in sorted(successful, key=lambda x: -x["elapsed"])[:5]:
            bar = "█" * min(int(r["elapsed"] / 2), 30)
            print(f"  Scene {r['scene_number']:02d}  {r['elapsed']:5.1f}s  {bar}  [{r['size_kb']}KB]")

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result : {status}")
    print(f"  Images : {out_dir}")
    separator()
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 4 — Voice Narration
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_4():
    separator("STAGE 4 — Voice Narration (ElevenLabs)")
    from pipeline.voice_generator import VoiceGenerator

    refined = load_refined()
    n_scenes = len(refined.scenes)

    gen = VoiceGenerator(use_fast_model=USE_FAST_VOICE)
    results = gen.generate(refined)

    separator("VALIDATION REPORT")
    out_dir   = Path(config.AUDIO_DIR) / refined.slug
    successful = [r for r in results if r.get("status") == "success"]
    failed     = [r for r in results if r.get("status") == "failed"]

    checks = [
        (f"All {n_scenes} clips attempted",   len(results) == n_scenes),
        (f"All {n_scenes} clips succeeded",   len(successful) == n_scenes),
        ("Output folder exists",              out_dir.exists()),
        ("full_narration.mp3 saved",          (out_dir / "full_narration.mp3").exists()),
        ("voice_manifest.json saved",         (out_dir / "voice_manifest.json").exists()),
        ("All MP3 files on disk",             all(
            Path(r["file"]).exists() for r in successful
        )),
        ("All MP3s > 5KB",                    all(
            r.get("size_kb", 0) > 5 for r in successful
        )),
        ("Multiple voice labels used",        len({
            r.get("voice_label") for r in successful
        }) > 1),
    ]
    passed = _print_checks(checks)

    if failed:
        separator("FAILED SCENES")
        for r in failed:
            print(f"  Scene {r['scene_number']:02d}: {r.get('error', 'unknown error')}")

    if successful:
        separator("VOICE ASSIGNMENT")
        for r in sorted(successful, key=lambda x: x["scene_number"]):
            print(f"  Scene {r['scene_number']:02d}  [{r.get('emotion','?'):10s}]  "
                  f"[{r.get('voice_label','?'):10s}]  {r.get('size_kb',0)}KB  "
                  f"~{r.get('estimated_audio_duration', 0):.1f}s")

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result : {status}")
    separator()
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 5 — Background Music
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_5():
    separator("STAGE 5 — Background Music (Bensound)")
    from pipeline.music_handler import MusicHandler

    refined = load_refined()

    handler = MusicHandler()
    mix_path = handler.create_mix(refined)

    separator("VALIDATION REPORT")
    audio_dir = Path(config.AUDIO_DIR) / refined.slug
    music_dir = Path(config.MUSIC_DIR) / refined.slug

    narration_path = audio_dir / "full_narration.mp3"
    final_mix_path = audio_dir / "final_mix.mp3"

    checks = [
        ("full_narration.mp3 exists",    check_file(narration_path, "narration")),
        ("final_mix.mp3 saved",          mix_path is not None and mix_path.exists()),
        ("final_mix.mp3 > 100KB",        mix_path is not None and
                                          mix_path.exists() and
                                          mix_path.stat().st_size > 100_000),
        ("Music dir created",            music_dir.exists()),
    ]
    # Already printed by check_file; run remaining checks silently
    remaining_checks = [
        ("final_mix.mp3 saved",        mix_path is not None and (mix_path.exists() if mix_path else False)),
        ("final_mix > 100KB",          mix_path is not None and mix_path.exists() and mix_path.stat().st_size > 100_000),
    ]
    all_checks = [
        ("full_narration.mp3 exists",  narration_path.exists()),
        ("final_mix.mp3 saved",        mix_path is not None),
        ("final_mix.mp3 > 100KB",      mix_path is not None and mix_path.exists() and mix_path.stat().st_size > 100_000),
        ("Music folder created",       music_dir.exists()),
    ]
    passed = _print_checks(all_checks)

    separator()
    status = "PASSED" if passed == len(all_checks) else f"PARTIAL ({passed}/{len(all_checks)})"
    print(f"  Result : {status}")
    if mix_path:
        print(f"  Output : {mix_path}")
    separator()
    return mix_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 6 — Video Render  (was Stage 8 — now in correct order)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_6():
    separator("STAGE 6 — Video Render (FFmpeg)")
    from pipeline.video_renderer import VideoRenderer

    refined = load_refined()

    print(f"  Resolution : {config.VIDEO_WIDTH}×{config.VIDEO_HEIGHT}")
    print(f"  FPS        : {config.VIDEO_FPS}")
    print(f"  Subtitles  : {'burn-in' if BURN_SUBTITLES else 'separate only'}")
    print()

    renderer = VideoRenderer()
    final_path = renderer.render(refined, burn_subtitles=BURN_SUBTITLES)

    separator("VALIDATION REPORT")
    out_dir       = Path(config.FINAL_DIR) / refined.slug
    manifest_path = out_dir / "render_manifest.json"

    checks = [
        ("Final video exists",        final_path.exists()),
        ("Video > 1MB",               final_path.exists() and
                                       final_path.stat().st_size > 1_000_000),
        ("render_manifest.json saved", manifest_path.exists()),
    ]

    if manifest_path.exists():
        rm = json.loads(manifest_path.read_text())
        n_rendered = len(rm.get("scenes", []))
        total_dur  = rm.get("total_duration", 0)
        checks += [
            (f"All {len(refined.scenes)} scenes in manifest", n_rendered == len(refined.scenes)),
            ("Total duration > 10s",    total_dur > 10),
        ]
        print(f"\n  Scenes rendered : {n_rendered}")
        print(f"  Total duration  : {total_dur:.1f}s")

    passed = _print_checks(checks)

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result : {status}")
    if final_path.exists():
        mb = final_path.stat().st_size / 1_000_000
        print(f"  Video  : {final_path}  [{mb:.1f}MB]")
    separator()

    print(f"\n  ─── IMPORTANT ────────────────────────────────────────")
    print(f"  Now run Stage 7 (subtitles) so timing is in sync.")
    print(f"  Stage 7 reads render_manifest.json for exact frame timing.")
    print(f"  ────────────────────────────────────────────────────")
    return final_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 7 — SRT Subtitles  (run AFTER Stage 6)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_7():
    separator("STAGE 7 — SRT Subtitles (script-based, free)")
    from pipeline.subtitle_generator import SubtitleGenerator

    refined = load_refined()

    # Warn if Stage 6 hasn't run yet
    rm_path = Path(config.FINAL_DIR) / refined.slug / "render_manifest.json"
    if not rm_path.exists():
        print("  ⚠️  render_manifest.json not found — run Stage 6 first for best results.")
        print("  Continuing with voice manifest timing (less accurate)...")
        print()

    gen = SubtitleGenerator()
    srt_path, ass_path = gen.generate(refined)

    separator("VALIDATION REPORT")
    checks = [
        ("SRT file saved",             srt_path.exists()),
        ("ASS file saved",             ass_path.exists()),
        ("SRT > 100 bytes",            srt_path.exists() and srt_path.stat().st_size > 100),
        ("ASS > 100 bytes",            ass_path.exists() and ass_path.stat().st_size > 100),
        ("SRT has timing lines",       srt_path.exists() and
                                        " --> " in srt_path.read_text(encoding="utf-8")),
    ]

    if srt_path.exists():
        srt_text  = srt_path.read_text(encoding="utf-8")
        n_entries = srt_text.count(" --> ")
        checks.append((f"SRT has {len(refined.scenes)} subtitle entries",
                        n_entries == len(refined.scenes)))
        print(f"\n  SRT entries : {n_entries}")
        print(f"  SRT size    : {srt_path.stat().st_size} bytes")
        print(f"  ASS size    : {ass_path.stat().st_size} bytes")

    passed = _print_checks(checks)

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result : {status}")
    print(f"  SRT    : {srt_path}  ← upload to YouTube Studio")
    print(f"  ASS    : {ass_path}  ← burn-in by Stage 6")
    separator()
    return srt_path, ass_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 8 — Thumbnail Generation  (was Stage 9)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_8():
    separator("STAGE 8 — Thumbnail Generation (Fal.ai Flux + Pillow)")
    from pipeline.thumbnail_generator import ThumbnailGenerator

    refined = load_refined()

    print(f"  Character : {refined.main_character[:70]}...")
    print(f"  Concept   : {refined.thumbnail_concept[:80]}...")
    print()

    gen = ThumbnailGenerator()
    results = gen.generate(refined)

    separator("VALIDATION REPORT")
    out_dir = Path(config.THUMBS_DIR) / refined.slug

    expected_files = [
        ("thumbnail_16x9.png",       "YouTube (1280×720)"),
        ("thumbnail_9x16.png",       "Shorts  (1080×1920)"),
        ("thumbnail_16x9_text.png",  "YouTube + title text  ← upload this"),
        ("thumbnail_9x16_text.png",  "Shorts + title text"),
    ]

    checks = [("Thumbnail dir exists", out_dir.exists())]
    for fname, label in expected_files:
        path = out_dir / fname
        checks.append((f"{fname} saved ({label})", path.exists() and path.stat().st_size > 10_000))

    passed = _print_checks(checks)

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result     : {status}")
    print(f"  Upload to YouTube Studio: {out_dir / 'thumbnail_16x9_text.png'}")
    separator()
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 9 — Metadata Optimisation  (was Stage 10)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_9():
    separator("STAGE 9 — Metadata Optimisation (Claude SEO)")
    from pipeline.metadata_optimizer import MetadataOptimizer

    refined = load_refined()

    # Try to read actual video duration from render manifest
    duration = config.TARGET_VIDEO_SEC
    is_long  = duration >= 480
    rm_path  = Path(config.FINAL_DIR) / refined.slug / "render_manifest.json"
    if rm_path.exists():
        try:
            rm = json.loads(rm_path.read_text())
            duration = int(sum(s.get("duration", 0) for s in rm.get("scenes", [])))
            is_long  = duration >= 480
            print(f"  Duration   : {duration}s (from render manifest)")
        except Exception:
            print(f"  Duration   : {duration}s (from config fallback)")
    else:
        print(f"  Duration   : {duration}s (render manifest not found — run Stage 6 first)")

    print(f"  Long video : {is_long}")
    print()

    opt  = MetadataOptimizer()
    meta = opt.generate(refined, video_duration_sec=duration, is_long=is_long)

    separator("VALIDATION REPORT")
    out_dir   = Path(config.OUTPUT_DIR) / "metadata" / refined.slug
    json_path = out_dir / "youtube_metadata.json"
    txt_path  = out_dir / "youtube_metadata.txt"

    checks = [
        ("Metadata JSON saved",          json_path.exists()),
        ("Copy-paste TXT saved",         txt_path.exists()),
        ("title_primary present",        bool(meta.get("title_primary"))),
        ("title_variants is list of 3",  len(meta.get("title_variants", [])) >= 2),
        ("description_full present",     len(meta.get("description_full", "")) > 100),
        ("description_short present",    bool(meta.get("description_short"))),
        ("tags has ≥ 20 entries",        len(meta.get("tags", [])) >= 20),
        ("thumbnail_text_options ≥ 2",   len(meta.get("thumbnail_text_options", [])) >= 2),
        ("best_upload_time present",     bool(meta.get("best_upload_time"))),
        ("Bensound credit in desc",      "Bensound" in meta.get("description_full", "")),
    ]

    if is_long:
        checks.append(("Chapters included for long video",
                        meta.get("chapters", {}).get("include") is True))

    passed = _print_checks(checks)

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result      : {status}")
    print(f"  Title       : {meta.get('title_primary', '')}")
    print(f"  Viral score : {meta.get('viral_score_estimate', 'N/A')}")
    print(f"  Metadata    : {txt_path}  ← open for copy-paste")
    separator()
    return meta


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 10 — YouTube Upload  (was Stage 11)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_10():
    separator("STAGE 10 — YouTube Upload (YouTube Data API v3)")
    from pipeline.youtube_uploader import YouTubeUploader
    from pipeline.metadata_optimizer import MetadataOptimizer

    refined = load_refined()

    # Load metadata from Stage 9
    try:
        meta = MetadataOptimizer.load_metadata(refined.slug)
        print(f"  Metadata   : loaded from Stage 9")
        print(f"  Title      : {meta.get('title_primary', refined.title)}")
    except FileNotFoundError:
        print("  ⚠️  Stage 9 metadata not found — using basic metadata from script")
        meta = {
            "title_primary":    refined.title,
            "description_full": refined.youtube_description + "\n\nMusic by Bensound.com",
            "tags":             refined.youtube_tags,
            "category_id":      "27",
            "made_for_kids":    True,
        }

    print(f"  Privacy    : {YOUTUBE_PRIVACY}")
    print(f"  Thumbnail  : {YOUTUBE_THUMBNAIL}")
    print(f"  Subtitles  : {YOUTUBE_SUBTITLES}")
    print()

    # Pre-flight checks before spending upload quota
    separator("PRE-FLIGHT CHECKS")
    video_path = Path(config.FINAL_DIR) / refined.slug / f"{refined.slug}_final.mp4"
    thumb_path = Path(config.THUMBS_DIR) / refined.slug / "thumbnail_16x9_text.png"
    srt_path   = Path(config.SUBTITLES_DIR) / refined.slug / f"{refined.slug}.srt"
    creds_path = Path("credentials.json")

    preflight = [
        ("credentials.json exists",  creds_path.exists()),
        ("Final video exists",        video_path.exists()),
        ("Video > 1MB",               video_path.exists() and
                                       video_path.stat().st_size > 1_000_000),
        ("Thumbnail exists",          thumb_path.exists()),
        ("SRT subtitles exist",       srt_path.exists()),
    ]
    pf_passed = _print_checks(preflight)

    if not creds_path.exists():
        print()
        print("  ❌  credentials.json missing — one-time setup required:")
        print("  1. Go to console.cloud.google.com → New Project")
        print("  2. Enable YouTube Data API v3")
        print("  3. Create OAuth 2.0 → Desktop App → Download credentials.json")
        print("  4. Save credentials.json to your project root folder")
        separator()
        return None

    if pf_passed < len(preflight):
        print()
        print("  ❌  Pre-flight failed — fix the above issues before uploading.")
        separator()
        return None

    print()
    print("  ✅  All pre-flight checks passed — starting upload...")
    print()

    uploader = YouTubeUploader()
    url = uploader.upload(
        refined,
        meta,
        privacy=YOUTUBE_PRIVACY,
        upload_thumbnail=YOUTUBE_THUMBNAIL,
        upload_subtitles=YOUTUBE_SUBTITLES,
    )

    separator("VALIDATION REPORT")
    result_path = Path(config.OUTPUT_DIR) / "metadata" / refined.slug / "upload_result.json"
    checks = [
        ("URL returned",             bool(url)),
        ("URL contains video ID",    "youtube.com" in (url or "")),
        ("upload_result.json saved", result_path.exists()),
    ]
    passed = _print_checks(checks)

    separator()
    status = "PASSED" if passed == len(checks) else f"PARTIAL ({passed}/{len(checks)})"
    print(f"  Result : {status}")
    if url:
        print(f"  URL    : {url}")
    separator()

    # Log episode to character series if character pipeline is active
    if USE_CHARACTER and CHARACTER_ID and LOG_EPISODE and url:
        from pipeline.character_manager import log_episode
        log_episode(
            character_id=CHARACTER_ID,
            title=refined.title,
            slug=refined.slug,
            topic=TEST_TOPIC,
            youtube_url=url or "",
        )

    return url


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _print_checks(checks: list[tuple[str, bool]]) -> int:
    """Print check results and return count of passed checks."""
    passed = 0
    for label, result in checks:
        icon = "✅" if result else "❌"
        print(f"  {icon}  {label}")
        if result:
            passed += 1
    return passed


# ─────────────────────────────────────────────────────────────────────────────
#  DISPATCH TABLE
# ─────────────────────────────────────────────────────────────────────────────

STAGES = {
    1:  test_stage_1,   # Story generation
    2:  test_stage_2,   # Scene refinement
    3:  test_stage_3,   # Image generation
    4:  test_stage_4,   # Voice narration
    5:  test_stage_5,   # Background music
    6:  test_stage_6,   # Video render        ← was Stage 8
    7:  test_stage_7,   # SRT subtitles       ← was Stage 7 (order correct now)
    8:  test_stage_8,   # Thumbnail           ← was Stage 9
    9:  test_stage_9,   # Metadata            ← was Stage 10
    10: test_stage_10,  # YouTube upload      ← was Stage 11
}

STAGE_NAMES = {
    1:  "Story Generation",
    2:  "Scene Refinement",
    3:  "Image Generation",
    4:  "Voice Narration",
    5:  "Background Music",
    6:  "Video Render",
    7:  "SRT Subtitles",
    8:  "Thumbnail Generation",
    9:  "Metadata Optimisation",
    10: "YouTube Upload",
}


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    header()

    if TEST_STAGE not in STAGES:
        print(f"\n  ❌  Invalid TEST_STAGE: {TEST_STAGE}")
        print(f"  Must be 1–{max(STAGES)}. Available stages:")
        for num, name in STAGE_NAMES.items():
            print(f"    {num:2d} — {name}")
        sys.exit(1)

    print(f"\n  Running: Stage {TEST_STAGE} — {STAGE_NAMES[TEST_STAGE]}")
    print()

    try:
        result = STAGES[TEST_STAGE]()

    except EnvironmentError as e:
        print(f"\n  ❌  Environment error: {e}")
        print("  Check your .env file contains all required API keys.")
        sys.exit(1)

    except FileNotFoundError as e:
        print(f"\n  ❌  File not found: {e}")
        print("  Make sure all previous stages have been run in order.")
        sys.exit(1)

    except ImportError as e:
        print(f"\n  ❌  Missing package: {e}")
        print("  Run: pip install -r requirements.txt")
        sys.exit(1)

    except KeyboardInterrupt:
        print(f"\n\n  ⚠️  Interrupted by user.")
        sys.exit(0)

    except Exception as e:
        print(f"\n  ❌  Unexpected error in Stage {TEST_STAGE}: {e}")
        raise