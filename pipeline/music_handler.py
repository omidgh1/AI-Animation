"""
music_handler.py — Stage 5: Background Music

Downloads a royalty-free background music track and mixes it
under the narration audio.

Music source: Bensound.com — free background music tracks
  License: Free with attribution for YouTube (see bensound.com/licensing)
  These are well-known, stable URLs that have been reliable for years.

Output:
    output/music/<slug>/background.mp3      (downloaded track)
    output/audio/<slug>/final_mix.mp3       (narration + music mixed)
"""

import json
import math
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


# ─────────────────────────────────────────────────────────────────────────────
#  MUSIC TRACKS  (Bensound.com — free, stable, kids-appropriate)
#  License: Free with attribution in video description
#  Add "Music by Bensound.com" to your YouTube description
# ─────────────────────────────────────────────────────────────────────────────

BENSOUND_TRACKS = {
    # ── Kids moods ──────────────────────────────────────────────────────────
    "playful": [
        "https://www.bensound.com/bensound-music/bensound-ukulele.mp3",
        "https://www.bensound.com/bensound-music/bensound-sunny.mp3",
    ],
    "adventurous": [
        "https://www.bensound.com/bensound-music/bensound-adventure.mp3",
        "https://www.bensound.com/bensound-music/bensound-epic.mp3",
    ],
    "magical": [
        "https://www.bensound.com/bensound-music/bensound-dreams.mp3",
        "https://www.bensound.com/bensound-music/bensound-fairy-tale.mp3",
    ],
    "calm_and_soothing": [
        "https://www.bensound.com/bensound-music/bensound-relaxing.mp3",
        "https://www.bensound.com/bensound-music/bensound-sweet.mp3",
    ],
    "heartwarming": [
        "https://www.bensound.com/bensound-music/bensound-tenderness.mp3",
        "https://www.bensound.com/bensound-music/bensound-memories.mp3",
    ],
    "funny": [
        "https://www.bensound.com/bensound-music/bensound-ukulele.mp3",
        "https://www.bensound.com/bensound-music/bensound-sunny.mp3",
    ],
    "dramatic": [
        "https://www.bensound.com/bensound-music/bensound-epic.mp3",
        "https://www.bensound.com/bensound-music/bensound-adventure.mp3",
    ],
    # ── Facts / adult moods ──────────────────────────────────────────────────
    "upbeat": [
        "https://www.bensound.com/bensound-music/bensound-energy.mp3",
        "https://www.bensound.com/bensound-music/bensound-upbeat.mp3",
    ],
    "tense": [
        "https://www.bensound.com/bensound-music/bensound-suspense.mp3",
        "https://www.bensound.com/bensound-music/bensound-epic.mp3",
    ],
    "mysterious": [
        "https://www.bensound.com/bensound-music/bensound-mystery.mp3",
        "https://www.bensound.com/bensound-music/bensound-suspense.mp3",
    ],
    "inspiring": [
        "https://www.bensound.com/bensound-music/bensound-inspire.mp3",
        "https://www.bensound.com/bensound-music/bensound-energy.mp3",
    ],
    "energetic": [
        "https://www.bensound.com/bensound-music/bensound-energy.mp3",
        "https://www.bensound.com/bensound-music/bensound-upbeat.mp3",
    ],
    "curious": [
        "https://www.bensound.com/bensound-music/bensound-tenderness.mp3",
        "https://www.bensound.com/bensound-music/bensound-mystery.mp3",
    ],
}

# Attribution line to add to YouTube description
BENSOUND_ATTRIBUTION = "Music by Bensound.com | License code: Free"


