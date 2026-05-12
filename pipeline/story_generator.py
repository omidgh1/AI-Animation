"""
story_generator.py — Stage 1: AI Story & Script Generation

Takes a one-line topic and produces a fully structured VideoScript JSON
using the Claude API. The output drives every downstream stage.

Usage:
    python pipeline/story_generator.py "a tiny dragon who is afraid of fire"
    python pipeline/story_generator.py "two frogs learning to share" --category friendship_and_emotions
    python pipeline/story_generator.py --batch automation/batch_topics.txt
"""

import anthropic
import argparse
import json
import os
import sys
import time
from pathlib import Path
from textwrap import dedent

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# Allow running from project root OR from pipeline/ subfolder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import VideoScript


# ─────────────────────────────────────────────────────────────────────────────
#  SYSTEM PROMPT
#  This is the core of Stage 1. It tells Claude exactly what to produce.
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = dedent("""
    You are a professional children's story writer and video script creator.
    You specialise in writing animated short-form video scripts for children aged 3–9,
    optimised for YouTube Shorts, TikTok, and Instagram Reels (vertical 9:16 format, ~60 seconds).

    YOUR JOB:
    Given a story topic, produce a complete, structured video script as valid JSON.

    STRICT RULES FOR ALL CONTENT:
    - Language must be simple enough for a 3-year-old to understand
    - Maximum 20 words per narration line
    - No scary, violent, or adult themes — ever
    - Every story MUST have a clear emotional arc: problem → struggle → helper → solution → celebration
    - Stories always end happily and positively
    - The main character must be loveable, round-faced, and cute (think Pixar style)
    - Use bright, warm, saturated colours in all image prompts
    - Never mention brands, real people, or copyrighted characters

    SCENE STRUCTURE (12 scenes total):
    Scene 01 — HOOK: Start mid-action. Something surprising or exciting. No slow intros.
               emotion: "surprised"
    Scene 02 — WORLD: Show the character's happy normal world.
               emotion: "happy"
    Scene 03 — PROBLEM: The problem appears. Character looks worried or sad.
               emotion: "scared"
    Scene 04 — ATTEMPT 1: Character tries to solve it — fails.
               emotion: "sad"
    Scene 05 — REACTION: Character feels sad/scared — relatable emotion.
               emotion: "sad"
    Scene 06 — HELPER: A friend or helper arrives — hopeful moment.
               emotion: "surprised"
    Scene 07 — TEAMWORK: They work on the problem together.
               emotion: "curious"
    Scene 08 — ALMOST: Getting closer — almost solved!
               emotion: "excited"
    Scene 09 — BREAKTHROUGH: The key moment — problem is solved!
               emotion: "excited"
    Scene 10 — CELEBRATION: Everyone is happy — big celebration moment.
               emotion: "excited"
    Scene 11 — LESSON: Character shares the lesson they learned.
               emotion: "proud"
    Scene 12 — ENDING: Warm, cosy ending. Character waves goodbye.
               emotion: "calm"

    CRITICAL: Every scene MUST have the correct emotion field as shown above.
    Do NOT use "happy" for all scenes — this breaks voice selection and music mood.
    The emotion field drives which voice tone ElevenLabs uses for narration.

    IMAGE PROMPT RULES:
    - Every image prompt must be 60–120 words
    - Always include the main_character description verbatim
    - Include: character action, facial expression, background setting, lighting mood
    - Always end with: "children's book illustration style, bright cheerful colours, cute friendly design, 9:16 vertical composition"
    - No text or words in images
    - No dark or scary imagery

    CAMERA MOVEMENT GUIDE:
    - slow_zoom_in: for emotional close-up moments
    - slow_zoom_out: for revealing a wider world
    - pan_left / pan_right: for action/movement
    - pan_up: for something rising (balloon, bird flying)
    - pan_down: for something falling or looking down
    - static: for calm, peaceful moments

    SOUND EFFECTS (use sparingly — 0 to 2 per scene):
    Good examples: "magic sparkle", "bird chirp", "happy bounce", "gentle wind",
    "water splash", "leaf rustle", "celebratory pop", "soft footsteps",
    "heart beat", "surprised gasp", "giggle", "applause"

    OUTPUT FORMAT:
    Return ONLY valid JSON matching the schema provided. No markdown, no explanation,
    no code fences. Start your response with { and end with }.
""").strip()


