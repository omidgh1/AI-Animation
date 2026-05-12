"""
youtube_metadata.py — Stage 9: YouTube SEO & Metadata Builder

Takes the RefinedScript + render manifest (for exact chapter timestamps)
and builds a fully optimised YouTube metadata package:

  - SEO-structured description  (hook → summary → lesson → CTA → chapters
                                  → music attribution → hashtags)
  - Viral tag set               (broad + character + intent + trending)
  - Chapter timestamps          (derived from render_manifest.json scene timings)
  - Pinned comment text         (engagement prompt, posted right after upload)

Output:
    output/final/<slug>/youtube_metadata.json   ← consumed by Stage 10 (upload)

Usage:
    python pipeline/youtube_metadata.py timmys-big-ship-adventure
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import RefinedScript
from pipeline.scene_refiner import SceneRefiner
from pipeline.video_renderer import VideoRenderer


# ─────────────────────────────────────────────────────────────────────────────
#  EVERGREEN TAG BANK  (always appended — proven to rank for kids content)
# ─────────────────────────────────────────────────────────────────────────────

EVERGREEN_TAGS = [
    "kids stories",
    "animated stories for kids",
    "bedtime stories",
    "children cartoons",
    "moral stories for kids",
    "short stories for kids",
    "stories for toddlers",
    "educational cartoon",
    "feel good kids story",
    "kids youtube",
]

SHORTS_EXTRA_TAGS = [
    "shorts",
    "kids shorts",
    "animated shorts",
    "short cartoon for kids",
]

# Category → extra thematic tags automatically added
CATEGORY_TAGS = {
    "animal_adventure":       ["animal cartoon", "animal story for kids", "cute animal video"],
    "friendship_and_emotions": ["friendship story", "kids emotions", "feelings for children"],
    "magic_and_fantasy":      ["magic story for kids", "fantasy cartoon", "fairy tale for kids"],
    "learning_and_educational": ["learn with cartoons", "educational kids video", "kids learning"],
    "bedtime_and_calming":    ["bedtime story", "calm kids video", "sleep story for kids"],
}

# Mood → extra thematic tags
MOOD_TAGS = {
    "playful":           ["fun cartoon", "funny kids story"],
    "adventurous":       ["adventure story for kids", "brave kids cartoon"],
    "magical":           ["magical cartoon", "enchanted story"],
    "calm_and_soothing": ["relaxing kids video", "gentle bedtime story"],
    "dramatic":          ["exciting kids story", "suspense cartoon"],
    "funny":             ["funny cartoon for kids", "comedy kids story"],
    "heartwarming":      ["heartwarming kids story", "touching cartoon"],
}

# Scene numbers → human-readable chapter labels
CHAPTER_LABELS = {
    1:  "🌟 The Hook",
    2:  "🌍 Meet the Character",
    3:  "😟 The Problem",
    4:  "💪 First Try",
    5:  "😢 Feeling Sad",
    6:  "🤝 A Friend Appears",
    7:  "🔨 Working Together",
    8:  "🏃 Almost There!",
    9:  "🎉 Breakthrough!",
    10: "🥳 Celebration",
    11: "📖 The Lesson",
    12: "👋 Goodbye",
}

# Music attribution (legally required for Bensound tracks)
BENSOUND_ATTRIBUTION = (
    "🎵 Background music: Bensound.com (Free license with attribution)"
)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _seconds_to_timestamp(total_seconds: float) -> str:
    """Convert float seconds → MM:SS string for YouTube chapters."""
    total_seconds = max(0, int(total_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _build_tags(refined: RefinedScript, is_shorts: bool) -> list[str]:
    """
    Build the full tag list with no duplicates, respecting YouTube's
    500-character combined limit.

    Order: story-specific → category → mood → evergreen → shorts
    """
    seen = set()
    tags = []

    def add(tag: str):
        t = tag.lower().strip()
        if t and t not in seen:
            seen.add(t)
            tags.append(t)

    # Story-specific tags from Claude (most relevant — go first)
    for t in refined.youtube_tags:
        add(t)

    # Category-specific
    for t in CATEGORY_TAGS.get(refined.category, []):
        add(t)

    # Mood-specific
    for t in MOOD_TAGS.get(refined.background_music_mood, []):
        add(t)

    # Evergreen broad tags
    for t in EVERGREEN_TAGS:
        add(t)

    # Shorts-specific
    if is_shorts:
        for t in SHORTS_EXTRA_TAGS:
            add(t)

    # Enforce YouTube combined 500-char limit
    safe = []
    total = 0
    for t in tags:
        if total + len(t) + 1 <= 500:
            safe.append(t)
            total += len(t) + 1

    return safe


def _build_chapters(manifest: dict) -> tuple[list[dict], str]:
    """
    Build chapter timestamps from render_manifest scene timings.

    YouTube chapter rules:
    - First chapter MUST start at 0:00
    - Minimum 3 chapters required for YouTube to show them
    - Each chapter must be at least 10 seconds long

    Returns (chapters_list, chapters_text_block).
    """
    scenes = manifest.get("scenes", [])
    if not scenes:
        return [], ""

    chapters = []
    current_time = 0.0

    for scene in scenes:
        n        = scene["scene_number"]
        duration = scene["duration"]
        label    = CHAPTER_LABELS.get(n, f"Scene {n:02d}")

        chapters.append({
            "scene":     n,
            "label":     label,
            "timestamp": _seconds_to_timestamp(current_time),
            "seconds":   round(current_time, 2),
        })
        current_time += duration

    # Build text block — YouTube parses these from description
    lines = ["📍 Story Chapters:"]
    for ch in chapters:
        lines.append(f"{ch['timestamp']} {ch['label']}")

    return chapters, "\n".join(lines)


def _build_description(
    refined: RefinedScript,
    chapters_text: str,
    is_shorts: bool,
) -> str:
    """
    Build a fully-structured, SEO-optimised YouTube description.

    Structure:
      1. Hook sentence       ← first 2 lines (crucial — shown before "Show more")
      2. Story summary       ← 2-3 sentences, spoiler-free
      3. Today's lesson
      4. Age suitability
      5. CTA block
      6. Chapters            ← YouTube parses timestamps from here
      7. Music attribution   ← legally required for Bensound
      8. Hashtags            ← algorithm boost (3 shown under title)
    """
    title   = refined.title
    moral   = refined.moral
    char    = refined.main_character.split(",")[0].strip()   # first descriptor only
    category_label = refined.category.replace("_", " ").title()

    # ── 1. Hook (first ~125 chars — visible before "Show more") ──────────────
    hook = f'✨ "{title}" — a magical story for little ones! 🌟'

    # ── 2. Story summary ─────────────────────────────────────────────────────
    summary = (
        f"Join {char} on an unforgettable adventure in this beautiful animated story "
        f"for children aged 3–9. "
        f"What happens when things go wrong? "
        f"Watch to find out how kindness and courage save the day! 🐾💛"
    )

    # ── 3. Lesson ────────────────────────────────────────────────────────────
    lesson_block = f"✨ Today's lesson: {moral}"

    # ── 4. Age suitability ───────────────────────────────────────────────────
    audience = (
        "Perfect for children aged 3–9. "
        "Great for bedtime, quiet time, road trips, and classroom story time! 😊"
    )

    # ── 5. CTA block ─────────────────────────────────────────────────────────
    cta = (
        "👉 SUBSCRIBE for a new kids story every week!\n"
        "❤️  LIKE this video if your little one enjoyed it!\n"
        "💬 COMMENT below — what's your child's favourite part?"
    )

    # ── 6. Chapters (only for long-form, not Shorts — Shorts has no chapters) ─
    chapters_section = "" if is_shorts else f"\n{chapters_text}\n"

    # ── 7. Music attribution ──────────────────────────────────────────────────
    music = BENSOUND_ATTRIBUTION

    # ── 8. Hashtags (3 shown under video title, rest boost algorithm) ─────────
    if is_shorts:
        hashtags = "#Shorts #KidsStories #AnimatedStories #BedtimeStories #KidsCartoon"
    else:
        hashtags = (
            f"#{category_label.replace(' ','')} #KidsStories #AnimatedStories "
            f"#BedtimeStories #KidsCartoon #MoralStories #ChildrensStories "
            f"#KidsYouTube #CartoonForKids #StoriesForKids"
        )

    # ── Assemble ──────────────────────────────────────────────────────────────
    parts = [
        hook,
        "",
        summary,
        "",
        lesson_block,
        "",
        audience,
        "",
        cta,
        chapters_section,
        "─" * 40,
        music,
        "",
        hashtags,
    ]

    description = "\n".join(parts)

    # YouTube limit: 5000 chars
    return description[:5000]


def _build_title(refined: RefinedScript, is_shorts: bool) -> str:
    """
    Build an optimised YouTube title.

    Formula: [Emoji] Story Title [Format suffix]
    - Adds a relevant emoji prefix based on story category
    - Adds #Shorts suffix only for Shorts (max 100 chars total)
    """
    CATEGORY_EMOJI = {
        "animal_adventure":        "🐾",
        "friendship_and_emotions": "💛",
        "magic_and_fantasy":       "✨",
        "learning_and_educational": "📚",
        "bedtime_and_calming":     "🌙",
    }
    emoji   = CATEGORY_EMOJI.get(refined.category, "🌟")
    title   = f"{emoji} {refined.title}"
    suffix  = " #Shorts" if is_shorts else ""
    full    = (title + suffix)[:100]
    return full


def _build_pinned_comment(refined: RefinedScript) -> str:
    """
    Build the text for a pinned comment posted immediately after upload.
    Pinned comments boost engagement signals in the first hour — critical
    for the YouTube algorithm.
    """
    char = refined.main_character.split(",")[0].strip()
    return (
        f"💬 What did {char} teach your little one today? "
        f"Tell us in the comments below! 👇\n\n"
        f"📖 Today's lesson: {refined.moral}\n\n"
        f"❤️  Don't forget to LIKE and SUBSCRIBE for more stories every week!"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  METADATA BUILDER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class YouTubeMetadataBuilder:
    """
    Stage 9: Build optimised YouTube metadata from the RefinedScript.

    Produces a complete metadata package saved to:
        output/final/<slug>/youtube_metadata.json

    This JSON is then consumed directly by Stage 10 (YouTubeUploader)
    instead of building metadata on-the-fly during upload.

    Example:
        from pipeline.scene_refiner import SceneRefiner
        from pipeline.youtube_metadata import YouTubeMetadataBuilder

        refined = SceneRefiner.load_refined("timmys-big-ship-adventure")
        builder = YouTubeMetadataBuilder()
        meta = builder.build(refined, is_shorts=True)
        print(meta["title"])
        print(meta["description"])
    """

    def _get_output_dir(self, slug: str) -> Path:
        out_dir = Path(config.FINAL_DIR) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def build(
        self,
        refined: RefinedScript,
        is_shorts: bool = True,
        privacy: str = "private",
    ) -> dict:
        """
        Build and save the full YouTube metadata package.

        Args:
            refined:   RefinedScript from Stage 2.
            is_shorts: True for 9:16 Shorts videos, False for 16:9 long-form.
            privacy:   "private" | "unlisted" | "public"

        Returns the metadata dict (also saved to youtube_metadata.json).
        """
        print(f"\n{'='*62}")
        print(f"  Stage 9: YouTube Metadata — '{refined.title}'")
        print(f"{'='*62}")
        print(f"  Format   : {'Shorts (9:16)' if is_shorts else 'Long-form (16:9)'}")
        print(f"  Privacy  : {privacy}")
        print()

        # ── Chapters (uses render manifest for exact timings) ─────────────────
        chapters = []
        chapters_text = ""
        try:
            manifest      = VideoRenderer.load_manifest(refined.slug)
            chapters, chapters_text = _build_chapters(manifest)
            print(f"  Chapters : {len(chapters)} scenes timed from render manifest ✓")
        except FileNotFoundError:
            print("  Chapters : render manifest not found — chapters skipped")
            print("             (Run Stage 6 before Stage 9 for chapter timestamps)")

        # ── Build each metadata field ─────────────────────────────────────────
        title       = _build_title(refined, is_shorts)
        description = _build_description(refined, chapters_text, is_shorts)
        tags        = _build_tags(refined, is_shorts)
        pinned_comment = _build_pinned_comment(refined)

        # ── Assemble package ──────────────────────────────────────────────────
        metadata = {
            # Core YouTube API fields
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  "1",     # Film & Animation
            "defaultLanguage": "en",
            "privacyStatus":   privacy,
            "madeForKids":     True,

            # Extra fields (used by uploader / for human review)
            "slug":          refined.slug,
            "is_shorts":     is_shorts,
            "pinned_comment": pinned_comment,
            "chapters":      chapters,
            "moral":         refined.moral,
            "tag_count":     len(tags),
            "description_chars": len(description),
            "built_at":      time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

        # ── Save to disk ──────────────────────────────────────────────────────
        out_dir  = self._get_output_dir(refined.slug)
        out_path = out_dir / "youtube_metadata.json"
        out_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

        # ── Print preview ─────────────────────────────────────────────────────
        self._print_preview(metadata)
        print(f"\n  Saved → {out_path}")
        print(f"{'─'*62}")

        return metadata

    def _print_preview(self, meta: dict):
        print(f"{'─'*62}")
        print(f"  TITLE ({len(meta['title'])} chars):")
        print(f"    {meta['title']}")
        print()
        print(f"  DESCRIPTION ({meta['description_chars']} chars) — first 3 lines:")
        for line in meta["description"].splitlines()[:3]:
            print(f"    {line}")
        print("    ...")
        print()
        print(f"  TAGS ({meta['tag_count']} tags, "
              f"{sum(len(t) for t in meta['tags'])} combined chars):")
        print(f"    {', '.join(meta['tags'][:8])}{'...' if len(meta['tags']) > 8 else ''}")
        print()
        if meta["chapters"]:
            print(f"  CHAPTERS ({len(meta['chapters'])}):")
            for ch in meta["chapters"][:4]:
                print(f"    {ch['timestamp']}  {ch['label']}")
            if len(meta["chapters"]) > 4:
                print(f"    ... +{len(meta['chapters']) - 4} more")
        print()
        print(f"  PINNED COMMENT preview:")
        print(f"    {meta['pinned_comment'][:100]}...")

    @staticmethod
    def load(slug: str) -> dict:
        """Load a previously built metadata package from disk."""
        path = Path(config.FINAL_DIR) / slug / "youtube_metadata.json"
        if not path.exists():
            raise FileNotFoundError(
                f"youtube_metadata.json not found for slug: {slug}\n"
                f"Run Stage 9 (YouTubeMetadataBuilder) first."
            )
        return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stage 9 — Build YouTube SEO metadata"
    )
    parser.add_argument("slug", help="Video slug (e.g. timmys-big-ship-adventure)")
    parser.add_argument(
        "--long", dest="is_shorts", action="store_false", default=True,
        help="Build for long-form 16:9 video (default: Shorts 9:16)",
    )
    parser.add_argument(
        "--privacy", choices=["private", "unlisted", "public"], default="private",
    )
    args = parser.parse_args()

    refined = SceneRefiner.load_refined(args.slug)
    builder = YouTubeMetadataBuilder()
    builder.build(refined, is_shorts=args.is_shorts, privacy=args.privacy)


if __name__ == "__main__":
    main()
