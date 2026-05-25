"""
run_pipeline.py — Master Workflow Runner
=========================================
Run the complete AI Kids Video pipeline from a single script.
No need to set TEST_STAGE manually — this runs all stages in order.

USAGE:
    python run_pipeline.py

CONFIGURATION:
    Edit the CONFIG section below — that's the only thing you need to touch.

STAGE ORDER (always):
    1 → Story generation      (Claude)
    2 → Scene refinement      (Claude art director)
    3 → Image generation      (Fal.ai Flux)
    4 → Voice narration       (ElevenLabs)
    5 → Background music      (Bensound)
    8 → Video render          (FFmpeg) ← must run before Stage 7
    7 → SRT subtitles         (free, script-based)
    9 → Thumbnail generation  (Fal.ai Flux + Pillow)
   10 → Metadata optimisation (Claude SEO)
   11 → YouTube upload        (YouTube Data API)
"""

import os
import sys
import time
import json
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  ✏️  EDIT THIS SECTION — everything you need to configure
# ─────────────────────────────────────────────────────────────────────────────

# ── STORY ─────────────────────────────────────────────────────────────────────
TOPIC    = "Titanic story for kids"   # Your one-line story idea
CATEGORY = None                        # None = Claude auto-selects, or set one:
                                       # "animal_adventure"
                                       # "friendship_and_emotions"
                                       # "magic_and_fantasy"
                                       # "learning_and_educational"
                                       # "bedtime_and_calming"

# ── CHARACTER SERIES ───────────────────────────────────────────────────────────
# Set CHARACTER_ID to use a saved character across all videos in a series.
# The character's visual description and flux_anchor are locked into Stage 1 & 2
# so every image shows the same character consistently.
#
# First time: run  python character_manager.py create  to make a character.
# Then set CHARACTER_ID = "leo" (or whatever ID was assigned).
#
CHARACTER_ID             = None        # e.g. "leo" | None = Claude invents a character
SUPPORTING_CHARACTER_IDS = []          # e.g. ["bella", "timmy"] | [] = no supporting chars
LOG_EPISODE              = True        # True = log this video to the character's series file

# ── VIDEO LENGTH ───────────────────────────────────────────────────────────────
VIDEO_FORMAT = "short"                 # "short" = 60s Shorts / "long" = 8-15 min

# Short video settings (used when VIDEO_FORMAT = "short")
SHORT_NUM_SCENES      = 12             # 12 scenes × ~5s = ~60s
SHORT_SCENE_DURATION  = 5             # seconds per scene

# Long video settings (used when VIDEO_FORMAT = "long")
LONG_NUM_SCENES       = 60            # 60 scenes × ~10s = ~10 min
LONG_SCENE_DURATION   = 10            # seconds per scene
LONG_TARGET_MINUTES   = 10            # target video length in minutes

# ── VIDEO SIZE / FORMAT ────────────────────────────────────────────────────────
VIDEO_ORIENTATION = "vertical"         # "vertical" = 9:16 Shorts/TikTok/Reels
                                       # "horizontal" = 16:9 YouTube standard
                                       # "square" = 1:1 Instagram feed

# ── PIPELINE STAGES TO RUN ────────────────────────────────────────────────────
RUN_STAGE_1  = True    # Story generation     (~10s, ~$0.01)
RUN_STAGE_2  = True    # Scene refinement     (~50s, ~$0.02)
RUN_STAGE_3  = True    # Image generation     (~60s, ~$0.48 for 12 images)
RUN_STAGE_4  = True    # Voice narration      (~40s, free)
RUN_STAGE_5  = True    # Background music     (~5s,  free)
RUN_STAGE_8  = True    # Video render         (~90s, free)
RUN_STAGE_7  = True    # SRT subtitles        (~1s,  free)
RUN_STAGE_9  = True    # Thumbnail            (~30s, ~$0.08)
RUN_STAGE_10 = True    # Metadata optimise    (~15s, ~$0.005)
RUN_STAGE_11 = False   # YouTube upload       (~30s, free) ← set True to auto-upload

# ── YOUTUBE UPLOAD SETTINGS ────────────────────────────────────────────────────
YOUTUBE_PRIVACY       = "public"       # "public", "unlisted", or "private"
YOUTUBE_THUMBNAIL     = True           # Upload custom thumbnail
YOUTUBE_SUBTITLES     = True           # Upload SRT captions

