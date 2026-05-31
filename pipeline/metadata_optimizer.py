"""
metadata_optimizer.py — Stage 10: YouTube Metadata Optimisation

Uses Claude to generate viral-optimised YouTube metadata from the refined script:
  - SEO title (A/B variants)
  - Description with timestamps, keywords, hashtags, Bensound credit
  - Tags (50 tags, mix of broad + niche)
  - Chapters for long videos
  - Cards / end-screen suggestions
  - Best upload time recommendation
  - Thumbnail A/B test text suggestions

Output:
    output/metadata/<slug>/youtube_metadata.json
    output/metadata/<slug>/youtube_metadata.txt   (copy-paste ready)

Cost: ~$0.005 Claude API (tiny prompt, small output)
"""

import anthropic
import json
import sys
import time
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript
from prompts.loader import load_prompt


# ─────────────────────────────────────────────────────────────────────────────
#  METADATA OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = load_prompt("metadata_system")


def _build_prompt(refined: RefinedScript, video_duration_sec: int, is_long: bool) -> str:
    narration_preview = " ".join(
        s.narration for s in refined.scenes[:4]
    )

    scene_list = "\n".join(
        f"  Scene {s.scene_number:02d} [{s.emotion}]: {s.narration}"
        for s in refined.scenes
    )

    duration_str = (
        f"{video_duration_sec // 60} minutes {video_duration_sec % 60} seconds"
        if video_duration_sec >= 60
        else f"{video_duration_sec} seconds"
    )

    include_val = "true" if is_long else "false"
    return load_prompt(
        "metadata_user",
        title=refined.title,
        moral=refined.moral,
        character=refined.main_character,
        category=refined.category,
        music_mood=refined.background_music_mood,
        duration_str=duration_str,
        is_long=is_long,
        narration_preview=narration_preview,
        scene_list=scene_list,
        existing_description=refined.youtube_description,
        existing_tags=", ".join(refined.youtube_tags),
        include_val=include_val,
    )


class MetadataOptimizer:
    """
    Generates viral-optimised YouTube metadata using Claude.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.metadata_optimizer import MetadataOptimizer

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        opt = MetadataOptimizer()
        meta = opt.generate(refined, video_duration_sec=62)
        print(meta["title_primary"])
    """

    def __init__(self):
        if not config.ANTHROPIC_API_KEY:
            raise EnvironmentError("ANTHROPIC_API_KEY not found in .env")
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _get_output_dir(self, slug: str) -> Path:
        d = Path(config.OUTPUT_DIR) / "metadata" / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _call_claude(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=config.STORY_MODEL,
            max_tokens=2048,
            temperature=0.8,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "max_tokens":
            raise ValueError("Metadata response truncated — increase max_tokens")
        return response.content[0].text

    def _parse(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(text)

    def _save(self, slug: str, meta: dict, out_dir: Path) -> tuple[Path, Path]:
        """Save JSON and copy-paste ready .txt version."""
        json_path = out_dir / "youtube_metadata.json"
        json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        # Build human-readable copy-paste text
        lines = [
            "═" * 60,
            "  YOUTUBE METADATA — COPY-PASTE READY",
            "═" * 60,
            "",
            "── TITLE (PRIMARY) ──────────────────────────────────────",
            meta.get("title_primary", ""),
            "",
            "── TITLE VARIANTS (A/B TEST) ────────────────────────────",
        ]
        for i, v in enumerate(meta.get("title_variants", []), 1):
            lines.append(f"  {i}. {v}")

        lines += [
            "",
            "── DESCRIPTION (FULL) ───────────────────────────────────",
            meta.get("description_full", ""),
            "",
            "── DESCRIPTION (SHORTS — 150 chars) ─────────────────────",
            meta.get("description_short", ""),
            "",
            "── TAGS (copy all) ──────────────────────────────────────",
            ", ".join(meta.get("tags", [])),
            "",
        ]

        chapters = meta.get("chapters", {})
        if chapters.get("include") and chapters.get("list"):
            lines += [
                "── CHAPTERS ─────────────────────────────────────────────",
            ]
            for ch in chapters["list"]:
                lines.append(f"  {ch['time']} {ch['title']}")
            lines.append("")

        lines += [
            "── THUMBNAIL TEXT OPTIONS ───────────────────────────────",
        ]
        for i, t in enumerate(meta.get("thumbnail_text_options", []), 1):
            lines.append(f"  {i}. {t}")

        upload = meta.get("best_upload_time", {})
        lines += [
            "",
            "── BEST UPLOAD TIME ─────────────────────────────────────",
            f"  {upload.get('day', '')} at {upload.get('time_utc', '')} UTC",
            f"  Reason: {upload.get('reason', '')}",
            "",
            "── END SCREEN SUGGESTIONS ───────────────────────────────",
        ]
        for s in meta.get("end_screen_suggestions", []):
            lines.append(f"  • {s}")

        lines += [
            "",
            "── PRIMARY SEO KEYWORDS ─────────────────────────────────",
            "  " + ", ".join(meta.get("seo_keywords_primary", [])),
            "",
            f"── PLAYLIST ─────────────────────────────────────────────",
            f"  {meta.get('playlist_suggestion', '')}",
            "",
            f"── VIRAL SCORE ESTIMATE ─────────────────────────────────",
            f"  {meta.get('viral_score_estimate', '')}",
            "",
            "═" * 60,
        ]

        txt_path = out_dir / "youtube_metadata.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, txt_path

    def generate(
        self,
        refined: RefinedScript,
        video_duration_sec: int = 62,
        is_long: bool = False,
    ) -> dict:
        """
        Generate viral YouTube metadata for the video.

        Args:
            refined:           RefinedScript from Stage 2
            video_duration_sec: Actual video duration in seconds (from render manifest)
            is_long:           True for 8+ minute videos (enables chapters, mid-roll)

        Returns:
            dict with all metadata fields
        """
        slug = refined.slug
        out_dir = self._get_output_dir(slug)

        print(f"\n{'='*60}")
        print(f"  Stage 10: Metadata Optimisation — '{refined.title}'")
        print(f"{'='*60}")
        print(f"  Duration : {video_duration_sec}s")
        print(f"  Long     : {is_long}")
        print(f"  Calling Claude for viral metadata...", end="", flush=True)

        t = time.time()
        prompt = _build_prompt(refined, video_duration_sec, is_long)
        raw = self._call_claude(prompt)
        elapsed = time.time() - t
        print(f" done in {elapsed:.1f}s")

        meta = self._parse(raw)

        # Ensure required fields have fallbacks
        meta.setdefault("title_primary", refined.title)
        meta.setdefault("tags", refined.youtube_tags)
        meta.setdefault("made_for_kids", True)
        meta.setdefault("category_id", "27")  # Education

        json_path, txt_path = self._save(slug, meta, out_dir)

        print(f"  Title    : {meta.get('title_primary', '')}")
        print(f"  Tags     : {len(meta.get('tags', []))} tags")
        print(f"  Viral    : {meta.get('viral_score_estimate', 'N/A')}")
        print(f"  JSON     : {json_path}")
        print(f"  TXT      : {txt_path}")
        print(f"{'─'*60}")

        return meta

    @staticmethod
    def load_metadata(slug: str) -> dict:
        path = Path(config.OUTPUT_DIR) / "metadata" / slug / "youtube_metadata.json"
        if not path.exists():
            raise FileNotFoundError(f"Metadata not found: {path}")
        return json.loads(path.read_text())