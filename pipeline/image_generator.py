"""
image_generator.py — Stage 3: AI Image Generation

Uses the official fal_client Python SDK (not raw HTTP) to generate
one image per scene from the RefinedScript produced by Stage 2.

All 12 images run in parallel via asyncio — total time ≈ slowest
single image (~20s), not 12 × 20s.

Output:
    output/raw/<slug>/scene_01.png  ...  scene_12.png
    output/raw/<slug>/manifest.json
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import fal_client

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
#  MODEL ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

PRIMARY_MODEL  = "fal-ai/flux-pro/v1.1"
FALLBACK_MODEL = "fal-ai/flux/dev"


# ─────────────────────────────────────────────────────────────────────────────
#  PAYLOAD BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(scene: RefinedScene, refined: RefinedScript) -> dict:
    """
    Build the Fal.ai request arguments for one scene.

    FLUX.1.1 [pro] key parameters:
      prompt          : image description (we append global_style_suffix if missing)
      negative_prompt : what to exclude
      image_size      : "portrait_9_16" → native 1080×1920 for Shorts
      num_images      : always 1
      output_format   : "png" for lossless quality
      safety_tolerance: "5" = most permissive (kids content is always safe)
    """
    prompt = scene.image_prompt
    suffix = refined.global_style_suffix
    if suffix and suffix[:25] not in prompt:
        prompt = f"{prompt.rstrip('. ')}, {suffix}"

    neg = scene.negative_prompt
    global_neg = refined.global_negative_prompt
    if global_neg and global_neg[:20] not in neg:
        neg = f"{neg}, {global_neg}"

    return {
        "prompt": prompt,
        "negative_prompt": neg,
        "image_size": "portrait_16_9",   # Fal.ai enum for vertical 9:16 format
        "num_images": 1,
        "output_format": "png",
        "safety_tolerance": "5",
        "enable_safety_checker": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  SINGLE SCENE GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

async def generate_one_scene(
    scene: RefinedScene,
    refined: RefinedScript,
    output_path: Path,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Generate one scene image using fal_client.submit_async.

    The official SDK handles:
      - Submitting to the queue
      - Polling status via iter_events
      - Returning the completed result

    Returns a result dict with status, file path, timing, size.
    """
    async with semaphore:
        t_start = time.time()
        n = scene.scene_number
        payload = build_payload(scene, refined)

        for attempt, model in enumerate([PRIMARY_MODEL, FALLBACK_MODEL]):
            try:
                print(f"    Scene {n:02d} — submitting to {model}...")

                # Submit to Fal.ai queue and stream events until complete
                handler = await fal_client.submit_async(
                    model,
                    arguments=payload,
                )

                # Stream status events — logs progress without blocking
                async for event in handler.iter_events(with_logs=False):
                    if isinstance(event, fal_client.Queued):
                        print(
                            f"\r    Scene {n:02d} — queued (pos {event.position})   ",
                            end="", flush=True
                        )
                    elif isinstance(event, fal_client.InProgress):
                        print(
                            f"\r    Scene {n:02d} — in progress...                  ",
                            end="", flush=True
                        )

                # Get the completed result
                result = await handler.get()
                break  # Success — exit retry loop

            except Exception as e:
                elapsed = time.time() - t_start
                if attempt == 0:
                    print(f"\n    Scene {n:02d} — primary failed ({e}), trying fallback...")
                else:
                    print(f"\n    Scene {n:02d} — FAILED after {elapsed:.1f}s: {e}")
                    return {
                        "scene_number": n,
                        "status": "failed",
                        "error": str(e),
                        "elapsed": round(elapsed, 1),
                    }

        # Extract image URL from result
        images = result.get("images", [])
        if not images or not images[0].get("url"):
            return {
                "scene_number": n,
                "status": "failed",
                "error": "No image URL in result",
                "elapsed": round(time.time() - t_start, 1),
            }

        image_url = images[0]["url"]

        # Download image to disk using stdlib (no extra deps)
        urllib.request.urlretrieve(image_url, output_path)

        elapsed = round(time.time() - t_start, 1)
        size_kb = output_path.stat().st_size // 1024
        used_model = FALLBACK_MODEL if attempt == 1 else PRIMARY_MODEL

        print(
            f"\r    Scene {n:02d} — done {elapsed}s  "
            f"[{size_kb}KB]  [{used_model.split('/')[-1]}]          "
        )

        return {
            "scene_number": n,
            "status": "success",
            "file": str(output_path),
            "size_kb": size_kb,
            "elapsed": elapsed,
            "model": used_model,
            "image_url": image_url,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  IMAGE GENERATOR ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class ImageGenerator:
    """
    Orchestrates parallel image generation for all 12 scenes.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.image_generator import ImageGenerator

        refined = SceneRefiner.load_refined("sparks-big-brave-moment")
        gen = ImageGenerator()
        results = gen.generate(refined)
        # Images saved to output/raw/sparks-big-brave-moment/scene_01.png ...
    """

    def __init__(self, max_concurrent: int = 3):
        """
        Args:
            max_concurrent: Images generated in parallel.
                            3 is safe for free tier. Raise to 5 with paid credits.
        """
        if not config.FAL_KEY:
            raise EnvironmentError(
                "FAL_KEY not found. Add FAL_KEY=key-xxxxxxxx to your .env file."
            )
        # Set FAL_KEY for the SDK — it reads from env variable
        os.environ["FAL_KEY"] = config.FAL_KEY
        self.max_concurrent = max_concurrent

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.RAW_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _save_manifest(
        self, results: list[dict], out_dir: Path, refined: RefinedScript
    ) -> Path:
        """
        Save manifest.json — maps scene numbers to file paths.
        Read by Stage 8 (video renderer) to assemble scenes in order.
        """
        successful = [r for r in results if r["status"] == "success"]
        manifest = {
            "slug": refined.slug,
            "title": refined.title,
            "total_scenes": len(refined.scenes),
            "successful": len(successful),
            "failed": len(results) - len(successful),
            "total_cost_usd": round(len(successful) * 0.04, 3),
            "scenes": sorted(results, key=lambda r: r["scene_number"]),
        }
        path = out_dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2))
        return path

    async def _run_all(
        self, refined: RefinedScript, out_dir: Path
    ) -> list[dict]:
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = [
            generate_one_scene(
                scene=scene,
                refined=refined,
                output_path=out_dir / f"scene_{scene.scene_number:02d}.png",
                semaphore=semaphore,
            )
            for scene in refined.scenes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any unhandled exceptions to error dicts
        cleaned = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                cleaned.append({
                    "scene_number": refined.scenes[i].scene_number,
                    "status": "failed",
                    "error": str(r),
                    "elapsed": 0,
                })
            else:
                cleaned.append(r)
        return cleaned

    def generate(self, refined: RefinedScript) -> list[dict]:
        """
        Generate all scene images in parallel and save to disk.

        Returns:
            List of result dicts — one per scene — with status, file, timing.
        """
        print(f"\n{'='*60}")
        print(f"  Stage 3: Image Generation — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Model      : {PRIMARY_MODEL}")
        print(f"  Fallback   : {FALLBACK_MODEL}")
        print(f"  Scenes     : {len(refined.scenes)}")
        print(f"  Concurrent : {self.max_concurrent} at a time")
        print(f"  Est. cost  : ~${len(refined.scenes) * 0.04:.2f}")

        out_dir = self._get_output_dir(refined.slug)
        print(f"  Output dir : {out_dir}")
        print()

        t_start = time.time()
        results = asyncio.run(self._run_all(refined, out_dir))
        elapsed = time.time() - t_start

        manifest_path = self._save_manifest(results, out_dir, refined)

        successful = [r for r in results if r["status"] == "success"]
        failed     = [r for r in results if r["status"] == "failed"]

        print()
        print(f"{'─'*60}")
        print(f"  Total time : {elapsed:.1f}s")
        print(f"  Successful : {len(successful)}/{len(results)}")
        if failed:
            print(f"  Failed     : scenes {[r['scene_number'] for r in failed]}")
        print(f"  Cost       : ~${len(successful) * 0.04:.2f}")
        print(f"  Manifest   : {manifest_path}")
        print(f"{'─'*60}")

        return results

    @staticmethod
    def load_manifest(slug: str) -> dict:
        """Load the image manifest for a slug — used by later stages."""
        path = Path(config.RAW_DIR) / slug / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Manifest not found: {path}")
        return json.loads(path.read_text())