# ─────────────────────────────────────────────────────────────────────────────
#  JSON SCHEMA  (passed to Claude to enforce exact output structure)
# ─────────────────────────────────────────────────────────────────────────────

VIDEO_SCRIPT_SCHEMA = {
    "type": "object",
    "required": [
        "title", "slug", "category", "moral", "main_character",
        "setting", "background_music_mood", "youtube_description",
        "youtube_tags", "thumbnail_concept", "scenes"
    ],
    "properties": {
        "title": {"type": "string"},
        "slug": {"type": "string"},
        "category": {
            "type": "string",
            "enum": [
                "animal_adventure", "friendship_and_emotions",
                "magic_and_fantasy", "learning_and_educational", "bedtime_and_calming"
            ]
        },
        "moral": {"type": "string"},
        "main_character": {"type": "string"},
        "setting": {"type": "string"},
        "background_music_mood": {
            "type": "string",
            "enum": ["playful", "adventurous", "magical", "calm_and_soothing",
                     "dramatic", "funny", "heartwarming"]
        },
        "youtube_description": {"type": "string"},
        "youtube_tags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_concept": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 12,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": [
                    "scene_number", "narration", "on_screen_text",
                    "image_prompt", "camera_movement", "duration_seconds",
                    "emotion", "sound_effects", "transition"
                ],
                "properties": {
                    "scene_number": {"type": "integer"},
                    "narration": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "camera_movement": {
                        "type": "string",
                        "enum": ["slow_zoom_in", "slow_zoom_out", "pan_left",
                                 "pan_right", "pan_up", "pan_down", "static"]
                    },
                    "duration_seconds": {"type": "integer", "minimum": 3, "maximum": 8},
                    "emotion": {
                        "type": "string",
                        "enum": ["happy", "excited", "sad", "scared", "surprised",
                                 "curious", "proud", "calm", "magical", "funny"]
                    },
                    "sound_effects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "timing", "volume"],
                            "properties": {
                                "name": {"type": "string"},
                                "timing": {"type": "string", "enum": ["start", "middle", "end"]},
                                "volume": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                            }
                        }
                    },
                    "transition": {"type": "string", "enum": ["cut", "fade", "wipe"]}
                }
            }
        }
    }
}


