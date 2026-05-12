"""
thumbnail_generator.py — Stage 9: Thumbnail Generation

Generates a YouTube-optimised thumbnail using Fal.ai Flux.
The thumbnail uses the refined script's thumbnail_concept and
main character description for visual consistency with the video.

Output sizes:
    1280x720  — YouTube standard thumbnail (16:9)
    1080x1920 — Shorts preview thumbnail (9:16, same as video)

Cost: $0.04 per thumbnail (Fal.ai Flux)
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import fal_client
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript


# ─────────────────────────────────────────────────────────────────────────────
#  THUMBNAIL PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_thumbnail_prompt(refined: RefinedScript) -> tuple[str, str]:
    """
    Build the image prompt and negative prompt for the thumbnail.

    Returns (prompt, negative_prompt).

    Thumbnail formula for kids YouTube:
    - Character in extreme close-up or dynamic action pose
    - Big expressive eyes, peak emotional moment
    - Bold simple background with strong colour contrast
    - Title text worked into the scene naturally (Flux handles text well)
    - Bright, saturated, eye-catching colours
    """
    char = refined.main_character
    concept = refined.thumbnail_concept
    title = refined.title

    prompt = (
        f"{char}, "
        f"{concept}, "
        f"extreme close-up portrait, face filling frame, huge expressive eyes, "
        f"peak emotional moment, mouth open with joy or surprise, "
        f"bold solid colour background, bright saturated colours, "
        f"children's book illustration style, Pixar-inspired, "
        f"soft cel-shading, clean outlines, "
        f"professional YouTube thumbnail composition, "
        f"high contrast, visually striking, eye-catching, "
        f"no text, no words, no letters, no watermark"
    )

    negative_prompt = (
        "text, words, letters, watermark, signature, title, "
        "ugly, deformed, extra limbs, bad anatomy, blurry, "
        "low quality, dark, scary, realistic photo, 3d render, "
        "multiple characters, cluttered background, busy background, "
        "small character, full body shot from far away"
    )

    return prompt, negative_prompt


# ─────────────────────────────────────────────────────────────────────────────
#  TEXT OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

def add_title_text(
    input_path: Path,
    output_path: Path,
    title: str,
    font_size: int = 100,
    text_color: tuple = (255, 255, 255),
    outline_color: tuple = (0, 0, 0),
    outline_width: int = 7,
    y_percent: float = 0.78,
) -> Path:
    """
    Add bold outlined title text to a thumbnail image using Pillow.
    Text is centred horizontally and positioned in the lower portion.

    Args:
        input_path:    Source PNG image
        output_path:   Output PNG path
        title:         Title text — use \n for line breaks
        font_size:     Font size in pixels
        text_color:    RGB tuple for text fill
        outline_color: RGB tuple for text outline
        outline_width: Outline stroke width in pixels
        y_percent:     Vertical position of text centre (0=top, 1=bottom)
    """
    img  = Image.open(input_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Try system fonts in order — first match wins
    font = None
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",       # Windows Arial Bold
        "C:/Windows/Fonts/calibrib.ttf",       # Windows Calibri Bold
        "C:/Windows/Fonts/impact.ttf",         # Windows Impact
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "/System/Library/Fonts/Helvetica.ttc", # Mac
        "arialbd.ttf",                         # local fallback
    ]
    for c in candidates:
        try:
            font = ImageFont.truetype(c, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    lines       = title.split("\n")
    line_height = int(font_size * 1.15)
    total_h     = len(lines) * line_height
    y_start     = int(h * y_percent) - total_h // 2

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        tw   = bbox[2] - bbox[0]

        # Clamp x so text never overflows image edges (20px padding)
        x = max(20, (w - tw) // 2)
        y = y_start + i * line_height

        # Draw thick outline (8 directions)
        ow = outline_width
        for dx in range(-ow, ow + 1, max(1, ow // 3)):
            for dy in range(-ow, ow + 1, max(1, ow // 3)):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=outline_color)

        # Draw main text
        draw.text((x, y), line, font=font, fill=text_color)

    # Save
    img.convert("RGB").save(str(output_path), "PNG")
    return output_path


def build_short_title(full_title: str) -> str:
    """
    Convert a full story title into a short punchy thumbnail title.
    Splits into max 2 lines of ~12 chars each.
    e.g. "Timmy's Big Ship Adventure" → "Timmy's BIG\nAdventure!"
    """
    # Remove possessives clutter for short version
    words = full_title.split()
    if len(words) <= 3:
        return full_title + "!"

    # Try to split roughly in half
    mid = len(words) // 2
    line1 = " ".join(words[:mid])
    line2 = " ".join(words[mid:])

    # Add exclamation if not already there
    if not line2.endswith("!"):
        line2 = line2 + "!"

    return f"{line1}\n{line2}"


# ─────────────────────────────────────────────────────────────────────────────
#  THUMBNAIL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class ThumbnailGenerator:
    """
    Generates YouTube thumbnails using Fal.ai Flux.

    Produces two sizes:
    - landscape_16_9 (1280x720) for standard YouTube thumbnail upload
    - portrait_16_9  (1080x1920) for Shorts preview

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.thumbnail_generator import ThumbnailGenerator

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        gen = ThumbnailGenerator()
        paths = gen.generate(refined)
        print(paths["landscape"])  # output/thumbnails/slug/thumbnail_16x9.png
    """

    def __init__(self):
        if not config.FAL_KEY:
            raise EnvironmentError("FAL_KEY not found in .env")
        os.environ["FAL_KEY"] = config.FAL_KEY

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.THUMBS_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    async def _generate_one(
        self,
        prompt: str,
        negative_prompt: str,
        image_size: str,
        output_path: Path,
    ) -> bool:
        """Generate one thumbnail image via Fal.ai Flux."""
        try:
            handler = await fal_client.submit_async(
                "fal-ai/flux-pro/v1.1",
                arguments={
                    "prompt":           prompt,
                    "negative_prompt":  negative_prompt,
                    "image_size":       image_size,
                    "num_images":       1,
                    "output_format":    "png",
                    "safety_tolerance": "5",
                    "enable_safety_checker": False,
                },
            )

            async for event in handler.iter_events(with_logs=False):
                if isinstance(event, fal_client.Queued):
                    print(f"\r    {image_size} — queued...        ", end="", flush=True)
                elif isinstance(event, fal_client.InProgress):
                    print(f"\r    {image_size} — generating...    ", end="", flush=True)

            result = await handler.get()
            images = result.get("images", [])
            if not images or not images[0].get("url"):
                return False

            urllib.request.urlretrieve(images[0]["url"], output_path)
            return True

        except Exception as e:
            print(f"\n    Error: {e}")
            return False

    def generate(self, refined: RefinedScript) -> dict:
        """
        Generate thumbnail images for the video.

        Returns dict with paths:
            {
                "landscape": Path(...thumbnail_16x9.png),   # 1280x720 YouTube
                "portrait":  Path(...thumbnail_9x16.png),   # 1080x1920 Shorts
            }
        """
        print(f"\n{'='*60}")
        print(f"  Stage 9: Thumbnail — '{refined.title}'")
        print(f"{'='*60}")

        out_dir = self._get_output_dir(refined.slug)
        prompt, neg_prompt = build_thumbnail_prompt(refined)

        print(f"  Character: {refined.main_character[:60]}...")
        print(f"  Concept  : {refined.thumbnail_concept[:80]}...")
        print()

        results = {}
        sizes = [
            ("landscape_16_9", "thumbnail_16x9.png",  "YouTube (1280×720)"),
            ("portrait_16_9",  "thumbnail_9x16.png",  "Shorts  (1080×1920)"),
        ]

        # Run both thumbnails in parallel inside ONE asyncio.run() call.
        # Running them sequentially inside a coroutine caused "Event loop is closed"
        # because fal_client.submit_async tried to create a new loop after the first
        # await completed and the outer loop had been torn down between iterations.
        async def run_all():
            async def generate_and_report(image_size: str, filename: str, label: str):
                output_path = out_dir / filename
                print(f"  Generating {label}...")
                t = time.time()
                ok = await self._generate_one(
                    prompt, neg_prompt, image_size, output_path
                )
                elapsed = round(time.time() - t, 1)
                if ok:
                    size_kb = output_path.stat().st_size // 1024
                    print(f"  ✅  {label}  [{size_kb}KB]  {elapsed}s")
                    return image_size.split("_")[0], output_path
                else:
                    print(f"  ❌  {label} failed")
                    return image_size.split("_")[0], None

            # Both requests go to Fal.ai simultaneously — same total time as one
            tasks = [
                generate_and_report(image_size, filename, label)
                for image_size, filename, label in sizes
            ]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in task_results:
                if isinstance(r, Exception):
                    print(f"  ❌  Thumbnail task error: {r}")
                elif r[1] is not None:
                    results[r[0]] = r[1]

        asyncio.run(run_all())

        # Save manifest
        manifest = {
            "slug":    refined.slug,
            "title":   refined.title,
            "prompt":  prompt[:200],
            "files":   {k: str(v) for k, v in results.items()},
            "cost_usd": round(len(results) * 0.04, 3),
        }
        (out_dir / "thumbnail_manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )

        # ── Add title text overlay to all generated thumbnails ──────────────
        if results:
            print()
            print("  Adding title text overlay...", end="", flush=True)
            short_title = build_short_title(refined.title)
            text_results = {}

            for key, src_path in results.items():
                # Portrait (9:16) needs smaller font — image is narrow
                # Landscape (16:9) can use larger font — image is wide
                fsize = 75 if key == "portrait" else 95
                dst_path = src_path.parent / src_path.name.replace(".png", "_text.png")
                try:
                    add_title_text(
                        input_path=src_path,
                        output_path=dst_path,
                        title=short_title,
                        font_size=fsize,
                        y_percent=0.85 if key == "portrait" else 0.78,
                    )
                    text_results[key] = dst_path
                except Exception as e:
                    print(f"\n  Text overlay failed for {key}: {e}")
                    text_results[key] = src_path  # fall back to no-text version

            print(f" done")
            # Add text versions to results
            results.update({f"{k}_text": v for k, v in text_results.items()})

        print()
        print(f"  Cost     : ~${sum(1 for k in results if 'text' not in k) * 0.04:.2f}")
        print(f"  Output   : {out_dir}")
        print(f"{'─'*60}")
        print()
        print("  Files generated:")
        for key, path in results.items():
            label = {
                "landscape":      "YouTube 16:9 (no text)",
                "portrait":       "Shorts 9:16  (no text)",
                "landscape_text": "YouTube 16:9 ✅ UPLOAD THIS",
                "portrait_text":  "Shorts 9:16  ✅ UPLOAD THIS",
            }.get(key, key)
            print(f"  → {label}: {Path(path).name}")
        print(f"{'─'*60}")

        return results