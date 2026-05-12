"""
run_pipeline.py — Full AI Kids Video Pipeline (all stages in one run)

Edit the ✏️ SETTINGS section below, then run:
    python run_pipeline.py
"""

import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  ✏️  SETTINGS — edit everything in this section before running
# ─────────────────────────────────────────────────────────────────────────────

# ── Story ─────────────────────────────────────────────────────────────────────
TOPIC    = "a tiny dragon who is afraid of fire"
CATEGORY = None     # None = auto-detect, or one of:
                    # "animal_adventure" | "friendship_and_emotions"
                    # "magic_and_fantasy" | "learning_and_educational" | "bedtime_and_calming"

# ── Video format ──────────────────────────────────────────────────────────────
#   "short"  →  9:16  portrait  1080×1920  (YouTube Shorts / TikTok / Reels)
#   "long"   →  16:9  landscape 1920×1080  (standard YouTube video)
VIDEO_FORMAT = "short"

# ── Upload to YouTube after rendering? ────────────────────────────────────────
UPLOAD_TO_YOUTUBE = False
YOUTUBE_PRIVACY   = "private"   # "private" | "unlisted" | "public"
                                 # Always start with "private" to review first!

# ── Resume from an existing story (skips Stages 1 & 2) ───────────────────────
# Set to a slug string to reuse a story you've already generated.
# e.g. LOAD_EXISTING_SLUG = "timmys-big-ship-adventure"
LOAD_EXISTING_SLUG = None

# ── Stage toggles — set False to skip a stage you've already completed ────────
RUN_STAGE_1_STORY      = True    # Story generation           (Claude)
RUN_STAGE_2_REFINE     = True    # Scene refinement           (Claude)
RUN_STAGE_3_IMAGES     = True    # Image generation           (Fal.ai Flux)
RUN_STAGE_4_VOICE      = True    # Voice narration            (ElevenLabs)
RUN_STAGE_5_MUSIC      = True    # Background music mix       (Bensound)
RUN_STAGE_6_VIDEO      = True    # Video render               (FFmpeg)
RUN_STAGE_7_SUBTITLES  = True    # SRT subtitle export
RUN_STAGE_8_THUMBNAIL  = True    # Thumbnail generation       (Fal.ai Flux)

# ── Voice quality ─────────────────────────────────────────────────────────────
USE_FAST_VOICE = False   # False = best quality (eleven_multilingual_v2)
                         # True  = faster/cheaper (eleven_flash_v2_5), good for testing

# ── Image generation concurrency ──────────────────────────────────────────────
IMAGE_MAX_CONCURRENT = 4   # parallel Fal.ai requests (raise to 5 with paid credits)


# ─────────────────────────────────────────────────────────────────────────────
#  FORMAT PROFILES  (derived from VIDEO_FORMAT above — do not edit)
# ─────────────────────────────────────────────────────────────────────────────

_FORMATS = {
    "short": {
        "video_width":     1080,
        "video_height":    1920,
        "aspect_ratio":    "9:16",
        "fal_image_size":  "portrait_16_9",    # Fal.ai enum → 1080×1920
        "thumb_width":     1280,
        "thumb_height":    720,
        "is_shorts":       True,
        "label":           "YouTube Shorts / TikTok / Reels  (9:16 · 1080×1920)",
    },
    "long": {
        "video_width":     1920,
        "video_height":    1080,
        "aspect_ratio":    "16:9",
        "fal_image_size":  "landscape_16_9",   # Fal.ai enum → 1920×1080
        "thumb_width":     1280,
        "thumb_height":    720,
        "is_shorts":       False,
        "label":           "Standard YouTube  (16:9 · 1920×1080)",
    },
}

if VIDEO_FORMAT not in _FORMATS:
    print(f"❌  Unknown VIDEO_FORMAT: {VIDEO_FORMAT!r}. Choose 'short' or 'long'.")
    sys.exit(1)

_fmt = _FORMATS[VIDEO_FORMAT]


# ─────────────────────────────────────────────────────────────────────────────
#  APPLY FORMAT TO CONFIG  ← must happen before importing any pipeline module
# ─────────────────────────────────────────────────────────────────────────────

import config  # noqa: E402

