"""
video_renderer.py — Stage 8: Final Video Rendering

Takes the 12 scene images (Stage 3) and 12 narration clips (Stage 4)
and assembles them into a single 9:16 vertical video using FFmpeg.

Each scene:
  - Image is animated with a Ken Burns pan/zoom effect
  - Audio duration drives the scene length (not a fixed 5 seconds)
  - Scenes are concatenated with optional transitions

Final output:
    output/final/<slug>/<slug>_final.mp4    (full video)
    output/final/<slug>/render_manifest.json

FFmpeg is called via subprocess — no extra Python libraries needed.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

# ── Windows FFmpeg PATH fix ───────────────────────────────────────────────────
# If ffmpeg is installed via winget but not on PATH, find it automatically.
def _ensure_ffmpeg_on_path():
    """Add winget FFmpeg bin dir to PATH if ffmpeg isn't already findable."""
    import shutil
    if shutil.which("ffmpeg"):
        return  # already on PATH — nothing to do

    import glob
    local_app = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        # Exact known path for this machine
        "C:\\Users\\omidg\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-8.1.1-full_build\\bin\\ffmpeg.exe",
        # Generic winget pattern (works for other machines)
        f"{local_app}\\Microsoft\\WinGet\\Packages\\*ffmpeg*\\**\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg*\\bin\\ffmpeg.exe",
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            bin_dir = str(Path(matches[0]).parent)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            print(f"  FFmpeg found at: {bin_dir}")
            return

    # Not found — user will get a clear error from _check_ffmpeg()

_ensure_ffmpeg_on_path()
from pipeline.models import RefinedScript


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

WIDTH  = config.VIDEO_WIDTH    # 1080
HEIGHT = config.VIDEO_HEIGHT   # 1920
FPS    = config.VIDEO_FPS      # 30

# Ken Burns zoom — how much to zoom in/out per scene
ZOOM_AMOUNT   = 0.04    # 4% zoom — subtle but visible
ZOOM_DURATION = 5.0     # seconds to complete a full zoom cycle

# Subtitle style burned into video
SUBTITLE_FONT_SIZE = 72
SUBTITLE_COLOR     = "white"
SUBTITLE_OUTLINE   = "black"
SUBTITLE_OUTLINE_W = 3
SUBTITLE_Y_POS     = "(h*0.82)"   # 82% down the screen

# Audio padding between scenes (milliseconds) — tiny gap prevents clicks
SCENE_AUDIO_PAD_MS = 50


# ─────────────────────────────────────────────────────────────────────────────
#  FFMPEG HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def run_ffmpeg(args: list[str], label: str = "") -> bool:
    """
    Run an FFmpeg command. Returns True on success, False on failure.
    Prints the command label and any error output on failure.
    """
    cmd = ["ffmpeg", "-y"] + args  # -y = overwrite output without asking
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            print(f"\n  FFmpeg error in {label}:")
            # Show last 20 lines of stderr (FFmpeg is very verbose)
            lines = result.stderr.strip().split("\n")
            for line in lines[-20:]:
                print(f"    {line}")
            return False
        return True
    except FileNotFoundError:
        print("\n  FFmpeg not found. Install it:")
        print("    Windows : winget install ffmpeg  OR  choco install ffmpeg")
        print("    Mac     : brew install ffmpeg")
        print("    Linux   : sudo apt install ffmpeg")
        return False