# ── RESUME / REUSE ─────────────────────────────────────────────────────────────
LOAD_EXISTING_SLUG    = None           # Set to reuse a saved script, e.g.:
                                       # "timmys-big-ship-adventure"
                                       # Saves cost by skipping Stages 1-2

# ── PARALLEL IMAGES ────────────────────────────────────────────────────────────
IMAGE_CONCURRENT      = 4              # How many images to generate at once
                                       # 4 = safe for free tier
                                       # 6-8 = ok with paid Fal.ai credits

# ── BURN SUBTITLES INTO VIDEO ─────────────────────────────────────────────────
BURN_SUBTITLES        = True           # Burn ASS subtitles directly into video
                                       # Also always generates separate .SRT file

# ─────────────────────────────────────────────────────────────────────────────
#  END OF CONFIG — no need to edit below this line
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config


def separator(title: str = "", char: str = "═", width: int = 60):
    if title:
        pad = max(0, (width - len(title) - 2) // 2)
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'═' * width}")


def banner():
    print("\n" + "═" * 60)
    print("   🎬  AI Kids Video Generator — Full Pipeline Runner")
    print("═" * 60)
    fmt_map = {
        "vertical":   "9:16  (YouTube Shorts / TikTok / Instagram Reels)",
        "horizontal": "16:9  (YouTube standard)",
        "square":     "1:1   (Instagram feed)",
    }
    if VIDEO_FORMAT == "short":
        num_scenes = SHORT_NUM_SCENES
        scene_dur  = SHORT_SCENE_DURATION
        total_sec  = num_scenes * scene_dur
        fmt_label  = f"Short (~{total_sec}s)"
    else:
        num_scenes = LONG_NUM_SCENES
        scene_dur  = LONG_SCENE_DURATION
        total_sec  = num_scenes * scene_dur
        fmt_label  = f"Long (~{total_sec // 60} min)"

    print(f"   Topic    : {TOPIC}")
    print(f"   Format   : {fmt_label}")
    print(f"   Size     : {fmt_map.get(VIDEO_ORIENTATION, VIDEO_ORIENTATION)}")
    print(f"   Scenes   : {num_scenes} × {scene_dur}s")
    if LOAD_EXISTING_SLUG:
        print(f"   Resume   : {LOAD_EXISTING_SLUG} (skipping Stages 1-2)")
    stages_on = [s for s, v in [
        ("1", RUN_STAGE_1), ("2", RUN_STAGE_2), ("3", RUN_STAGE_3),
        ("4", RUN_STAGE_4), ("5", RUN_STAGE_5), ("8", RUN_STAGE_8),
        ("7", RUN_STAGE_7), ("9", RUN_STAGE_9), ("10", RUN_STAGE_10),
        ("11", RUN_STAGE_11),
    ] if v]
    print(f"   Stages   : {' → '.join(stages_on)}")
    print("═" * 60)


def apply_video_config():
    """Apply VIDEO_FORMAT and VIDEO_ORIENTATION to config at runtime."""
    if VIDEO_FORMAT == "short":
        config.NUM_SCENES       = SHORT_NUM_SCENES
        config.SCENE_DURATION_SEC = SHORT_SCENE_DURATION
        config.TARGET_VIDEO_SEC = SHORT_NUM_SCENES * SHORT_SCENE_DURATION
    else:
        config.NUM_SCENES       = LONG_NUM_SCENES
        config.SCENE_DURATION_SEC = LONG_SCENE_DURATION
        config.TARGET_VIDEO_SEC = LONG_NUM_SCENES * LONG_SCENE_DURATION

    orientation_map = {
        "vertical":   ("1080", "1920", "9:16",  "portrait_9_16"),
        "horizontal": ("1920", "1080", "16:9",  "landscape_16_9"),
        "square":     ("1080", "1080", "1:1",   "square_hd"),
    }
    w, h, ar, fal_size = orientation_map.get(VIDEO_ORIENTATION, orientation_map["vertical"])
    config.VIDEO_WIDTH        = int(w)
    config.VIDEO_HEIGHT       = int(h)
    config.VIDEO_ASPECT_RATIO = ar
    config.FAL_IMAGE_SIZE     = fal_size

    # Scale Claude output budget to scene count — prevents truncation on long videos
    config.STORY_MAX_TOKENS = config.story_max_tokens_for(config.NUM_SCENES)

    print(f"  Config   : {config.NUM_SCENES} scenes × {config.SCENE_DURATION_SEC}s "
          f"= {config.TARGET_VIDEO_SEC}s, "
          f"{config.VIDEO_WIDTH}×{config.VIDEO_HEIGHT} ({ar}), "
          f"max_tokens={config.STORY_MAX_TOKENS}")


