"""
subtitle_generator.py — Stage 7: Subtitle Generation

Generates two subtitle outputs from the narration audio:

1. .SRT file — standard subtitle format for YouTube CC system
   → Upload alongside your video for YouTube auto-captions + SEO

2. .ASS file — Advanced SubStation Alpha format with kids-style styling
   → Burned into the video by Stage 8 (big, bold, colourful)

Mode: script-based (free) — uses narration text + audio timing from voice manifest.
No external API needed beyond what's already in the pipeline.

Output:
    output/subtitles/<slug>/<slug>.srt   (for YouTube upload)
    output/subtitles/<slug>/<slug>.ass   (for Stage 8 burn-in)
    output/subtitles/<slug>/subtitle_manifest.json
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript


# ─────────────────────────────────────────────────────────────────────────────
#  ASS SUBTITLE STYLE  (kids-friendly: big, bold, colourful)
# ─────────────────────────────────────────────────────────────────────────────

ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Kids,Arial Rounded MT Bold,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Colour cycling for on_screen_text — keeps kids engaged
SUBTITLE_COLOURS = [
    "&H0000FFFF",  # Yellow
    "&H0000FF00",  # Lime
    "&H00FF6600",  # Orange
    "&H00FF00FF",  # Magenta
    "&H0066FFFF",  # Cyan
]


def seconds_to_ass(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.cc"""
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def seconds_to_srt(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm"""
    h   = int(seconds // 3600)
    m   = int((seconds % 3600) // 60)
    s   = int(seconds % 60)
    ms  = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─────────────────────────────────────────────────────────────────────────────
#  SUBTITLE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class SubtitleGenerator:
    """
    Generates SRT and ASS subtitle files from narration audio.

    Two strategies depending on available APIs:

    Strategy A — Whisper API (accurate word-level timestamps):
      Uses narration text + audio duration per scene from voice manifest
      → builds subtitle blocks from on_screen_text and narration
      Free, accurate enough for YouTube SEO and burn-in

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.voice_generator import VoiceGenerator
        from pipeline.subtitle_generator import SubtitleGenerator

        refined = SceneRefiner.load_refined("sparks-big-brave-moment")
        gen = SubtitleGenerator()
        srt_path, ass_path = gen.generate(refined)
    """

    def __init__(self):
        # No external API needed — uses narration text + audio timing
        pass

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.SUBTITLES_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _get_scene_timings(self, slug: str, refined: RefinedScript) -> list[dict]:
        """
        Get scene start/end times from the render manifest (most accurate)
        or fall back to voice manifest audio durations.

        Priority:
          1. Render manifest (output/final/<slug>/render_manifest.json)
             — exact FFmpeg-rendered durations, perfectly in sync with video
          2. Voice manifest (output/audio/<slug>/voice_manifest.json)
             — actual audio clip durations, close but may drift
          3. Fixed 5s per scene — last resort fallback
        """
        # Priority 1: Render manifest — exact video timings
        render_manifest_path = Path(config.FINAL_DIR) / slug / "render_manifest.json"
        if render_manifest_path.exists():
            render_manifest = json.loads(render_manifest_path.read_text())
            timings = []
            current_t = 0.0
            scene_map = {s["scene_number"]: s for s in render_manifest.get("scenes", [])}
            for scene in refined.scenes:
                n        = scene.scene_number
                duration = scene_map.get(n, {}).get("duration", 5.0)
                timings.append({
                    "scene_number":   n,
                    "start":          round(current_t, 3),
                    "end":            round(current_t + duration, 3),
                    "duration":       duration,
                    "narration":      scene.narration,
                    "on_screen_text": scene.on_screen_text,
                })
                current_t += duration
            print(f"  Timing   : from render manifest (exact video sync) ✓")
            return timings

        # Priority 2: Voice manifest — actual audio durations
        voice_manifest_path = Path(config.AUDIO_DIR) / slug / "voice_manifest.json"
        scene_durations = {}
        if voice_manifest_path.exists():
            manifest = json.loads(voice_manifest_path.read_text())
            for s in manifest.get("scenes", []):
                if s["status"] == "success":
                    scene_durations[s["scene_number"]] = s.get("estimated_audio_duration", 5.0)
            print(f"  Timing   : from voice manifest (run Stage 8 first for exact sync)")
        else:
            print(f"  Timing   : fixed 5s per scene (fallback)")

        timings = []
        current_t = 0.0
        for scene in refined.scenes:
            n        = scene.scene_number
            duration = scene_durations.get(n, 5.0)
            timings.append({
                "scene_number":   n,
                "start":          round(current_t, 3),
                "end":            round(current_t + duration, 3),
                "duration":       duration,
                "narration":      scene.narration,
                "on_screen_text": scene.on_screen_text,
            })
            current_t += duration

        return timings

    # ── Subtitle generation: Script-based (free fallback) ──────────────────────────────

    def _timings_to_srt(self, timings: list[dict]) -> str:
        """Convert scene timings to SRT using full narration text."""
        lines = []
        for i, t in enumerate(timings, 1):
            lines.append(str(i))
            lines.append(f"{seconds_to_srt(t['start'])} --> {seconds_to_srt(t['end'])}")
            # Break narration into shorter lines for readability
            words    = t["narration"].split()
            midpoint = len(words) // 2
            if len(words) > 6 and midpoint > 0:
                line1 = " ".join(words[:midpoint])
                line2 = " ".join(words[midpoint:])
                lines.append(f"{line1}\n{line2}")
            else:
                lines.append(t["narration"])
            lines.append("")
        return "\n".join(lines)

    def _timings_to_ass(self, timings: list[dict]) -> str:
        """
        Convert scene timings to ASS using on_screen_text.
        on_screen_text is the punchy 1-4 word subtitle per scene.
        This is what gets burned into the video as the big bold text.
        """
        lines = [ASS_HEADER]
        for i, t in enumerate(timings):
            colour = SUBTITLE_COLOURS[i % len(SUBTITLE_COLOURS)]
            # Show on_screen_text for first 60% of scene, then narration for rest
            ost_end = t["start"] + (t["duration"] * 0.6)

            # On-screen text (big, punchy) — first 60% of scene
            lines.append(
                f"Dialogue: 0,{seconds_to_ass(t['start'])},{seconds_to_ass(ost_end)},"
                f"Kids,,0,0,0,,{{\\c{colour}\\fs80}}{t['on_screen_text']}"
            )
            # Narration text (smaller) — remaining 40% of scene
            # Split into two lines if long
            words = t["narration"].split()
            mid   = len(words) // 2
            if len(words) > 6:
                narr_text = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])
            else:
                narr_text = t["narration"]

            lines.append(
                f"Dialogue: 0,{seconds_to_ass(ost_end)},{seconds_to_ass(t['end'])},"
                f"Kids,,0,0,0,,{{\\c&H00FFFFFF&\\fs60}}{narr_text}"
            )

        return "\n".join(lines)

    # ── Main generate ─────────────────────────────────────────────────────────

    def generate(
        self,
        refined: RefinedScript,
    ) -> tuple[Path, Path]:
        """
        Generate SRT and ASS subtitle files.

        Args:
            refined: RefinedScript from Stage 2

        Returns:
            (srt_path, ass_path) tuple
        """
        slug    = refined.slug
        out_dir = self._get_output_dir(slug)

        print(f"\n{'='*60}")
        print(f"  Stage 7: Subtitles — '{refined.title}'")
        print(f"{'='*60}")

        # Get scene timings from voice manifest
        timings = self._get_scene_timings(slug, refined)
        total_dur = timings[-1]["end"] if timings else 0
        print(f"  Scenes   : {len(timings)}")
        print(f"  Duration : ~{total_dur:.1f}s")

        # Free script-based generation — uses narration text + audio timing
        # No external API needed. Timing comes from voice manifest (Stage 4).
        print(f"  Mode     : script-based (free — uses narration + audio timing)")
        srt_content = self._timings_to_srt(timings)
        ass_content = self._timings_to_ass(timings)
        method_used = "script"

        # Save files
        srt_path = out_dir / f"{slug}.srt"
        ass_path = out_dir / f"{slug}.ass"
        srt_path.write_text(srt_content, encoding="utf-8")
        ass_path.write_text(ass_content, encoding="utf-8")

        # Save manifest
        manifest = {
            "slug":        slug,
            "method":      method_used,
            "total_scenes": len(timings),
            "total_duration": round(total_dur, 2),
            "srt_file":    str(srt_path),
            "ass_file":    str(ass_path),
            "cost_usd":    0.0,
        }
        (out_dir / "subtitle_manifest.json").write_text(json.dumps(manifest, indent=2))

        print(f"  Method   : {method_used}")
        print(f"  SRT      : {srt_path}  ({srt_path.stat().st_size // 1024}KB)")
        print(f"  ASS      : {ass_path}  ({ass_path.stat().st_size // 1024}KB)")
        print(f"  Cost     : $0.00")
        print(f"{'─'*60}")
        print()
        print("  ℹ️  Upload the .SRT file to YouTube Studio alongside your video")
        print("     for auto-captions and improved search discoverability.")
        print(f"{'─'*60}")

        return srt_path, ass_path

    @staticmethod
    def load_ass(slug: str) -> Path:
        """Return path to ASS subtitle file — used by Stage 8 renderer."""
        path = Path(config.SUBTITLES_DIR) / slug / f"{slug}.ass"
        if not path.exists():
            raise FileNotFoundError(f"ASS subtitle not found: {path}")
        return path

    @staticmethod
    def load_srt(slug: str) -> Path:
        """Return path to SRT subtitle file — upload to YouTube."""
        path = Path(config.SUBTITLES_DIR) / slug / f"{slug}.srt"
        if not path.exists():
            raise FileNotFoundError(f"SRT subtitle not found: {path}")
        return path