def get_audio_duration(audio_path: Path) -> float:
    """Get the exact duration of an audio file using FFprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return float(config.SCENE_DURATION_SEC)  # fallback


def _get_stream_duration(media_path: Path) -> float:
    """
    Get duration of any media file (audio OR video) using FFprobe.
    Used to compare video length vs final_mix.mp3 length before combining.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def get_camera_filter(camera_movement: str, duration: float) -> str:
    """
    Build the FFmpeg zoompan filter string for Ken Burns effect.

    zoompan parameters:
      z  = zoom expression (how much to zoom over time)
      x  = x position of the crop window
      y  = y position of the crop window
      d  = duration in frames
      s  = output size
    """
    d = int(duration * FPS)  # total frames
    z_start = 1.0
    z_end   = 1.0 + ZOOM_AMOUNT

    # All movements start with a slight zoom for polish
    if camera_movement == "slow_zoom_in":
        z_expr = f"'min(zoom+{ZOOM_AMOUNT/d:.6f},{z_end})'"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    elif camera_movement == "slow_zoom_out":
        z_expr = f"'max(zoom-{ZOOM_AMOUNT/d:.6f},{z_start})'"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    elif camera_movement == "pan_right":
        z_expr = f"'{z_start + ZOOM_AMOUNT/2}'"
        x_expr = f"'min(iw*(on/{d})*0.05,iw-iw/zoom)'"
        y_expr = "ih/2-(ih/zoom/2)"

    elif camera_movement == "pan_left":
        z_expr = f"'{z_start + ZOOM_AMOUNT/2}'"
        x_expr = f"'max(iw-iw*(on/{d})*0.05-iw/zoom,0)'"
        y_expr = "ih/2-(ih/zoom/2)"

    elif camera_movement == "pan_up":
        z_expr = f"'{z_start + ZOOM_AMOUNT/2}'"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"'max(ih-ih*(on/{d})*0.05-ih/zoom,0)'"

    elif camera_movement == "pan_down":
        z_expr = f"'{z_start + ZOOM_AMOUNT/2}'"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"'min(ih*(on/{d})*0.05,ih-ih/zoom)'"

    else:  # static — very slight zoom for visual interest
        z_expr = f"'min(zoom+{(ZOOM_AMOUNT*0.5)/d:.6f},{z_start + ZOOM_AMOUNT*0.5})'"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  VIDEO RENDERER
# ─────────────────────────────────────────────────────────────────────────────