# ─────────────────────────────────────────────────────────────────────────────
#  STORY GENERATOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class StoryGenerator:
    """
    Generates a complete kids' video script using the Claude API.

    Example:
        gen = StoryGenerator()
        script = gen.generate("a bunny who is afraid of thunder")
        print(script.title)
        print(script.scenes[0].narration)
    """

    def __init__(self):
        if not config.ANTHROPIC_API_KEY:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not found. "
                "Create a .env file in the project root with your API key."
            )
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._ensure_output_dirs()

    def _ensure_output_dirs(self):
        """Create all output directories if they don't exist."""
        for d in [
            config.OUTPUT_DIR, config.RAW_DIR, config.AUDIO_DIR,
            config.SUBTITLES_DIR, config.FINAL_DIR, config.STORIES_DIR
        ]:
            Path(d).mkdir(parents=True, exist_ok=True)

    def _build_user_prompt(self, topic: str, category: str | None = None) -> str:
        """Build the user-facing prompt that includes the topic and optional category hint."""
        category_hint = ""
        if category and category in config.STORY_CATEGORIES:
            category_hint = f"\nStory category: {category.replace('_', ' ')}"

        return dedent(f"""
            Create a complete kids' video script for this topic:

            TOPIC: {topic}
            {category_hint}
            TARGET AUDIENCE: Children aged 3–9
            VIDEO LENGTH: ~60 seconds (exactly 12 scenes)
            FORMAT: YouTube Shorts / TikTok / Instagram Reels (vertical 9:16)

            Remember:
            - Start with a HOOK in scene 1 — jump straight into the action
            - Keep all narration under 20 words per scene
            - Make the main character adorable and loveable
            - Use the full emotional arc: problem → struggle → helper → solution → celebration
            - Return ONLY valid JSON, nothing else
        """).strip()

    @retry(
        stop=stop_after_attempt(config.MAX_RETRIES),
        wait=wait_exponential(
            min=config.RETRY_WAIT_MIN_SEC,
            max=config.RETRY_WAIT_MAX_SEC
        ),
        retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.RateLimitError)),
        reraise=True,
    )
    def _call_claude(self, user_prompt: str) -> str:
        """
        Make the API call to Claude. Decorated with tenacity retry logic
        so it automatically retries on connection errors or rate limits.
        """
        response = self.client.messages.create(
            model=config.STORY_MODEL,
            max_tokens=config.STORY_MAX_TOKENS,
            temperature=config.STORY_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
        )
        return response.content[0].text

    def _normalize(self, data: dict) -> dict:
        """
        Repair common Claude response variations before Pydantic validation.
        Handles missing top-level fields, plain-string sound_effects, missing
        scene fields, and invalid enum values — all without re-calling the API.
        """
        import re

        # ── Top-level missing fields ──────────────────────────────────────────

        if "slug" not in data and "title" in data:
            raw = data["title"].lower()
            slug = re.sub(r"[^a-z0-9\s-]", "", raw)
            slug = re.sub(r"\s+", "-", slug.strip())
            slug = re.sub(r"-+", "-", slug)[:60]
            data["slug"] = slug

        if "category" not in data:
            data["category"] = "animal_adventure"

        if "moral" not in data:
            data["moral"] = (
                data.pop("story_moral", None)
                or data.pop("lesson", None)
                or "Being brave and trying your best always leads to good things."
            )

        if "setting" not in data:
            data["setting"] = (
                data.pop("world", None)
                or data.pop("environment", None)
                or "a bright and colourful magical world"
            )

        if "background_music_mood" not in data:
            data["background_music_mood"] = (
                data.pop("music_mood", None)
                or data.pop("mood", None)
                or "playful"
            )

        if "youtube_description" not in data:
            data["youtube_description"] = (
                f"Join us for a magical story: {data.get('title', 'A Kids Story')}! "
                f"{data.get('moral', '')} "
                "#KidsStories #AnimatedStories #BedtimeStories #ChildrensStories"
            )

        if "youtube_tags" not in data:
            data["youtube_tags"] = [
                "kids stories", "animated stories", "children's stories",
                "bedtime stories", "kids cartoons", "moral stories for kids",
                "short stories for kids", "educational videos for kids",
            ]

        if "thumbnail_concept" not in data:
            char = data.get("main_character", "the main character")
            title = data.get("title", "this story")
            data["thumbnail_concept"] = (
                f"{char} looking happy and excited, bright colourful background, "
                f"title '{title}', bold friendly font, cheerful and eye-catching."
            )

        if "main_character" not in data:
            data["main_character"] = "a small cute friendly animal with big eyes"

        # ── Enum guards ───────────────────────────────────────────────────────

        valid_moods = {"playful","adventurous","magical","calm_and_soothing",
                       "dramatic","funny","heartwarming"}
        if data.get("background_music_mood") not in valid_moods:
            data["background_music_mood"] = "playful"

        valid_categories = {"animal_adventure","friendship_and_emotions","magic_and_fantasy",
                            "learning_and_educational","bedtime_and_calming"}
        if data.get("category") not in valid_categories:
            data["category"] = "animal_adventure"

        # ── Scene-level fixes ─────────────────────────────────────────────────

        valid_emotions    = {"happy","excited","sad","scared","surprised",
                             "curious","proud","calm","magical","funny"}
        valid_cameras     = {"slow_zoom_in","slow_zoom_out","pan_left","pan_right",
                             "pan_up","pan_down","static"}
        valid_transitions = {"cut","fade","wipe"}

        for scene in data.get("scenes", []):

            # on_screen_text: first 4 words of narration
            if not scene.get("on_screen_text"):
                words = scene.get("narration", "").split()[:4]
                scene["on_screen_text"] = " ".join(words).rstrip(".,!?") + "!"

            # emotion default
            if scene.get("emotion") not in valid_emotions:
                scene["emotion"] = "happy"

            # camera_movement default
            if scene.get("camera_movement") not in valid_cameras:
                scene["camera_movement"] = "static"

            # transition default
            if scene.get("transition") not in valid_transitions:
                scene["transition"] = "cut"

            # duration clamp
            try:
                scene["duration_seconds"] = max(3, min(8, int(scene.get("duration_seconds", 5))))
            except (TypeError, ValueError):
                scene["duration_seconds"] = 5

            # sound_effects: strings → SoundEffect dicts
            fixed_sfx = []
            for sfx in scene.get("sound_effects", []):
                if isinstance(sfx, str):
                    fixed_sfx.append({"name": sfx, "timing": "start", "volume": 0.6})
                elif isinstance(sfx, dict):
                    sfx.setdefault("name", "sound effect")
                    sfx.setdefault("timing", "start")
                    sfx.setdefault("volume", 0.6)
                    if sfx["timing"] not in {"start","middle","end"}:
                        sfx["timing"] = "start"
                    fixed_sfx.append(sfx)
            scene["sound_effects"] = fixed_sfx

        return data

    def _parse_and_validate(self, raw_json: str) -> VideoScript:
        """
        Parse Claude's raw JSON, normalize it, then validate with Pydantic.
        """
        text = raw_json.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Claude returned invalid JSON: {e}\n\nRaw response:\n{raw_json[:500]}")

        data = self._normalize(data)

        try:
            script = VideoScript(**data)
        except Exception as e:
            raise ValueError(f"JSON structure doesn't match VideoScript model after normalization: {e}")

        if len(script.scenes) != config.NUM_SCENES:
            raise ValueError(f"Expected {config.NUM_SCENES} scenes, got {len(script.scenes)}.")

        return script



    def _save_script(self, script: VideoScript) -> Path:
        """Save the script JSON to output/stories/<slug>.json for resumability."""
        output_path = Path(config.STORIES_DIR) / f"{script.slug}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(script.model_dump_json(indent=2))
        return output_path

    def generate(
        self,
        topic: str,
        category: str | None = None,
        save: bool = True,
    ) -> VideoScript:
        """
        Generate a complete video script from a topic string.

        Args:
            topic:    One-line story topic, e.g. "a bunny afraid of thunder"
            category: Optional story category override. If None, Claude chooses.
            save:     If True, saves the JSON to output/stories/.

        Returns:
            A validated VideoScript Pydantic model.
        """
        print(f"\n{'='*60}")
        print(f"  Stage 1: Generating story for: '{topic}'")
        print(f"{'='*60}")
        print(f"  Model    : {config.STORY_MODEL}")
        print(f"  Scenes   : {config.NUM_SCENES}")
        if category:
            print(f"  Category : {category}")
        print()

        t_start = time.time()
        user_prompt = self._build_user_prompt(topic, category)

        print("  Calling Claude API...", end="", flush=True)
        raw_response = self._call_claude(user_prompt)
        elapsed = time.time() - t_start
        print(f" done in {elapsed:.1f}s")

        print("  Parsing and validating JSON...", end="", flush=True)
        script = self._parse_and_validate(raw_response)
        print(" done")

        if save:
            saved_path = self._save_script(script)
            print(f"  Saved    : {saved_path}")

        print()
        print(f"  Title    : {script.title}")
        print(f"  Category : {script.category}")
        print(f"  Moral    : {script.moral}")
        print(f"  Duration : ~{script.total_duration_seconds}s")
        print(f"  Character: {script.main_character[:60]}...")
        print()

        return script

    def generate_batch(self, topics: list[tuple[str, str | None]]) -> list[VideoScript]:
        """
        Generate multiple scripts from a list of (topic, category) tuples.
        Saves each one and reports progress.

        Args:
            topics: List of (topic_string, category_or_None) tuples.

        Returns:
            List of VideoScript objects.
        """
        scripts = []
        total = len(topics)
        for i, (topic, category) in enumerate(topics, 1):
            print(f"\n[{i}/{total}] Processing: {topic}")
            try:
                script = self.generate(topic, category)
                scripts.append(script)
            except Exception as e:
                print(f"  ERROR generating '{topic}': {e}")
                continue
            # Small pause between batch calls to be kind to the API
            if i < total:
                time.sleep(1)
        return scripts

    @staticmethod
    def load_script(slug_or_path: str) -> VideoScript:
        """
        Load a previously saved script from disk.

        Args:
            slug_or_path: Either a slug like 'brave-little-bunny' or a full file path.

        Returns:
            A validated VideoScript model.
        """
        path = Path(slug_or_path)
        if not path.suffix:
            path = Path(config.STORIES_DIR) / f"{slug_or_path}.json"
        if not path.exists():
            raise FileNotFoundError(f"Script not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return VideoScript(**data)


# ─────────────────────────────────────────────────────────────────────────────
#  PRETTY PRINTER  (for CLI usage)
# ─────────────────────────────────────────────────────────────────────────────

def print_script_summary(script: VideoScript):
    """Print a human-readable summary of a generated script."""
    divider = "─" * 60

    print(f"\n{divider}")
    print(f"  VIDEO SCRIPT SUMMARY")
    print(divider)
    print(f"  Title      : {script.title}")
    print(f"  Slug       : {script.slug}")
    print(f"  Category   : {script.category}")
    print(f"  Moral      : {script.moral}")
    print(f"  Duration   : ~{script.total_duration_seconds} seconds")
    print(f"  Music mood : {script.background_music_mood}")
    print(f"\n  Character  : {script.main_character}")
    print(f"  Setting    : {script.setting}")
    print(f"\n  Thumbnail  : {script.thumbnail_concept}")
    print(f"\n  YouTube tags: {', '.join(script.youtube_tags[:8])}...")
    print(f"\n{divider}")
    print(f"  SCENE BREAKDOWN")
    print(divider)

    emotion_icons = {
        "happy": "😊", "excited": "🤩", "sad": "😢", "scared": "😨",
        "surprised": "😲", "curious": "🤔", "proud": "😤", "calm": "😌",
        "magical": "✨", "funny": "😄"
    }
    camera_icons = {
        "slow_zoom_in": "🔍", "slow_zoom_out": "🔭", "pan_left": "⬅️",
        "pan_right": "➡️", "pan_up": "⬆️", "pan_down": "⬇️", "static": "📷"
    }

    for scene in script.scenes:
        icon = emotion_icons.get(scene.emotion, "🎬")
        cam  = camera_icons.get(scene.camera_movement, "📷")
        sfx  = ", ".join(s.name for s in scene.sound_effects) if scene.sound_effects else "—"
        print(
            f"  [{scene.scene_number:02d}] {icon} {cam}  "
            f"{scene.duration_seconds}s  [{scene.emotion}]"
        )
        print(f"       Narration : {scene.narration}")
        print(f"       On screen : \"{scene.on_screen_text}\"")
        print(f"       SFX       : {sfx}")
        print(f"       Transition: {scene.transition}")
        print()

    print(divider)
    print(f"  FULL NARRATION (TTS input)")
    print(divider)
    print(f"  {script.full_narration}")
    print(divider)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Generate a kids' video script using Claude AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
            Examples:
              python pipeline/story_generator.py "a tiny dragon afraid of fire"
              python pipeline/story_generator.py "two frogs learning to share" --category friendship_and_emotions
              python pipeline/story_generator.py --batch automation/batch_topics.txt
              python pipeline/story_generator.py "magic rainbow cat" --no-save --json
        """)
    )
    parser.add_argument(
        "topic",
        nargs="?",
        help="Story topic, e.g. 'a bunny who is afraid of thunder'"
    )
    parser.add_argument(
        "--category",
        choices=config.STORY_CATEGORIES,
        help="Force a specific story category (optional — Claude auto-selects if omitted)"
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="Path to a text file with one topic per line (supports 'topic | category' format)"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save the script JSON to disk"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON output instead of human-readable summary"
    )
    parser.add_argument(
        "--load",
        metavar="SLUG",
        help="Load and display a previously saved script by slug"
    )

    args = parser.parse_args()

    # ── Load a previously saved script ──
    if args.load:
        script = StoryGenerator.load_script(args.load)
        if args.json:
            print(script.model_dump_json(indent=2))
        else:
            print_script_summary(script)
        return

    # ── Batch mode ──
    if args.batch:
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"Error: batch file not found: {args.batch}")
            sys.exit(1)

        topics = []
        for line in batch_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                topic, cat = [x.strip() for x in line.split("|", 1)]
                topics.append((topic, cat if cat in config.STORY_CATEGORIES else None))
            else:
                topics.append((line, None))

        gen = StoryGenerator()
        scripts = gen.generate_batch(topics)
        print(f"\nBatch complete: {len(scripts)}/{len(topics)} scripts generated.")
        return

    # ── Single topic mode ──
    if not args.topic:
        parser.print_help()
        sys.exit(1)

    gen = StoryGenerator()
    script = gen.generate(
        topic=args.topic,
        category=args.category,
        save=not args.no_save,
    )

    if args.json:
        print(script.model_dump_json(indent=2))
    else:
        print_script_summary(script)


if __name__ == "__main__":
    main()