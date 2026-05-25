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
from prompts.loader import load_prompt


# ─────────────────────────────────────────────────────────────────────────────
#  SYSTEM PROMPT
#  This is the core of Stage 1. It tells Claude exactly what to produce.
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(num_scenes: int) -> str:
    """
    Build the story generation system prompt dynamically based on scene count.
    Supports short videos (12 scenes) and long videos (30, 60, 90 scenes).
    """
    NL = "\n"

    # ── Emotion arc ────────────────────────────────────────────────────────────
    if num_scenes <= 12:
        emotion_map = {
            1: "surprised", 2: "happy", 3: "scared", 4: "sad",
            5: "sad", 6: "surprised", 7: "curious", 8: "excited",
            9: "excited", 10: "excited", 11: "proud", 12: "calm",
        }
        emotions = [emotion_map.get(i, "happy") for i in range(1, num_scenes + 1)]
    else:
        act1_end = num_scenes // 5
        act2_end = num_scenes * 4 // 5
        emotions = []
        for i in range(1, num_scenes + 1):
            if i == 1:
                emotions.append("surprised")
            elif i <= act1_end:
                emotions.append("happy")
            elif i == act1_end + 1:
                emotions.append("scared")
            elif i <= act1_end + 3:
                emotions.append("sad")
            elif i == act1_end + 4:
                emotions.append("surprised")
            elif i <= act2_end - (num_scenes // 10):
                emotions.append("curious")
            elif i <= act2_end:
                emotions.append("excited")
            elif i == num_scenes - 1:
                emotions.append("proud")
            elif i == num_scenes:
                emotions.append("calm")
            else:
                emotions.append("excited")

    # ── Scene structure block ───────────────────────────────────────────────────
    if num_scenes <= 12:
        labels = {
            1: "HOOK",  2: "WORLD",        3: "PROBLEM",       4: "ATTEMPT 1",
            5: "REACTION", 6: "HELPER",    7: "TEAMWORK",      8: "ALMOST",
            9: "BREAKTHROUGH", 10: "CELEBRATION", 11: "LESSON", 12: "ENDING",
        }
        scene_lines = []
        for i in range(1, num_scenes + 1):
            label = labels.get(i, "SCENE " + str(i))
            scene_lines.append(
                '    Scene {:02d} - {}: emotion: "{}"'.format(i, label, emotions[i - 1])
            )
        scene_structure = NL.join(scene_lines)
        duration_note   = "~{} seconds ({} scenes x ~5s each)".format(num_scenes * 5, num_scenes)
        structure_note  = "Scene 01 = HOOK (start mid-action), Scene {} = ENDING (warm goodbye)".format(num_scenes)
    else:
        act1_end = num_scenes // 5
        act2_end = num_scenes * 4 // 5
        duration_note = "~{} minutes ({} scenes x ~10s each)".format(
            (num_scenes * 10) // 60, num_scenes
        )
        structure_note = (
            "ACT 1 SETUP (scenes 1-{}): world, character, normal life. "
            "ACT 2 ADVENTURE (scenes {}-{}): problem, attempts, helpers, teamwork, escalation. "
            "ACT 3 RESOLUTION (scenes {}-{}): breakthrough, celebration, lesson, warm ending."
        ).format(act1_end, act1_end + 1, act2_end, act2_end + 1, num_scenes)
        scene_structure = (
            "    (Generate ALL {} scenes following the 3-act arc above)\n"
            "    Sample emotions: scene 1={}, scene {}={}, scene {}={}"
        ).format(
            num_scenes,
            emotions[0],
            num_scenes // 2, emotions[num_scenes // 2 - 1],
            num_scenes, emotions[-1],
        )

    return load_prompt(
        "story_system",
        num_scenes=num_scenes,
        duration_note=duration_note,
        structure_note=structure_note,
        scene_structure=scene_structure,
    )

# Build system prompt using current config
SYSTEM_PROMPT = _build_system_prompt(config.NUM_SCENES)


# ─────────────────────────────────────────────────────────────────────────────
#  JSON SCHEMA  (passed to Claude to enforce exact output structure)
# ─────────────────────────────────────────────────────────────────────────────

def _build_schema(num_scenes: int) -> dict:
    """Build the JSON schema dynamically based on scene count."""
    return {
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
            "minItems": num_scenes,
            "maxItems": num_scenes,
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
    }  # end of schema dict returned by _build_schema()


VIDEO_SCRIPT_SCHEMA = _build_schema(config.NUM_SCENES)


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

    def _build_user_prompt(
        self,
        topic: str,
        category: str | None = None,
        character_block: str | None = None,
    ) -> str:
        """
        Build the user-facing prompt.
        If character_block is provided (from character_manager), it is injected
        before the story instructions so Claude cannot invent a new character look.
        """
        # Rebuild system prompt in case config.NUM_SCENES changed at runtime
        global SYSTEM_PROMPT, VIDEO_SCRIPT_SCHEMA
        SYSTEM_PROMPT = _build_system_prompt(config.NUM_SCENES)
        VIDEO_SCRIPT_SCHEMA = _build_schema(config.NUM_SCENES)
        category_hint = ""
        if category and category in config.STORY_CATEGORIES:
            category_hint = f"\nStory category: {category.replace('_', ' ')}"

        char_section = ""
        if character_block:
            char_section = (
                f"{character_block}\n\n"
                "IMPORTANT: The character definitions above are LOCKED.\n"
                "Copy the flux_anchor verbatim into every scene's image_prompt field.\n"
                "Use the visual_description verbatim as the main_character field.\n"
                "Do NOT change hair colour, eye colour, clothing, or any other feature."
            )

        return load_prompt(
            "story_user",
            topic=topic,
            category_hint=category_hint,
            target_duration=config.TARGET_VIDEO_SEC,
            num_scenes=config.NUM_SCENES,
            char_section=char_section,
        )

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
        max_tokens = config.story_max_tokens_for(config.NUM_SCENES)
        response = self.client.messages.create(
            model=config.STORY_MODEL,
            max_tokens=max_tokens,
            temperature=config.STORY_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
        )
        if response.stop_reason == "max_tokens":
            raise ValueError(
                f"Stage 1 response was truncated at {max_tokens} tokens "
                f"for {config.NUM_SCENES} scenes. "
                "This should not happen — report this as a bug."
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

        # Claude sometimes uses "topic" or "story_title" instead of "title"
        if "title" not in data:
            data["title"] = (
                data.pop("story_title", None)
                or data.pop("topic", None)
                or "A Kids Adventure"
            )

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
        main_character: dict | None = None,
        supporting_characters: list[dict] | None = None,
    ) -> VideoScript:
        """
        Generate a complete video script from a topic string.

        Args:
            topic:                 One-line story topic, e.g. "a bunny afraid of thunder"
            category:              Optional story category override. If None, Claude chooses.
            save:                  If True, saves the JSON to output/stories/.
            main_character:        Character dict from character_manager.load_character().
                                   If set, locks the character design so Claude cannot
                                   invent a new look.
            supporting_characters: List of supporting character dicts (optional).

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
        if main_character:
            ep = main_character.get("episode_count", 0) + 1
            print(f"  Character: {main_character['name']} (Episode {ep} of '{main_character.get('series_name', '')}')")
        if supporting_characters:
            print(f"  Supporting: {', '.join(c['name'] for c in supporting_characters)}")
        print()

        # Build character instruction block if a character is provided
        character_block = None
        if main_character:
            from character_manager import build_character_block, build_topic_with_character
            ep_num = main_character.get("episode_count", 0) + 1
            character_block = build_character_block(main_character, supporting_characters)
            topic = build_topic_with_character(topic, main_character, supporting_characters, ep_num)

        t_start = time.time()
        user_prompt = self._build_user_prompt(topic, category, character_block=character_block)

        print("  Calling Claude API...", end="", flush=True)
        raw_response = self._call_claude(user_prompt)
        elapsed = time.time() - t_start
        print(f" done in {elapsed:.1f}s")

        print("  Parsing and validating JSON...", end="", flush=True)
        script = self._parse_and_validate(raw_response)
        print(" done")

        # If a locked character was provided, override whatever Claude wrote
        # for main_character to guarantee it matches the character file exactly.
        if main_character:
            from character_manager import build_main_character_string
            locked = build_main_character_string(main_character)
            script = script.model_copy(update={"main_character": locked})

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