class VideoRenderer:
    """
    Assembles the final kids video from scene images and narration audio.

    Pipeline:
      1. Get exact audio duration for each scene from FFprobe
      2. For each scene: animate image with Ken Burns + add audio → scene clip
      3. Concatenate all scene clips into one video
      4. Add subtitle overlays (on_screen_text per scene)
      5. Export final 9:16 MP4

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.video_renderer import VideoRenderer

        refined = SceneRefiner.load_refined("sparks-big-brave-moment")
        renderer = VideoRenderer()
        output = renderer.render(refined)
        print(f"Video saved: {output}")
    """

    def __init__(self):
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """Verify FFmpeg is installed and accessible."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError("FFmpeg returned non-zero exit code")
            version_line = result.stdout.split("\n")[0]
            print(f"  FFmpeg : {version_line}")
        except FileNotFoundError:
            raise EnvironmentError(
                "FFmpeg not found. Install it:\n"
                "  Windows: winget install ffmpeg\n"
                "  Mac    : brew install ffmpeg\n"
                "  Linux  : sudo apt install ffmpeg"
            )

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.FINAL_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _get_scene_files(
        self,
        refined: RefinedScript,
        use_animated: bool = False,
    ) -> list[dict]:
        """
        Build a list of scene file info dicts.
        Uses Stage 3 PNG images + Stage 4 audio clips.
        Audio duration drives scene timing.
        """
        scenes_info = []
        missing = []

        for scene in refined.scenes:
            n          = scene.scene_number
            image_path = Path(config.RAW_DIR)   / refined.slug / f"scene_{n:02d}.png"
            audio_path = Path(config.AUDIO_DIR) / refined.slug / f"scene_{n:02d}.mp3"

            if not image_path.exists():
                missing.append(f"Scene {n:02d}: image missing: {image_path}")
                continue
            if not audio_path.exists():
                missing.append(f"Scene {n:02d}: audio missing: {audio_path}")
                continue

            duration = get_audio_duration(audio_path)
            scenes_info.append({
                "scene_number":    n,
                "video_source":    image_path,
                "source_type":     "static",
                "audio_path":      audio_path,
                "duration":        duration,
                "camera_movement": scene.camera_movement,
                "on_screen_text":  scene.on_screen_text,
                "emotion":         scene.emotion,
            })

        if missing:
            raise FileNotFoundError(
                f"Missing files for render:\n" + "\n".join(f"  {m}" for m in missing)
            )

        print(f"  Using static images : {len(scenes_info)} scenes ✓")
        return scenes_info

    def _render_scene_clip(
        self,
        scene_info: dict,
        output_path: Path,
        tmp_dir: Path,
    ) -> bool:
        """
        Render one scene clip with audio.

        Handles two source types automatically:
          - "animated" : Kling MP4 clip → trim/pad to audio duration + add audio
          - "static"   : PNG image → Ken Burns animation + add audio (fallback)
        """
        n           = scene_info["scene_number"]
        source      = scene_info["video_source"]
        source_type = scene_info["source_type"]
        audio       = scene_info["audio_path"]
        duration    = scene_info["duration"]

        if source_type == "animated":
            # ── Animated clip path ────────────────────────────────────────────
            # Kling clips are 5s. Audio may be longer or shorter.
            # We trim/loop the clip to match audio duration, then merge audio.

            # Step 1: Trim or loop clip to match audio duration
            # If audio > clip: loop the clip. If audio < clip: trim the clip.
            trimmed_path = tmp_dir / f"scene_{n:02d}_trimmed.mp4"

            ok = run_ffmpeg([
                "-stream_loop", "-1",       # loop video indefinitely
                "-i", str(source),
                "-t", str(duration),        # stop at audio duration
                "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
                        f"setsar=1",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-r", str(FPS),
                str(trimmed_path),
            ], label=f"scene {n:02d} clip trim")

            if not ok:
                return False

            # Step 2: Merge trimmed clip with narration audio
            ok = run_ffmpeg([
                "-i", str(trimmed_path),
                "-i", str(audio),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path),
            ], label=f"scene {n:02d} audio merge")

            if trimmed_path.exists():
                trimmed_path.unlink()

            return ok

        else:
            # ── Static image fallback path ────────────────────────────────────
            # Ken Burns pan/zoom animation on PNG image
            movement = scene_info["camera_movement"]
            zoom_filter = get_camera_filter(movement, duration)

            anim_path = tmp_dir / f"scene_{n:02d}_anim.mp4"

            ok = run_ffmpeg([
                "-loop", "1",
                "-i", str(source),
                "-t", str(duration),
                "-vf", f"{zoom_filter},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                       f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
                       f"setsar=1",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", str(FPS),
                str(anim_path),
            ], label=f"scene {n:02d} animation (static fallback)")

            if not ok:
                return False

            ok = run_ffmpeg([
                "-i", str(anim_path),
                "-i", str(audio),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_path),
            ], label=f"scene {n:02d} audio merge")

            if anim_path.exists():
                anim_path.unlink()

            return ok

    def _concatenate_scenes(
        self,
        clip_paths: list[Path],
        output_path: Path,
        tmp_dir: Path,
    ) -> bool:
        """
        Join all scene clips into one video using FFmpeg concat demuxer.
        This is the most reliable concat method — no re-encoding needed.
        """
        # Write concat list file using absolute paths
        # Critical on Windows: must use forward slashes AND absolute paths
        # to avoid path doubling when FFmpeg resolves relative paths
        concat_file = tmp_dir / "concat_list.txt"
        with open(concat_file, "w") as f:
            for clip in clip_paths:
                abs_path = clip.resolve().as_posix()
                f.write(f"file '{abs_path}'\n")

        ok = run_ffmpeg([
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",  # enables streaming/preview in browser
            str(output_path),
        ], label="concatenation")

        return ok

    def _burn_subtitles(
        self,
        input_path: Path,
        output_path: Path,
        scenes_info: list[dict],
    ) -> bool:
        """
        Burn on_screen_text subtitles into the video using FFmpeg drawtext.
        Each subtitle appears for the duration of its scene.

        Uses FFmpeg's drawtext filter with enable='between(t,start,end)'.
        """
        # Build cumulative timestamps
        timestamps = []
        current_t = 0.0
        for info in scenes_info:
            start = current_t
            end   = current_t + info["duration"]
            timestamps.append((start, end, info["on_screen_text"]))
            current_t = end

        # Build chained drawtext filters — one per scene
        filters = []
        for start, end, text in timestamps:
            # Escape special characters for FFmpeg
            safe_text = (
                text
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace("\\", "\\\\")
            )
            filters.append(
                f"drawtext="
                f"text='{safe_text}':"
                f"fontsize={SUBTITLE_FONT_SIZE}:"
                f"fontcolor={SUBTITLE_COLOR}:"
                f"borderw={SUBTITLE_OUTLINE_W}:"
                f"bordercolor={SUBTITLE_OUTLINE}:"
                f"x=(w-text_w)/2:"          # horizontally centered
                f"y={SUBTITLE_Y_POS}:"      # 82% down
                f"enable='between(t,{start:.3f},{end:.3f})'"
            )

        filter_chain = ",".join(filters)

        ok = run_ffmpeg([
            "-i", str(input_path),
            "-vf", filter_chain,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ], label="subtitle burn")

        return ok

    def _save_render_manifest(
        self,
        out_dir: Path,
        refined: RefinedScript,
        scenes_info: list[dict],
        final_path: Path,
        elapsed: float,
    ) -> Path:
        total_duration = sum(s["duration"] for s in scenes_info)
        file_size_mb = round(final_path.stat().st_size / 1024 / 1024, 2)

        manifest = {
            "slug":           refined.slug,
            "title":          refined.title,
            "output_file":    str(final_path),
            "resolution":     f"{WIDTH}x{HEIGHT}",
            "fps":            FPS,
            "total_duration": round(total_duration, 2),
            "file_size_mb":   file_size_mb,
            "render_time_s":  round(elapsed, 1),
            "scenes": [
                {
                    "scene_number":    s["scene_number"],
                    "duration":        round(s["duration"], 2),
                    "camera_movement": s["camera_movement"],
                    "on_screen_text":  s["on_screen_text"],
                }
                for s in scenes_info
            ],
        }

        path = out_dir / "render_manifest.json"
        path.write_text(json.dumps(manifest, indent=2))
        return path

    def render(self, refined: RefinedScript, burn_subtitles: bool = True) -> Path:
        """
        Render the complete video from images + audio.

        Args:
            refined:         RefinedScript from Stage 2
            burn_subtitles:  If True, bake on_screen_text into the video

        Returns:
            Path to the final MP4 file
        """
        print(f"\n{'='*60}")
        print(f"  Stage 8: Video Render — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Resolution  : {WIDTH}x{HEIGHT}  ({config.VIDEO_ASPECT_RATIO})")
        print(f"  FPS         : {FPS}")
        print(f"  Subtitles   : {'yes' if burn_subtitles else 'no'}")
        print()

        out_dir = self._get_output_dir(refined.slug)
        tmp_dir = out_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)

        t_start = time.time()

        # ── Collect scene file info ───────────────────────────────────────────
        print("  Collecting scene files and audio durations...")
        scenes_info = self._get_scene_files(refined)
        total_dur = sum(s["duration"] for s in scenes_info)
        print(f"  Total duration  : ~{total_dur:.1f}s  ({len(scenes_info)} scenes)")
        print()

        # ── Validate audio files before starting ─────────────────────────────
        print("  Validating audio files...")
        for info in scenes_info:
            ap = info["audio_path"]
            size = ap.stat().st_size if ap.exists() else 0
            if size < 1000:  # less than 1KB = corrupt/empty
                print(f"    ⚠️  Scene {info['scene_number']:02d} audio is corrupt ({size}B) — regenerate it")

        # ── Render each scene clip ────────────────────────────────────────────
        print("  Rendering scene clips:")
        clip_paths = []
        failed_scenes = []

        for info in scenes_info:
            n    = info["scene_number"]
            dur  = info["duration"]
            move = info["camera_movement"]
            clip_path = tmp_dir / f"scene_{n:02d}_final.mp4"

            print(
                f"    Scene {n:02d}  [{move:15s}]  {dur:.1f}s  ...",
                end="", flush=True
            )
            t_scene = time.time()
            ok = self._render_scene_clip(info, clip_path, tmp_dir)

            if ok and clip_path.exists():
                scene_elapsed = time.time() - t_scene
                size_mb = round(clip_path.stat().st_size / 1024 / 1024, 1)
                print(f"  done {scene_elapsed:.1f}s  [{size_mb}MB]")
                clip_paths.append(clip_path)
            else:
                print(f"  FAILED")
                failed_scenes.append(n)

        if failed_scenes:
            print(f"\n  ⚠️  Skipping failed scenes: {failed_scenes}")
            print(f"  Continuing render with {len(clip_paths)}/{len(scenes_info)} scenes...")
            # Filter scenes_info to only successful scenes for subtitle timing
            scenes_info = [s for s in scenes_info if s["scene_number"] not in failed_scenes]

        # ── Concatenate all clips ─────────────────────────────────────────────
        print()
        print("  Concatenating all scenes...", end="", flush=True)
        t_concat = time.time()
        concat_path = out_dir / f"{refined.slug}_concat.mp4"
        ok = self._concatenate_scenes(clip_paths, concat_path, tmp_dir)
        if not ok:
            raise RuntimeError("Concatenation failed. Check FFmpeg output above.")
        print(f"  done {time.time()-t_concat:.1f}s")

        # ── Replace video audio with final_mix.mp3 (narration + music) ────────
        # final_mix.mp3 already contains narration + background music from Stage 5.
        # We REPLACE the video audio entirely — not mix — to avoid echo.
        # The individual scene clips have narration baked in, but we discard that
        # and use final_mix.mp3 as the single authoritative audio track.
        music_path = Path(config.AUDIO_DIR) / refined.slug / "final_mix.mp3"
        if music_path.exists():
            print("  Replacing audio with final mix (narration + music)...", end="", flush=True)
            t_music = time.time()
            music_concat_path = out_dir / f"{refined.slug}_music.mp4"

            # Get durations to decide how to handle length mismatch.
            # final_mix.mp3 has intro + narration + outro padding built in by Stage 5,
            # so it is intentionally LONGER than the raw concatenated video.
            # We extend the last video frame to cover the full audio length.
            # DO NOT use -shortest — that would cut audio off at video end.
            video_dur = _get_stream_duration(concat_path)
            audio_dur = _get_stream_duration(music_path)

            if audio_dur > video_dur + 0.1:
                # Audio is longer (normal case — has outro tail).
                # Extend last video frame to cover the full audio length.
                ok = run_ffmpeg([
                    "-i", str(concat_path),
                    "-i", str(music_path),
                    "-filter_complex",
                    # tpad extends the video by holding the last frame
                    f"[0:v]tpad=stop_mode=clone:stop_duration={audio_dur - video_dur:.3f}[vout]",
                    "-map", "[vout]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "18",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    str(music_concat_path),
                ], label="audio replace + extend video")
            else:
                # Audio is shorter or same length — use it as-is, pad audio with silence.
                ok = run_ffmpeg([
                    "-i", str(concat_path),
                    "-i", str(music_path),
                    "-filter_complex",
                    # apad adds silence at the end of audio to match video length
                    "[1:a]apad[aout]",
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(music_concat_path),
                ], label="audio replace + pad audio")

            if ok and music_concat_path.exists():
                concat_path.unlink(missing_ok=True)
                concat_path = music_concat_path
                print(f"  done {time.time()-t_music:.1f}s  "
                      f"[video {video_dur:.1f}s → audio {audio_dur:.1f}s]")
            else:
                print("  failed — keeping original narration audio")
                music_concat_path.unlink(missing_ok=True)
        else:
            print("  No final_mix.mp3 found — video uses scene narration only")
            print(f"  Run Stage 5 to add background music")

        # ── Burn subtitles ────────────────────────────────────────────────────
        final_path = out_dir / f"{refined.slug}_final.mp4"

        if burn_subtitles:
            print("  Burning subtitles...", end="", flush=True)
            t_sub = time.time()
            ok = self._burn_subtitles(concat_path, final_path, scenes_info)
            if not ok:
                print("  subtitle burn failed — using version without subtitles")
                concat_path.rename(final_path)
            else:
                print(f"  done {time.time()-t_sub:.1f}s")
                concat_path.unlink(missing_ok=True)
        else:
            concat_path.rename(final_path)

        # ── Cleanup temp files ────────────────────────────────────────────────
        print("  Cleaning up temp files...", end="", flush=True)
        for f in tmp_dir.glob("*.mp4"):
            f.unlink(missing_ok=True)
        for f in tmp_dir.glob("*.txt"):
            f.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
        print("  done")

        # ── Save manifest ─────────────────────────────────────────────────────
        elapsed = time.time() - t_start
        manifest_path = self._save_render_manifest(
            out_dir, refined, scenes_info, final_path, elapsed
        )

        file_size_mb = round(final_path.stat().st_size / 1024 / 1024, 2)

        print()
        print(f"{'─'*60}")
        print(f"  Render time  : {elapsed:.1f}s")
        print(f"  Duration     : ~{total_dur:.1f}s")
        print(f"  File size    : {file_size_mb}MB")
        print(f"  Output       : {final_path}")
        print(f"  Manifest     : {manifest_path}")
        print(f"{'─'*60}")

        return final_path

    @staticmethod
    def load_manifest(slug: str) -> dict:
        """Load the render manifest for a slug."""
        path = Path(config.FINAL_DIR) / slug / "render_manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Render manifest not found: {path}")
        return json.loads(path.read_text())