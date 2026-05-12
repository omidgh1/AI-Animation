"""
voice_generator.py — Stage 4: AI Voice Generation

Reads a RefinedScript and generates one narration audio clip per scene
using the ElevenLabs API. Voice selection is automatic based on each
scene's emotion tag, using the three voices defined in config.py.

Output:
    output/audio/<slug>/scene_01.mp3  ...  scene_12.mp3
    output/audio/<slug>/full_narration.mp3   (all scenes joined)
    output/audio/<slug>/voice_manifest.json
"""

import json
import sys
import time
from pathlib import Path

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript, RefinedScene


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def pick_voice(scene: RefinedScene) -> str:
    """
    Select the best voice ID for a scene based on its emotion.
    Falls back to VOICE_DEFAULT if emotion not in map.
    """
    return config.VOICE_EMOTION_MAP.get(scene.emotion, config.VOICE_DEFAULT)


def estimate_duration_seconds(text: str, words_per_minute: int = 130) -> float:
    """
    Rough estimate of audio duration from word count.
    Kids narration is ~120-140 wpm — slower than adult speech.
    Used for pre-flight cost estimates only.
    """
    words = len(text.split())
    return round((words / words_per_minute) * 60, 1)


# ─────────────────────────────────────────────────────────────────────────────
#  VOICE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class VoiceGenerator:
    """
    Generates narration audio for all scenes in a RefinedScript
    using the ElevenLabs TTS API.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.voice_generator import VoiceGenerator

        refined = SceneRefiner.load_refined("sparks-big-brave-moment")
        gen = VoiceGenerator()
        results = gen.generate(refined)
        # Audio saved to output/audio/sparks-big-brave-moment/scene_01.mp3 ...
    """

    def __init__(self, use_fast_model: bool = False):
        """
        Args:
            use_fast_model: Use eleven_flash_v2_5 instead of eleven_multilingual_v2.
                            Faster and cheaper — good for testing.
                            Switch to False for final production renders.
        """
        if not config.ELEVENLABS_API_KEY:
            raise EnvironmentError(
                "ELEVENLABS_API_KEY not found. "
                "Add ELEVENLABS_API_KEY=sk_... to your .env file."
            )
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import VoiceSettings
        except ImportError:
            raise ImportError(
                "elevenlabs package not installed. "
                "Run: pip install elevenlabs"
            )

        self.client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        self.VoiceSettings = VoiceSettings
        self.model = (
            config.ELEVENLABS_MODEL_FAST
            if use_fast_model
            else config.ELEVENLABS_MODEL
        )

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.AUDIO_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @retry(
        stop=stop_after_attempt(config.MAX_RETRIES),
        wait=wait_exponential(
            min=config.RETRY_WAIT_MIN_SEC,
            max=config.RETRY_WAIT_MAX_SEC
        ),
        reraise=True,
    )
    def _generate_clip(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
    ) -> int:
        """
        Call ElevenLabs TTS for one text chunk.
        Returns file size in KB.
        """
        vs = self.VoiceSettings(
            stability=config.VOICE_SETTINGS["stability"],
            similarity_boost=config.VOICE_SETTINGS["similarity_boost"],
            style=config.VOICE_SETTINGS["style"],
            use_speaker_boost=config.VOICE_SETTINGS["use_speaker_boost"],
        )

        # ElevenLabs returns a generator of audio bytes
        audio_stream = self.client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=self.model,
            voice_settings=vs,
            output_format=config.ELEVENLABS_OUTPUT_FORMAT,
        )

        # Write stream to file
        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)

        return output_path.stat().st_size // 1024

    def _join_audio_files(
        self,
        scene_paths: list[Path],
        output_path: Path,
        silence_ms: int = 300,
    ) -> Path:
        """
        Join all scene audio files into one full narration track.
        Adds a short silence between scenes so cuts feel natural.

        Uses pydub if available, falls back to raw binary concatenation.
        """
        try:
            from pydub import AudioSegment

            combined = AudioSegment.empty()
            silence = AudioSegment.silent(duration=silence_ms)

            for i, path in enumerate(scene_paths):
                if path.exists() and path.stat().st_size > 0:
                    seg = AudioSegment.from_mp3(str(path))
                    combined += seg
                    if i < len(scene_paths) - 1:
                        combined += silence

            combined.export(str(output_path), format="mp3")
            return output_path

        except ImportError:
            # Fallback: raw binary join (no silence, but works without pydub)
            with open(output_path, "wb") as out:
                for path in scene_paths:
                    if path.exists() and path.stat().st_size > 0:
                        out.write(path.read_bytes())
            return output_path

    def _save_manifest(
        self,
        results: list[dict],
        out_dir: Path,
        refined: RefinedScript,
        full_narration_path: Path,
    ) -> Path:
        """
        Save voice_manifest.json — maps scene numbers to audio files.
        Read by Stage 8 (video renderer) to sync audio with images.
        """
        successful = [r for r in results if r["status"] == "success"]
        total_chars = sum(len(r.get("text", "")) for r in successful)
        # ElevenLabs charges per character — estimate cost
        # eleven_multilingual_v2: ~$0.30 per 1K chars on Creator plan
        cost_per_1k = 0.30
        estimated_cost = round((total_chars / 1000) * cost_per_1k, 4)

        manifest = {
            "slug": refined.slug,
            "title": refined.title,
            "model": self.model,
            "total_scenes": len(refined.scenes),
            "successful": len(successful),
            "failed": len(results) - len(successful),
            "total_characters": total_chars,
            "estimated_cost_usd": estimated_cost,
            "full_narration_file": str(full_narration_path),
            "scenes": sorted(results, key=lambda r: r["scene_number"]),
        }

        path = out_dir / "voice_manifest.json"
        path.write_text(json.dumps(manifest, indent=2))
        return path

    def generate(
        self,
        refined: RefinedScript,
        use_fast_model: bool = False,
    ) -> list[dict]:
        """
        Generate narration audio for all 12 scenes.

        Args:
            refined:        RefinedScript from Stage 2
            use_fast_model: Override to use Flash model (faster/cheaper)

        Returns:
            List of result dicts — one per scene — with status, file, timing.
        """
        print(f"\n{'='*60}")
        print(f"  Stage 4: Voice Generation — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Model    : {self.model}")
        print(f"  Scenes   : {len(refined.scenes)}")
        print()
        print(f"  Voice assignment by emotion:")
        print(f"    Warm narrator  : sad, scared, calm, magical, curious")
        print(f"    Energetic      : happy, excited, funny, surprised, proud")
        print()

        out_dir = self._get_output_dir(refined.slug)
        print(f"  Output dir : {out_dir}")
        print()

        results = []
        scene_paths = []
        t_total = time.time()

        for scene in refined.scenes:
            n = scene.scene_number
            voice_id = pick_voice(scene)

            # Label which voice is being used
            if voice_id == config.VOICE_WARM_NARRATOR:
                voice_label = "warm"
            elif voice_id == config.VOICE_ENERGETIC:
                voice_label = "energetic"
            else:
                voice_label = "character"

            output_path = out_dir / f"scene_{n:02d}.mp3"
            text = scene.narration

            print(
                f"  Scene {n:02d}  [{scene.emotion:10s}]  "
                f"[{voice_label:10s}]  {len(text)} chars  ...",
                end="", flush=True
            )

            t_start = time.time()
            try:
                size_kb = self._generate_clip(text, voice_id, output_path)
                elapsed = round(time.time() - t_start, 1)
                est_dur = estimate_duration_seconds(text)

                print(f"  done {elapsed}s  [{size_kb}KB  ~{est_dur}s audio]")
                scene_paths.append(output_path)

                results.append({
                    "scene_number": n,
                    "status": "success",
                    "file": str(output_path),
                    "text": text,
                    "voice_id": voice_id,
                    "voice_label": voice_label,
                    "emotion": scene.emotion,
                    "size_kb": size_kb,
                    "elapsed": elapsed,
                    "estimated_audio_duration": est_dur,
                })

            except Exception as e:
                elapsed = round(time.time() - t_start, 1)
                print(f"  FAILED after {elapsed}s: {e}")
                scene_paths.append(None)
                results.append({
                    "scene_number": n,
                    "status": "failed",
                    "error": str(e),
                    "elapsed": elapsed,
                })

            # Small pause between API calls — ElevenLabs rate limit is generous
            # but a tiny gap prevents any burst throttling
            time.sleep(0.3)

        # Join all clips into one full narration track
        print()
        print("  Joining scene clips into full narration...", end="", flush=True)
        valid_paths = [p for p in scene_paths if p and p.exists()]
        full_path = out_dir / "full_narration.mp3"
        self._join_audio_files(valid_paths, full_path)
        full_kb = full_path.stat().st_size // 1024
        print(f" done  [{full_kb}KB]")

        # Save manifest
        manifest_path = self._save_manifest(results, out_dir, refined, full_path)

        # Summary
        successful = [r for r in results if r["status"] == "success"]
        failed     = [r for r in results if r["status"] == "failed"]
        total_chars = sum(len(r.get("text", "")) for r in successful)
        total_time  = round(time.time() - t_total, 1)

        print()
        print(f"{'─'*60}")
        print(f"  Total time  : {total_time}s")
        print(f"  Successful  : {len(successful)}/{len(results)}")
        if failed:
            print(f"  Failed      : scenes {[r['scene_number'] for r in failed]}")
        print(f"  Characters  : {total_chars}")
        print(f"  Est. cost   : ~${round((total_chars/1000)*0.30, 4)}")
        print(f"  Full audio  : {full_path}")
        print(f"  Manifest    : {manifest_path}")
        print(f"{'─'*60}")

        return results

    @staticmethod
    def load_manifest(slug: str) -> dict:
        """Load the voice manifest for a slug — used by Stage 8."""
        path = Path(config.AUDIO_DIR) / slug / "voice_manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Voice manifest not found: {path}")
        return json.loads(path.read_text())