config.VIDEO_WIDTH        = _fmt["video_width"]
config.VIDEO_HEIGHT       = _fmt["video_height"]
config.VIDEO_ASPECT_RATIO = _fmt["aspect_ratio"]
config.FAL_IMAGE_SIZE     = _fmt["fal_image_size"]
config.THUMB_WIDTH        = _fmt["thumb_width"]
config.THUMB_HEIGHT       = _fmt["thumb_height"]


# ─────────────────────────────────────────────────────────────────────────────
#  WINDOWS FFMPEG PATH FIX  (must run before importing video_renderer)
# ─────────────────────────────────────────────────────────────────────────────

import glob
import os
import shutil

def _ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return
    patterns = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet",
                     "Packages", "*ffmpeg*", "**", "ffmpeg.exe"),
        r"C:\Program Files\ffmpeg*\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for pat in patterns:
        matches = glob.glob(pat, recursive=True)
        if matches:
            bin_dir = str(Path(matches[0]).parent)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return

_ensure_ffmpeg()


# ─────────────────────────────────────────────────────────────────────────────
#  PIPELINE IMPORTS  (after config is patched so module-level constants are right)
# ─────────────────────────────────────────────────────────────────────────────

from pipeline.story_generator     import StoryGenerator, print_script_summary
from pipeline.scene_refiner       import SceneRefiner, print_refined_summary
from pipeline.image_generator     import ImageGenerator
from pipeline.voice_generator     import VoiceGenerator
from pipeline.music_handler       import MusicHandler
from pipeline.video_renderer      import VideoRenderer
from pipeline.subtitle_generator  import SubtitleGenerator
from pipeline.thumbnail_generator import ThumbnailGenerator, build_short_title


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_STAGE_RESULTS: dict[str, str] = {}   # stage_label → "ok" | "skip" | "fail"

def _banner():
    print("\n" + "═" * 62)
    print("   🎬  AI Kids Video Pipeline")
    print("═" * 62)
    print(f"   Topic    : {TOPIC}")
    print(f"   Format   : {_fmt['label']}")
    print(f"   Slug     : {LOAD_EXISTING_SLUG or '(will be generated)'}")
    print(f"   Upload   : {'Yes — ' + YOUTUBE_PRIVACY if UPLOAD_TO_YOUTUBE else 'No'}")
    print("═" * 62)

def _section(label: str):
    pad = (58 - len(label) - 2) // 2
    print(f"\n{'─' * pad} {label} {'─' * pad}")

def _mark(label: str, status: str):
    _STAGE_RESULTS[label] = status

