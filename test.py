"""
test_pipeline.py — AI Kids Video Generator — Pipeline Test Runner
=================================================================
Run this file to test any stage of the pipeline.
Set TEST_STAGE and LOAD_EXISTING_SLUG below, then run.

STAGES — run in this order:
    1  = Story generation      (Claude → story JSON)
    2  = Scene refinement      (Claude → enhanced prompts + negative prompts)
    3  = Image generation      (Fal.ai Flux → 12 PNG images)
    4  = Voice generation      (ElevenLabs → 12 MP3 clips + full narration)
    5  = Background music      (music download + narration mix)
    6  = Video render          (FFmpeg → final 9:16 MP4 with burned subtitles)
    7  = SRT subtitle export   (run AFTER Stage 6 — uses exact video timings)
    8  = Thumbnail generation  (Fal.ai Flux → YouTube thumbnail)

IMPORTANT: Run Stage 7 AFTER Stage 8 so subtitle timing matches the video exactly.
"""

import json
import os
import sys
from pathlib import Path

# ── Windows FFmpeg PATH fix ───────────────────────────────────────────────────
_FFMPEG_BIN = (
    r"C:\Users\omidg\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin"
)
if _FFMPEG_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_BIN + os.pathsep + os.environ.get("PATH", "")

# ── Project root on path ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────────────────────
#  ✏️  EDIT THESE TO CONTROL YOUR TEST
# ─────────────────────────────────────────────────────────────────────────────

TEST_STAGE         = 8                             # Stage to run (1-9)
TEST_TOPIC         = "titanic story for kids"
TEST_CATEGORY      = None                           # None = auto, or set a category
LOAD_EXISTING_SLUG = "timmys-big-ship-adventure"      # Set to reuse saved outputs
PRINT_JSON         = False                          # True = print raw JSON
SAVE_OUTPUT        = True

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def separator(title: str = "", width: int = 60):
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