def _load_characters() -> tuple[dict | None, list[dict]]:
    """
    Resolve CHARACTER_ID into loaded character dicts.

    CHARACTER_ID = None   → returns (None, []) — Claude invents the character freely
    CHARACTER_ID = "leo"  → loads characters/leo.json
    CHARACTER_ID = "new"  → interactive: shows existing characters, then either
                            picks one or runs Claude character creator
    """
    if not CHARACTER_ID:
        return None, []

    from character_manager import (
        load_character, load_supporting, list_characters, create_character,
    )

    char_id = CHARACTER_ID

    if char_id == "new":
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
            print()
            description = input("  Describe your character: ").strip()
            series_name = input("  Series name: ").strip()
            if not description or not series_name:
                print("  Both fields required — aborting character creation.")
                return None, []
            char_data = create_character(description, series_name)
            char_id   = char_data["id"]

    main = load_character(char_id)
    supporting = load_supporting(SUPPORTING_CHARACTER_IDS) if SUPPORTING_CHARACTER_IDS else []
    return main, supporting


def run_stage_1() -> "VideoScript":
    from pipeline.story_generator import StoryGenerator
    gen = StoryGenerator()
    if LOAD_EXISTING_SLUG:
        print(f"  Loading existing script: {LOAD_EXISTING_SLUG}")
        return StoryGenerator.load_script(LOAD_EXISTING_SLUG)
    main_char, supporting = _load_characters()
    return gen.generate(
        topic=TOPIC,
        category=CATEGORY,
        save=True,
        main_character=main_char,
        supporting_characters=supporting if supporting else None,
    )


def run_stage_2(script) -> "RefinedScript":
    from pipeline.scene_refiner import SceneRefiner
    if LOAD_EXISTING_SLUG:
        try:
            return SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
        except FileNotFoundError:
            pass
    main_char, supporting = _load_characters()
    return SceneRefiner().refine(
        script,
        save=True,
        main_character=main_char,
        supporting_characters=supporting if supporting else None,
    )


def run_stage_3(refined) -> list:
    from pipeline.image_generator import ImageGenerator
    gen = ImageGenerator(max_concurrent=IMAGE_CONCURRENT)
    return gen.generate(refined)


def run_stage_4(refined) -> Path:
    from pipeline.voice_generator import VoiceGenerator
    return VoiceGenerator().generate(refined)


def run_stage_5(refined) -> Path:
    from pipeline.music_handler import MusicHandler

    # Get actual narration duration from voice manifest
    voice_manifest_path = (
        Path(config.AUDIO_DIR) / refined.slug / "voice_manifest.json"
    )
    duration = config.TARGET_VIDEO_SEC
    if voice_manifest_path.exists():
        try:
            vm = json.loads(voice_manifest_path.read_text())
            duration = sum(
                s.get("estimated_audio_duration", config.SCENE_DURATION_SEC)
                for s in vm.get("scenes", [])
                if s.get("status") == "success"
            )
        except Exception:
            pass

    return MusicHandler().create_mix(refined)


def run_stage_8(refined) -> Path:
    from pipeline.video_renderer import VideoRenderer
    renderer = VideoRenderer()
    return renderer.render(refined, burn_subtitles=BURN_SUBTITLES)


def run_stage_7(refined) -> tuple:
    from pipeline.subtitle_generator import SubtitleGenerator
    return SubtitleGenerator().generate(refined)


def run_stage_9(refined) -> dict:
    from pipeline.thumbnail_generator import ThumbnailGenerator
    return ThumbnailGenerator().generate(refined)


def run_stage_10(refined) -> dict:
    from pipeline.metadata_optimizer import MetadataOptimizer

    # Get actual video duration from render manifest if available
    duration = config.TARGET_VIDEO_SEC
    try:
        rm_path = Path(config.FINAL_DIR) / refined.slug / "render_manifest.json"
        if rm_path.exists():
            rm = json.loads(rm_path.read_text())
            duration = int(sum(s.get("duration", 0) for s in rm.get("scenes", [])))
    except Exception:
        pass

    is_long = duration >= 480  # 8+ minutes = long video
    return MetadataOptimizer().generate(refined, video_duration_sec=duration, is_long=is_long)


