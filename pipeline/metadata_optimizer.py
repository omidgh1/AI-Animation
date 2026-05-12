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


# ─────────────────────────────────────────────────────────────────────────────
#  METADATA OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = dedent("""
    You are a YouTube SEO specialist and viral content strategist for kids channels.
    You have deep knowledge of the YouTube Kids algorithm, what parents search for,
    and what titles/thumbnails get clicked by children aged 3-9.

    Your job: given a kids animated story script, generate fully optimised YouTube
    metadata that maximises CTR, watch time, and discoverability.

    YOUTUBE KIDS ALGORITHM FACTS:
    - Titles with character names + emotional words perform best ("Timmy SAVES the day!")
    - Numbers in titles increase CTR ("5 Brave Friends", "12 Magical Scenes")
    - ALL CAPS one word creates urgency without clickbait penalty
    - Description first 3 lines appear in search — make them count
    - Tags: mix 5 broad (kids stories, animated stories) + 20 niche + 25 specific
    - Best upload times for kids: Saturday 7-9am, Sunday 8-10am (parent's timezone)
    - Chapters boost watch time by 15-25% on long videos
    - End screens with "Watch next" suggestions increase session time

    OUTPUT FORMAT: Return ONLY valid JSON, no markdown, no explanation.
    Start with { and end with }.
""").strip()


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
    return dedent(f"""
        Generate viral YouTube metadata for this kids animated story:

        STORY DETAILS:
        Title         : {refined.title}
        Moral         : {refined.moral}
        Character     : {refined.main_character}
        Category      : {refined.category}
        Music mood    : {refined.background_music_mood}
        Duration      : {duration_str}
        Is long video : {is_long} (long = 8+ minutes, unlocks mid-roll ads)

        NARRATION PREVIEW (first 4 scenes):
        {narration_preview}

        ALL SCENES:
        {scene_list}

        EXISTING DESCRIPTION (from story generation):
        {refined.youtube_description}

        EXISTING TAGS:
        {", ".join(refined.youtube_tags)}

        REQUIRED JSON OUTPUT:
        {{
          "title_primary": "<main title — max 60 chars, character name + emotional hook>",
          "title_variants": [
            "<alt title 1 — different emotional angle>",
            "<alt title 2 — question format>",
            "<alt title 3 — number/list format>"
          ],
          "description_full": "<full YouTube description, 800-1000 chars. First 3 lines are the hook. Include story summary, moral, parent note, Music by Bensound.com credit, and 10 hashtags at end>",
          "description_short": "<150 char version for Shorts — punchy, ends with hashtags>",
          "tags": [
            "<50 tags total: 5 ultra-broad, 20 mid-tier, 25 specific. No duplicates. Mix singular/plural. Max 500 chars total>",
            "..."
          ],
          "chapters": {{"include": {include_val}, "list": [
            {{"time": "0:00", "title": "<chapter title>"}},
            {{"time": "1:00", "title": "<chapter title>"}},
            "..."
          ]}},
          "thumbnail_text_options": [
            "<option 1 — 3-5 words, CAPS for key word>",
            "<option 2 — different emotional angle>",
            "<option 3 — character name focus>"
          ],
          "best_upload_time": {{
            "day": "<best day of week>",
            "time_utc": "<HH:MM UTC>",
            "reason": "<one sentence why>"
          }},
          "end_screen_suggestions": [
            "<suggestion 1 — what video type to show next>",
            "<suggestion 2>",
            "<suggestion 3>"
          ],
          "cards_suggestions": [
            "<card 1 — timestamp and what to link>",
            "<card 2>"
          ],
          "category_id": "<YouTube category ID as string: 20=Gaming, 22=People&Blogs, 24=Entertainment, 27=Education, 28=Science&Tech>",
          "made_for_kids": true,
          "language": "en",
          "viral_score_estimate": "<1-10 score with one sentence explanation>",
          "seo_keywords_primary": ["<top 5 keywords parents would search>"],
          "playlist_suggestion": "<name of playlist this video should be added to>"
        }}
    """).strip()


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