def _summary():
    _section("PIPELINE SUMMARY")
    icons = {"ok": "✅", "skip": "⏭ ", "fail": "❌"}
    for label, status in _STAGE_RESULTS.items():
        print(f"  {icons.get(status, '?')}  {label}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 1 — Story Generation
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_1() -> object:
    """Generate story script with Claude. Returns VideoScript."""
    label = "Stage 1 — Story Generation"

    if not RUN_STAGE_1_STORY and not LOAD_EXISTING_SLUG:
        print(f"\n  ⚠️  RUN_STAGE_1_STORY=False but no LOAD_EXISTING_SLUG set.")
        print("      Set LOAD_EXISTING_SLUG to resume from a saved story.")
        sys.exit(1)

    if not RUN_STAGE_1_STORY or LOAD_EXISTING_SLUG:
        slug = LOAD_EXISTING_SLUG
        print(f"\n  ⏭   Stage 1 — loading saved script: {slug}")
        script = StoryGenerator.load_script(slug)
        _mark(label, "skip")
        return script

    gen    = StoryGenerator()
    script = gen.generate(topic=TOPIC, category=CATEGORY, save=True)
    print_script_summary(script)
    _mark(label, "ok")
    return script


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 2 — Scene Refinement
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_2(script) -> object:
    """Refine prompts & add negative prompts with Claude. Returns RefinedScript."""
    label = "Stage 2 — Scene Refinement"

    if not RUN_STAGE_2_REFINE or LOAD_EXISTING_SLUG:
        slug = LOAD_EXISTING_SLUG or script.slug
        try:
            refined = SceneRefiner.load_refined(slug)
            print(f"\n  ⏭   Stage 2 — loading saved refined script: {slug}")
            _mark(label, "skip")
            return refined
        except FileNotFoundError:
            pass   # not saved yet — fall through to generate

    refiner = SceneRefiner()
    refined = refiner.refine(script, save=True)
    print_refined_summary(refined)
    _mark(label, "ok")
    return refined


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 3 — Image Generation
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_3(refined) -> list[dict]:
    """Generate scene images with Fal.ai Flux. Returns results list."""
    label = "Stage 3 — Image Generation"

    out_dir = Path(config.RAW_DIR) / refined.slug
    if not RUN_STAGE_3_IMAGES and out_dir.exists():
        print(f"\n  ⏭   Stage 3 — images already exist, skipping")
        _mark(label, "skip")
        return ImageGenerator.load_manifest(refined.slug)["scenes"]

    print(f"\n  Image resolution : {config.FAL_IMAGE_SIZE}  "
          f"({config.VIDEO_WIDTH}×{config.VIDEO_HEIGHT})")

    gen     = ImageGenerator(max_concurrent=IMAGE_MAX_CONCURRENT)
    results = gen.generate(refined)

    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        print(f"\n  ❌  {len(failed)} images failed: scenes {[r['scene_number'] for r in failed]}")
        _mark(label, "fail")
    else:
        _mark(label, "ok")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 4 — Voice Generation
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_4(refined) -> list[dict]:
    """Generate narration audio with ElevenLabs. Returns results list."""
    label = "Stage 4 — Voice Generation"

    out_dir = Path(config.AUDIO_DIR) / refined.slug
    if not RUN_STAGE_4_VOICE and (out_dir / "full_narration.mp3").exists():
        print(f"\n  ⏭   Stage 4 — audio already exists, skipping")
        _mark(label, "skip")
        return []

    gen     = VoiceGenerator(use_fast_model=USE_FAST_VOICE)
    results = gen.generate(refined)

    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        print(f"\n  ❌  {len(failed)} voice clips failed")
        _mark(label, "fail")
    else:
        _mark(label, "ok")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 5 — Background Music
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_5(refined) -> Path | None:
    """Download & mix background music. Returns final mix Path."""
    label = "Stage 5 — Background Music"

    mix_path = Path(config.AUDIO_DIR) / refined.slug / "final_mix.mp3"
    if not RUN_STAGE_5_MUSIC and mix_path.exists():
        print(f"\n  ⏭   Stage 5 — music mix already exists, skipping")
        _mark(label, "skip")
        return mix_path

    handler  = MusicHandler()
    mix_path = handler.create_mix(refined)

    if mix_path and mix_path.exists():
        _mark(label, "ok")
    else:
        print("\n  ⚠️  Stage 5 — music mix failed, continuing without music")
        _mark(label, "fail")
    return mix_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 6 — Video Render
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_6(refined) -> Path:
    """Render final video with FFmpeg. Returns final MP4 Path."""
    label = "Stage 6 — Video Render"

    final_path = Path(config.FINAL_DIR) / refined.slug / f"{refined.slug}_final.mp4"
    if not RUN_STAGE_6_VIDEO and final_path.exists():
        print(f"\n  ⏭   Stage 6 — final video already exists, skipping")
        _mark(label, "skip")
        return final_path

    print(f"\n  Output resolution : {config.VIDEO_WIDTH}×{config.VIDEO_HEIGHT}  "
          f"({config.VIDEO_ASPECT_RATIO})")

    renderer   = VideoRenderer()
    final_path = renderer.render(refined, burn_subtitles=True)

    if final_path.exists():
        _mark(label, "ok")
    else:
        print("\n  ❌  Stage 6 — video render failed")
        _mark(label, "fail")
    return final_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 7 — Subtitle Export
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_7(refined) -> tuple[Path, Path] | tuple[None, None]:
    """Export SRT + ASS subtitle files. Returns (srt_path, ass_path)."""
    label = "Stage 7 — Subtitle Export"

    srt_path = Path(config.SUBTITLES_DIR) / refined.slug / f"{refined.slug}.srt"
    if not RUN_STAGE_7_SUBTITLES and srt_path.exists():
        print(f"\n  ⏭   Stage 7 — subtitles already exist, skipping")
        _mark(label, "skip")
        return srt_path, srt_path.with_suffix(".ass")

    gen = SubtitleGenerator()
    try:
        srt_path, ass_path = gen.generate(refined)
        _mark(label, "ok")
        return srt_path, ass_path
    except Exception as e:
        print(f"\n  ⚠️  Stage 7 failed: {e}")
        _mark(label, "fail")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 8 — Thumbnail Generation
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_8(refined) -> dict:
    """Generate YouTube thumbnail images. Returns dict of paths."""
    label = "Stage 8 — Thumbnail"

    out_dir = Path(config.THUMBS_DIR) / refined.slug
    manifest = out_dir / "thumbnail_manifest.json"
    if not RUN_STAGE_8_THUMBNAIL and manifest.exists():
        print(f"\n  ⏭   Stage 8 — thumbnail already exists, skipping")
        _mark(label, "skip")
        return {}

    gen     = ThumbnailGenerator()
    results = gen.generate(refined)

    if results:
        _mark(label, "ok")
    else:
        print("\n  ❌  Stage 8 — thumbnail generation failed")
        _mark(label, "fail")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 9 — YouTube Upload  (only runs if UPLOAD_TO_YOUTUBE = True)
# ─────────────────────────────────────────────────────────────────────────────

def run_stage_9(refined) -> dict | None:
    """Upload video to YouTube. Returns upload result dict or None."""
    label = "Stage 9 — YouTube Upload"

    if not UPLOAD_TO_YOUTUBE:
        print(f"\n  ⏭   Stage 9 — UPLOAD_TO_YOUTUBE=False, skipping")
        _mark(label, "skip")
        return None

    from pipeline.youtube_uploader import YouTubeUploader

    uploader = YouTubeUploader()
    try:
        result = uploader.upload(
            refined,
            privacy=YOUTUBE_PRIVACY,
            is_shorts=_fmt["is_shorts"],
        )
        _mark(label, "ok")
        return result
    except FileNotFoundError as e:
        print(f"\n  ❌  Stage 9 — {e}")
        _mark(label, "fail")
        return None
    except Exception as e:
        print(f"\n  ❌  Stage 9 — upload failed: {e}")
        _mark(label, "fail")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN — run all stages in order
# ─────────────────────────────────────────────────────────────────────────────

def main():
    t_total = time.time()
    _banner()

    # ── Stage 1: Story ────────────────────────────────────────────────────────
    script = run_stage_1()
    slug   = script.slug
    print(f"\n  Slug: {slug}")

    # ── Stage 2: Refinement ───────────────────────────────────────────────────
    refined = run_stage_2(script)

    # ── Stage 3: Images ───────────────────────────────────────────────────────
    run_stage_3(refined)

    # ── Stage 4: Voice ────────────────────────────────────────────────────────
    run_stage_4(refined)

    # ── Stage 5: Music ────────────────────────────────────────────────────────
    run_stage_5(refined)

    # ── Stage 6: Video ────────────────────────────────────────────────────────
    final_path = run_stage_6(refined)

    # ── Stage 7: Subtitles ────────────────────────────────────────────────────
    srt_path, _ = run_stage_7(refined)

    # ── Stage 8: Thumbnail ────────────────────────────────────────────────────
    thumb_results = run_stage_8(refined)

    # ── Stage 9: YouTube Upload ───────────────────────────────────────────────
    upload_result = run_stage_9(refined)

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = round(time.time() - t_total, 1)
    _summary()

    print("═" * 62)
    print("   DONE")
    print("═" * 62)
    print(f"   Title    : {refined.title}")
    print(f"   Format   : {_fmt['label']}")
    print(f"   Duration : {elapsed}s total pipeline time")
    print()

    if final_path and Path(final_path).exists():
        size_mb = round(Path(final_path).stat().st_size / 1024 / 1024, 1)
        print(f"   Video    : {final_path}  ({size_mb} MB)")

    if srt_path and Path(srt_path).exists():
        print(f"   SRT      : {srt_path}  (upload to YouTube Studio for captions)")

    if thumb_results:
        upload_thumb = (
            thumb_results.get("landscape_text")
            or thumb_results.get("landscape")
        )
        if upload_thumb:
            print(f"   Thumbnail: {upload_thumb}")

    if upload_result:
        print()
        print(f"   YouTube  : {upload_result['video_url']}")
        print(f"   Shorts   : {upload_result['shorts_url']}")
        print(f"   Privacy  : {upload_result['privacy']}")
        if upload_result["privacy"] == "private":
            print(f"   Studio   : https://studio.youtube.com/video/{upload_result['video_id']}/edit")
    elif UPLOAD_TO_YOUTUBE:
        print()
        print("   ⚠️  Upload failed — check errors above")
    else:
        print()
        print("   Set UPLOAD_TO_YOUTUBE = True to publish automatically.")

    print("═" * 62)


if __name__ == "__main__":
    main()