def run_stage_11(refined, meta: dict) -> str:
    from pipeline.youtube_uploader import YouTubeUploader
    uploader = YouTubeUploader()
    return uploader.upload(
        refined,
        meta,
        privacy=YOUTUBE_PRIVACY,
        upload_thumbnail=YOUTUBE_THUMBNAIL,
        upload_subtitles=YOUTUBE_SUBTITLES,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def main():
    banner()
    apply_video_config()

    t_total = time.time()
    results = {}

    script  = None
    refined = None
    meta    = None

    # ── Stage 1 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_1:
        separator("Stage 1 — Story Generation")
        t = time.time()
        script = run_stage_1()
        results["stage_1"] = {"slug": script.slug, "time": round(time.time() - t, 1)}
        print(f"  ✅  {script.title} [{results['stage_1']['time']}s]")
    else:
        print("\n  ⏩  Stage 1 skipped")

    # ── Stage 2 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_2 and script:
        separator("Stage 2 — Scene Refinement")
        t = time.time()
        refined = run_stage_2(script)
        results["stage_2"] = {"time": round(time.time() - t, 1)}
        print(f"  ✅  Refined [{results['stage_2']['time']}s]")
    elif LOAD_EXISTING_SLUG and not refined:
        from pipeline.scene_refiner import SceneRefiner
        refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
        print(f"\n  ⏩  Stage 2 skipped — loaded {LOAD_EXISTING_SLUG}_refined.json")

    if not refined:
        print("\n  ❌  No refined script available. Run Stage 1+2 first.")
        sys.exit(1)

    slug = refined.slug

    # ── Stage 3 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_3:
        separator("Stage 3 — Image Generation")
        t = time.time()
        img_results = run_stage_3(refined)
        ok = sum(1 for r in img_results if r.get("status") == "success")
        results["stage_3"] = {"images": ok, "time": round(time.time() - t, 1),
                               "cost": round(ok * 0.04, 2)}
        print(f"  ✅  {ok}/{len(img_results)} images [{results['stage_3']['time']}s] "
              f"~${results['stage_3']['cost']}")
    else:
        print("\n  ⏩  Stage 3 skipped")

    # ── Stage 4 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_4:
        separator("Stage 4 — Voice Narration")
        t = time.time()
        run_stage_4(refined)
        results["stage_4"] = {"time": round(time.time() - t, 1)}
        print(f"  ✅  Voice generated [{results['stage_4']['time']}s]")
    else:
        print("\n  ⏩  Stage 4 skipped")

    # ── Stage 5 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_5:
        separator("Stage 5 — Background Music")
        t = time.time()
        run_stage_5(refined)
        results["stage_5"] = {"time": round(time.time() - t, 1)}
        print(f"  ✅  Music mixed [{results['stage_5']['time']}s]")
    else:
        print("\n  ⏩  Stage 5 skipped")

    # ── Stage 8 — MUST come before Stage 7 ──────────────────────────────────
    if RUN_STAGE_8:
        separator("Stage 8 — Video Render")
        t = time.time()
        video_path = run_stage_8(refined)
        results["stage_8"] = {"path": str(video_path), "time": round(time.time() - t, 1)}
        print(f"  ✅  Video rendered [{results['stage_8']['time']}s]")
        print(f"       → {video_path}")
    else:
        print("\n  ⏩  Stage 8 skipped")

    # ── Stage 7 — subtitles AFTER render ─────────────────────────────────────
    if RUN_STAGE_7:
        separator("Stage 7 — SRT Subtitles")
        t = time.time()
        srt_path, ass_path = run_stage_7(refined)
        results["stage_7"] = {"srt": str(srt_path), "time": round(time.time() - t, 1)}
        print(f"  ✅  Subtitles generated [{results['stage_7']['time']}s]")
        print(f"       SRT: {srt_path}")
    else:
        print("\n  ⏩  Stage 7 skipped")

    # ── Stage 9 ──────────────────────────────────────────────────────────────
    if RUN_STAGE_9:
        separator("Stage 9 — Thumbnail Generation")
        t = time.time()
        thumb_results = run_stage_9(refined)
        results["stage_9"] = {"time": round(time.time() - t, 1), "cost": 0.08}
        print(f"  ✅  Thumbnails generated [{results['stage_9']['time']}s]")
    else:
        print("\n  ⏩  Stage 9 skipped")

    # ── Stage 10 — Metadata optimisation ─────────────────────────────────────
    if RUN_STAGE_10:
        separator("Stage 10 — Metadata Optimisation")
        t = time.time()
        meta = run_stage_10(refined)
        results["stage_10"] = {"time": round(time.time() - t, 1)}
        print(f"  ✅  Metadata optimised [{results['stage_10']['time']}s]")
        print(f"       Title: {meta.get('title_primary', '')}")
    else:
        print("\n  ⏩  Stage 10 skipped")
        # Try to load existing metadata
        try:
            from pipeline.metadata_optimizer import MetadataOptimizer
            meta = MetadataOptimizer.load_metadata(slug)
        except Exception:
            meta = {
                "title_primary": refined.title,
                "tags": refined.youtube_tags,
                "description_full": refined.youtube_description,
                "category_id": "27",
                "made_for_kids": True,
            }

    # ── Stage 11 — YouTube Upload ─────────────────────────────────────────────
    youtube_url = ""
    if RUN_STAGE_11:
        separator("Stage 11 — YouTube Upload")
        t = time.time()
        youtube_url = run_stage_11(refined, meta)
        results["stage_11"] = {"url": youtube_url, "time": round(time.time() - t, 1)}
        print(f"  ✅  Uploaded [{results['stage_11']['time']}s]")
    else:
        print("\n  ⏩  Stage 11 skipped (set RUN_STAGE_11 = True to auto-upload)")

    # ── Log episode to character series file ──────────────────────────────────
    if CHARACTER_ID and LOG_EPISODE and refined:
        from character_manager import log_episode
        log_episode(
            character_id=CHARACTER_ID,
            title=refined.title,
            slug=refined.slug,
            topic=TOPIC,
            youtube_url=youtube_url,
        )

    # ── Final Summary ─────────────────────────────────────────────────────────
    total_time = time.time() - t_total
    total_cost = (
        results.get("stage_3", {}).get("cost", 0) +
        results.get("stage_9", {}).get("cost", 0) +
        0.025  # Claude stages 1+2+10
    )

    separator("PIPELINE COMPLETE")
    print(f"\n  📹  {refined.title}")
    print(f"  🎬  Slug  : {slug}")
    print(f"  ⏱️   Time  : {total_time:.0f}s total ({total_time/60:.1f} min)")
    print(f"  💰  Cost  : ~${total_cost:.2f}")
    print()

    video_path = Path(config.FINAL_DIR) / slug / f"{slug}_final.mp4"
    thumb_path = Path(config.OUTPUT_DIR) / "thumbnails" / slug / "thumbnail_16x9_text.png"
    srt_path   = Path(config.SUBTITLES_DIR) / slug / f"{slug}.srt"
    meta_txt   = Path(config.OUTPUT_DIR) / "metadata" / slug / "youtube_metadata.txt"

    print("  OUTPUT FILES:")
    for label, path in [
        ("Video",     video_path),
        ("Thumbnail", thumb_path),
        ("SRT",       srt_path),
        ("Metadata",  meta_txt),
    ]:
        exists = "✅" if path.exists() else "❌"
        print(f"  {exists}  {label}: {path}")

    if RUN_STAGE_11 and "stage_11" in results:
        print(f"\n  🌐  LIVE URL: {results['stage_11']['url']}")
    else:
        print()
        print("  MANUAL UPLOAD STEPS:")
        print(f"  1. Go to studio.youtube.com → Upload")
        print(f"  2. Upload: {video_path}")
        print(f"  3. Thumbnail: {thumb_path}")
        print(f"  4. Subtitles: {srt_path}")
        print(f"  5. Copy metadata from: {meta_txt}")

    # Save run summary
    summary = {
        "slug":        slug,
        "title":       refined.title,
        "topic":       TOPIC,
        "format":      VIDEO_FORMAT,
        "orientation": VIDEO_ORIENTATION,
        "num_scenes":  config.NUM_SCENES,
        "total_time_sec": round(total_time, 1),
        "total_cost_usd": round(total_cost, 2),
        "stages":      results,
    }
    summary_path = Path(config.OUTPUT_DIR) / "metadata" / slug / "run_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Summary saved: {summary_path}")
    print()
    print("═" * 60)


if __name__ == "__main__":
    main()