def header():
    print("\n" + "═" * 60)
    print("   🎬  AI Kids Video Generator — Pipeline Test Runner")
    print("═" * 60)
    print(f"   Stage    : {TEST_STAGE}")
    print(f"   Topic    : {TEST_TOPIC}")
    print(f"   Load slug: {LOAD_EXISTING_SLUG or 'none (generate fresh)'}")
    print("═" * 60)


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 1 — Story Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_1():
    separator("STAGE 1 — Story Generation")
    from pipeline.story_generator import StoryGenerator, print_script_summary

    gen = StoryGenerator()
    if LOAD_EXISTING_SLUG:
        print(f"  Loading saved script: {LOAD_EXISTING_SLUG}")
        script = StoryGenerator.load_script(LOAD_EXISTING_SLUG)
    else:
        script = gen.generate(topic=TEST_TOPIC, category=TEST_CATEGORY, save=SAVE_OUTPUT)

    print_script_summary(script)

    if PRINT_JSON:
        separator("RAW JSON")
        print(script.model_dump_json(indent=2))

    separator("VALIDATION")
    checks = [
        ("Title present",                bool(script.title)),
        ("Slug is URL-safe",             script.slug.replace("-","").isalnum()),
        ("Exactly 12 scenes",            len(script.scenes) == 12),
        ("All scenes have narration",    all(s.narration for s in script.scenes)),
        ("All scenes have image_prompt", all(s.image_prompt for s in script.scenes)),
        ("Duration 50-70 seconds",       50 <= script.total_duration_seconds <= 70),
        ("Has YouTube tags",             len(script.youtube_tags) >= 5),
        ("Has moral",                    bool(script.moral)),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")

    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return script


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 2 — Scene Refinement
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_2():
    separator("STAGE 2 — Scene Refinement")
    from pipeline.story_generator import StoryGenerator
    from pipeline.scene_refiner import SceneRefiner, print_refined_summary

    if not LOAD_EXISTING_SLUG:
        print("  No LOAD_EXISTING_SLUG set — generating Stage 1 first...")
        gen = StoryGenerator()
        script = gen.generate(topic=TEST_TOPIC, category=TEST_CATEGORY, save=SAVE_OUTPUT)
    else:
        print(f"  Loading Stage 1 script: {LOAD_EXISTING_SLUG}")
        script = StoryGenerator.load_script(LOAD_EXISTING_SLUG)

    refiner = SceneRefiner()
    refined = refiner.refine(script, save=SAVE_OUTPUT)

    if not PRINT_JSON:
        print_refined_summary(refined)
    else:
        print(refined.model_dump_json(indent=2))

    separator("VALIDATION")
    import re
    hex_re = re.compile(r'^#[0-9A-Fa-f]{6}$')
    checks = [
        ("Title preserved",            refined.title == script.title),
        ("12 refined scenes",          len(refined.scenes) == 12),
        ("Global style suffix set",    bool(refined.global_style_suffix)),
        ("Global negative prompt set", bool(refined.global_negative_prompt)),
        ("All narrations preserved",   all(rs.narration == os.narration for rs, os in zip(refined.scenes, script.scenes))),
        ("All have negative_prompt",   all(bool(s.negative_prompt) for s in refined.scenes)),
        ("All have colour_palette",    all(len(s.colour_palette) == 3 for s in refined.scenes)),
        ("All palette colours valid",  all(all(hex_re.match(c) for c in s.colour_palette) for s in refined.scenes)),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")
    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return refined


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 3 — Image Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_3():
    separator("STAGE 3 — Image Generation (Fal.ai Flux)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.image_generator import ImageGenerator
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        return

    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded: {refined.title}")

    gen = ImageGenerator(max_concurrent=4)
    results = gen.generate(refined)

    separator("VALIDATION")
    out_dir    = Path(config.RAW_DIR) / refined.slug
    successful = [r for r in results if r["status"] == "success"]
    failed     = [r for r in results if r["status"] == "failed"]

    checks = [
        ("All 12 images attempted",  len(results) == 12),
        ("All 12 succeeded",         len(successful) == 12),
        ("Output folder exists",     out_dir.exists()),
        ("Manifest saved",           (out_dir / "manifest.json").exists()),
        ("All PNG files exist",      all(Path(r["file"]).exists() for r in successful)),
        ("All files > 50KB",         all(r.get("size_kb", 0) > 50 for r in successful)),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")
    if failed:
        separator("FAILED SCENES")
        for r in failed:
            print(f"  Scene {r['scene_number']:02d}: {r.get('error','')[:80]}")
    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 4 — Voice Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_4():
    separator("STAGE 4 — Voice Generation (ElevenLabs)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.voice_generator import VoiceGenerator
    import config as cfg

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        return

    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded: {refined.title}")

    # Show voice plan
    separator("VOICE PLAN")
    icons = {"happy":"😊","excited":"🤩","sad":"😢","scared":"😨","surprised":"😲","curious":"🤔","proud":"😤","calm":"😌","magical":"✨","funny":"😄"}
    for scene in refined.scenes:
        vid = cfg.VOICE_EMOTION_MAP.get(scene.emotion, cfg.VOICE_DEFAULT)
        label = "warm" if vid == cfg.VOICE_WARM_NARRATOR else "energetic" if vid == cfg.VOICE_ENERGETIC else "character"
        print(f"  Scene {scene.scene_number:02d}  {icons.get(scene.emotion,'🎬')}  [{scene.emotion:10s}]  → {label}")

    separator("GENERATING")
    gen     = VoiceGenerator()
    results = gen.generate(refined)

    separator("VALIDATION")
    out_dir    = Path(config.AUDIO_DIR) / refined.slug
    successful = [r for r in results if r["status"] == "success"]

    checks = [
        ("All 12 scenes attempted",   len(results) == 12),
        ("All 12 succeeded",          len(successful) == 12),
        ("Full narration saved",      (out_dir / "full_narration.mp3").exists()),
        ("Full narration > 10KB",     (out_dir / "full_narration.mp3").stat().st_size > 10_000
                                      if (out_dir / "full_narration.mp3").exists() else False),
        ("All MP3 files exist",       all(Path(r["file"]).exists() for r in successful)),
        ("All files > 2KB",           all(r.get("size_kb", 0) > 2 for r in successful)),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")
    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 5 — Background Music
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_5():
    separator("STAGE 5 — Background Music (Pixabay)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.music_handler import MusicHandler
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        return

    refined   = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded : {refined.title}")
    print(f"  Mood   : {refined.background_music_mood}")

    handler   = MusicHandler()
    mix_path  = handler.create_mix(refined)

    separator("VALIDATION")
    checks = [
        ("Music downloaded",        bool(mix_path)),
        ("Final mix file exists",   mix_path.exists() if mix_path else False),
        ("Final mix > 100KB",       mix_path.stat().st_size > 100_000 if mix_path and mix_path.exists() else False),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")
    if mix_path:
        print(f"\n  Output: {mix_path}")
    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return mix_path

# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 7 — Video Render
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_6():
    separator("STAGE 6 — Video Render (FFmpeg)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.video_renderer import VideoRenderer
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        return

    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded: {refined.title}")

    renderer   = VideoRenderer()
    final_path = renderer.render(refined, burn_subtitles=True)

    separator("VALIDATION")
    final    = Path(final_path)
    size_mb  = round(final.stat().st_size / 1024 / 1024, 2) if final.exists() else 0
    manifest = VideoRenderer.load_manifest(LOAD_EXISTING_SLUG)

    checks = [
        ("Final MP4 exists",       final.exists()),
        ("File size > 5MB",        size_mb > 5),
        ("File size < 500MB",      size_mb < 500),
        ("Duration > 30s",         manifest.get("total_duration", 0) > 30),
        ("Resolution correct",     manifest.get("resolution") == f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}"),
        ("All 12 scenes rendered", len(manifest.get("scenes", [])) == 12),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")

    separator("SCENE TIMING")
    total = 0
    for s in manifest.get("scenes", []):
        bar = "█" * int(s["duration"] * 1.5)
        print(f"  Scene {s['scene_number']:02d}  {s['duration']:5.1f}s  {bar}  {s['on_screen_text']}")
        total += s["duration"]
    print(f"  {'─'*40}")
    print(f"  Total: {total:.1f}s  |  {size_mb}MB")

    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    print(f"  Video : {final_path}")
    return final_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 7 — Subtitle Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_7():
    separator("STAGE 7 — SRT Subtitle Export (run AFTER Stage 6)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.subtitle_generator import SubtitleGenerator
    from pipeline.video_renderer import VideoRenderer
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        return

    # Warn if render manifest missing
    try:
        VideoRenderer.load_manifest(LOAD_EXISTING_SLUG)
        print(f"  Render manifest : found ✓ (exact video timings)")
    except FileNotFoundError:
        print(f"  ⚠️  Render manifest not found — run Stage 6 first!")
        print(f"  Subtitle timing will be approximate.")


    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded : {refined.title}")
    print(f"  Mode   : script-based (free — no extra API needed)")
    print()

    gen = SubtitleGenerator()
    srt_path, ass_path = gen.generate(refined)

    separator("VALIDATION")
    checks = [
        ("SRT file created",       srt_path.exists()),
        ("ASS file created",       ass_path.exists()),
        ("SRT has content",        srt_path.stat().st_size > 100 if srt_path.exists() else False),
        ("ASS has content",        ass_path.stat().st_size > 100 if ass_path.exists() else False),
        ("ASS has Kids style",     "Style: Kids" in ass_path.read_text() if ass_path.exists() else False),
        ("SRT has timestamps",     "-->" in srt_path.read_text() if srt_path.exists() else False),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")

    separator("SRT PREVIEW (first 3 entries)")
    if srt_path.exists():
        lines = srt_path.read_text().split("\n")[:15]
        for line in lines:
            print(f"  {line}")

    separator()
    print(f"  Result  : {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    print(f"  SRT     : {srt_path}")
    print(f"  ASS     : {ass_path}")
    print(f"  Upload the .SRT file to YouTube Studio for auto-captions!")
    return srt_path, ass_path


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 8 — Thumbnail (stub — coming soon)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_8():
    separator("STAGE 9 — Thumbnail Generation (Fal.ai Flux)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.thumbnail_generator import ThumbnailGenerator
    from pathlib import Path
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        separator();
        return

    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)
    print(f"  Loaded : {refined.title}")
    print(f"  Cost   : ~$0.08 (2 thumbnails × $0.04)")
    print()

    gen = ThumbnailGenerator()
    results = gen.generate(refined)

    separator("VALIDATION")
    out_dir = Path(config.THUMBS_DIR) / refined.slug
    checks = [
        ("Landscape thumbnail (YouTube)", "landscape" in results and results["landscape"].exists()),
        ("Portrait thumbnail (Shorts)", "portrait" in results and results["portrait"].exists()),
        ("Landscape > 100KB", results.get("landscape") and results["landscape"].stat().st_size > 100_000),
        ("Portrait > 100KB", results.get("portrait") and results["portrait"].stat().st_size > 100_000),
        ("Manifest saved", (out_dir / "thumbnail_manifest.json").exists()),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")

    if results.get("landscape"):
        print(f"\n  YouTube  : {results['landscape']}")
    if results.get("portrait"):
        print(f"  Shorts   : {results['portrait']}")

    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 9 — Thumbnail (stub — coming soon)
# ─────────────────────────────────────────────────────────────────────────────

def test_stage_9():
    separator("STAGE 9 — Thumbnail Generation (Fal.ai Flux)")
    from pipeline.scene_refiner import SceneRefiner
    from pipeline.thumbnail_generator import ThumbnailGenerator, build_short_title
    from pathlib import Path
    import config

    if not LOAD_EXISTING_SLUG:
        print("  Set LOAD_EXISTING_SLUG and re-run.")
        separator();
        return

    refined = SceneRefiner.load_refined(LOAD_EXISTING_SLUG)

    # Auto-generate title — no manual input needed
    auto_title = build_short_title(refined.title)

    print(f"  Story   : {refined.title}")
    print(f"  Title   : {repr(auto_title)}  (auto-generated)")
    print(f"  Cost    : ~$0.08 (2 thumbnails × $0.04)")
    print()

    gen = ThumbnailGenerator()
    results = gen.generate(refined)

    separator("VALIDATION")
    out_dir = Path(config.THUMBS_DIR) / refined.slug
    checks = [
        ("Landscape raw generated", "landscape" in results and Path(results["landscape"]).exists()),
        ("Portrait raw generated", "portrait" in results and Path(results["portrait"]).exists()),
        ("Landscape with text generated", "landscape_text" in results and Path(results["landscape_text"]).exists()),
        ("Portrait with text generated", "portrait_text" in results and Path(results["portrait_text"]).exists()),
        ("Landscape > 100KB", "landscape" in results and Path(results["landscape"]).stat().st_size > 100_000),
        ("Portrait > 100KB", "portrait" in results and Path(results["portrait"]).stat().st_size > 100_000),
        ("Manifest saved", (out_dir / "thumbnail_manifest.json").exists()),
    ]
    passed = sum(1 for _, r in checks if r)
    for label, result in checks:
        print(f"  {'✅' if result else '❌'}  {label}")

    separator("OUTPUT FILES")
    labels = {
        "landscape": "YouTube 16:9 (no text) ",
        "portrait": "Shorts  9:16 (no text) ",
        "landscape_text": "YouTube 16:9 ✅ UPLOAD ",
        "portrait_text": "Shorts  9:16 ✅ UPLOAD ",
    }
    for key, path in results.items():
        label = labels.get(key, key)
        print(f"  {label}: {Path(path).name}")

    separator()
    print(f"  Result: {'PASSED' if passed == len(checks) else f'PARTIAL ({passed}/{len(checks)})'}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  DISPATCH
# ─────────────────────────────────────────────────────────────────────────────

STAGES = {
    1: test_stage_1,
    2: test_stage_2,
    3: test_stage_3,
    4: test_stage_4,
    5: test_stage_5,
    6: test_stage_6,
    7: test_stage_7,    # Run AFTER Stage 8 for exact subtitle sync
    8: test_stage_8,
}

import config  # noqa — needed for audio dir path in stage 4

if __name__ == "__main__":
    header()

    if TEST_STAGE not in STAGES:
        print(f"\n  ❌  Invalid TEST_STAGE: {TEST_STAGE}. Choose from: {sorted(STAGES.keys())}")
        sys.exit(1)

    try:
        result = STAGES[TEST_STAGE]()
    except EnvironmentError as e:
        print(f"\n  ❌  Environment error: {e}")
        print("  Check your .env file has all required API keys.")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"\n  ❌  File not found: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌  Unexpected error in Stage {TEST_STAGE}: {e}")
        raise