def download_track(url: str, output_path: Path) -> bool:
    """Download a music track from URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bensound.com/",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 10_000:
            return False   # too small — error page
        output_path.write_bytes(data)
        return True
    except Exception:
        return False


def generate_silence(output_path: Path, duration_sec: float) -> bool:
    """Generate a silent MP3 as absolute last resort."""
    try:
        from pydub import AudioSegment
        silence = AudioSegment.silent(
            duration=int(duration_sec * 1000),
            frame_rate=44100
        )
        silence.export(str(output_path), format="mp3", bitrate="128k")
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  MUSIC HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class MusicHandler:
    """
    Downloads background music and mixes it with narration audio.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.music_handler import MusicHandler

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        handler = MusicHandler()
        final_mix = handler.create_mix(refined)
    """

    def __init__(self):
        Path(config.MUSIC_DIR).mkdir(parents=True, exist_ok=True)

    def _get_music_dir(self, slug: str) -> Path:
        d = Path(config.MUSIC_DIR) / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def download_music(
        self, mood: str, slug: str, duration_sec: float = 60.0
    ) -> Path | None:
        """
        Download a background track for the given mood.
        Tries each URL for the mood until one succeeds.
        Falls back to silence if all fail.
        """
        music_dir = self._get_music_dir(slug)
        output_path = music_dir / f"background_{mood}.mp3"

        # Use cached version
        if output_path.exists() and output_path.stat().st_size > 10_000:
            print(f"  Music    : using cached track ({output_path.stat().st_size // 1024}KB)")
            return output_path

        urls = BENSOUND_TRACKS.get(mood, BENSOUND_TRACKS["playful"])

        for i, url in enumerate(urls):
            track_name = url.split("/")[-1].replace(".mp3", "")
            print(f"  Music    : downloading '{track_name}'...", end="", flush=True)
            if download_track(url, output_path):
                size_kb = output_path.stat().st_size // 1024
                print(f" done [{size_kb}KB]")
                print(f"  Credit   : {BENSOUND_ATTRIBUTION}")
                return output_path
            print(f" failed, trying next...")

        # Final fallback — silence
        print(f"  Music    : generating silence fallback...", end="", flush=True)
        if generate_silence(output_path, duration_sec):
            size_kb = output_path.stat().st_size // 1024
            print(f" done [{size_kb}KB] (silent fallback)")
            return output_path

        return None

    def mix_audio(
        self,
        narration_path: Path,
        music_path: Path,
        output_path: Path,
        total_duration: float,
        music_volume: float = None,
        fade_in: float = None,
        fade_out: float = None,
        intro_sec: float = None,
        outro_sec: float = None,
    ) -> Path:
        """
        Mix narration audio with background music.

        Layout of the final mix:
            [intro_sec of music only]
            [narration mixed under music]
            [outro_sec of music only]
            [fade out]

        This gives the video a proper musical intro before the first word
        and a tail after the last word so the video does not cut off abruptly.
        """
        from pydub import AudioSegment

        vol       = music_volume if music_volume is not None else config.MUSIC_VOLUME
        fi_ms     = int((fade_in  if fade_in  is not None else config.MUSIC_FADE_IN_SEC)  * 1000)
        fo_ms     = int((fade_out if fade_out is not None else config.MUSIC_FADE_OUT_SEC) * 1000)
        intro_ms  = int((intro_sec if intro_sec is not None else config.MUSIC_INTRO_SEC)  * 1000)
        outro_ms  = int((outro_sec if outro_sec is not None else config.MUSIC_OUTRO_SEC)  * 1000)

        # Total mix length = intro + narration + outro
        narration_actual_ms = int(total_duration * 1000)
        total_mix_ms = intro_ms + narration_actual_ms + outro_ms

        print(f"  Mixing   : {intro_ms//1000}s intro + narration + {outro_ms//1000}s outro "
              f"= {total_mix_ms//1000}s  (vol={vol:.0%})...", end="", flush=True)

        narration = AudioSegment.from_file(str(narration_path))
        music     = AudioSegment.from_file(str(music_path))

        # Loop music to cover the full mix duration
        if len(music) < total_mix_ms:
            loops = (total_mix_ms // len(music)) + 2
            music = music * loops
        music = music[:total_mix_ms]

        # Reduce music volume
        db_reduction = 20 * math.log10(vol) if vol > 0 else -60
        music = music + db_reduction

        # Fade in at the very start, fade out at the very end
        music = music.fade_in(fi_ms).fade_out(fo_ms)

        # Overlay narration starting after the intro silence
        # music track already runs the full length — narration sits on top of it
        mix = music.overlay(narration, position=intro_ms)
        mix.export(str(output_path), format="mp3", bitrate="192k")

        size_kb = output_path.stat().st_size // 1024
        print(f" done [{size_kb}KB  {total_mix_ms//1000}s total]")
        return output_path

    def _get_duration(self, audio_path: Path) -> float:
        try:
            from pydub import AudioSegment
            return len(AudioSegment.from_file(str(audio_path))) / 1000.0
        except Exception:
            return 60.0

    def create_mix(self, refined, narration_path: Path = None) -> Path | None:
        """Full pipeline: download music + mix with narration."""
        slug = refined.slug
        mood = refined.background_music_mood

        print(f"\n{'='*60}")
        print(f"  Stage 5: Music — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Mood     : {mood}")

        if narration_path is None:
            narration_path = Path(config.AUDIO_DIR) / slug / "full_narration.mp3"

        if not narration_path.exists():
            print(f"  ❌ Narration not found: {narration_path}")
            return None

        narration_duration = self._get_duration(narration_path)
        print(f"  Duration : {narration_duration:.1f}s")

        music_path = self.download_music(mood, slug, narration_duration)
        if not music_path:
            print(f"  ⚠️  No music available — skipping mix")
            return None

        output_path = Path(config.AUDIO_DIR) / slug / "final_mix.mp3"
        self.mix_audio(
            narration_path=narration_path,
            music_path=music_path,
            output_path=output_path,
            total_duration=narration_duration,
            # intro/outro come from config — gives music breathing room
        )

        final_duration = self._get_duration(output_path)
        print(f"  Output   : {output_path}")
        print(f"  Timeline : {config.MUSIC_INTRO_SEC}s music intro → "
              f"{narration_duration:.1f}s narration → "
              f"{config.MUSIC_OUTRO_SEC}s music outro = "
              f"{final_duration:.1f}s total")
        print(f"  ℹ️  Add to YouTube description: {BENSOUND_ATTRIBUTION}")
        print(f"{'─'*60}")
        return output_path

    @staticmethod
    def load_mix(slug: str) -> Path:
        path = Path(config.AUDIO_DIR) / slug / "final_mix.mp3"
        if not path.exists():
            raise FileNotFoundError(f"Final mix not found: {path}")
        return path