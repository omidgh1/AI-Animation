"""
scene_refiner.py — Stage 2: Scene Refinement & Image Prompt Enhancement

Reads the VideoScript from Stage 1 and produces a RefinedScript with:
  - Punchy, intentional on_screen_text (not mechanically sliced)
  - Stronger image prompts with composition, lighting and depth language
  - Negative prompts per scene (for Fal.ai Flux)
  - Colour palette per scene (3 hex codes)
  - Global style suffix and global negative prompt
  - CTR-optimised thumbnail concept

Why a separate stage?
  Stage 1 focuses on story structure and narration — Claude is thinking like a writer.
  Stage 2 focuses on visual quality — Claude thinks like an art director.
  Separating the concerns produces significantly better image prompts.
"""

import anthropic
import json
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.models import VideoScript, RefinedScript, RefinedScene, SoundEffect


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = dedent("""
    You are a senior art director and visual storyteller specialising in children's
    animated short-form video for YouTube Shorts, TikTok, and Instagram Reels.

    You receive a kids' story script and your job is to elevate every scene's
    visual quality for AI image generation using Fal.ai Flux 1.1 Pro.

    YOUR RESPONSIBILITIES:

    1. ON_SCREEN_TEXT — rewrite every scene's subtitle to be:
       - 1 to 4 words maximum
       - Emotionally punchy and age-appropriate
       - The peak emotional beat of that scene
       - Written in ALL CAPS for hook scenes, Title Case for calm scenes
       - Examples of GOOD on_screen_text:
           "OH NO!" / "Try Again!" / "YOU DID IT!" / "Best Friends!" /
           "So Scary..." / "ALMOST THERE!" / "The Secret!" / "Sweet Dreams!"
       - Examples of BAD on_screen_text (do not produce):
           "Spark the tiny dragon!" (too long, mechanical slice of narration)
           "But when Dragon School!" (grammatically broken)

    2. IMAGE_PROMPT — enhance every scene prompt to include:
       - Character: exact physical description verbatim from main_character field
       - Action: precise body language and gesture
       - Expression: specific facial emotion (e.g. "eyes wide with wonder, mouth open in a small O")
       - Foreground: what is immediately in front
       - Background: layered depth — near, mid, far elements
       - Lighting: specific quality (e.g. "warm golden hour sidelight", "soft diffused morning glow",
                   "cool moonlight with rim lighting", "magical sparkle particles catching light")
       - Atmosphere: mood-enhancing details (mist, lens flare, bokeh, particle effects)
       - ALWAYS end with the global_style_suffix exactly as provided
       - 80 to 140 words total

    3. NEGATIVE_PROMPT — for every scene, write what to exclude:
       - Always include: "text, words, letters, watermark, signature, ugly, deformed,
         extra limbs, bad anatomy, blurry, low quality, dark, scary, violent,
         adult content, realistic photo, 3d render, anime, manga, grainy, noise"
       - Add scene-specific exclusions (e.g. for a night scene: "bright daylight";
         for a calm scene: "fire, explosions, chaos")

    4. COLOUR_PALETTE — choose 3 hex colour codes that define each scene's mood:
       - Use warm colours (oranges, yellows, pinks) for happy/excited scenes
       - Use cool colours (blues, purples) for sad/scared scenes
       - Use teals and greens for calm/magical scenes
       - Use bright saturated rainbow colours for celebration scenes
       - Colours must look good together and reflect the emotion

    5. GLOBAL FIELDS — for the whole video:
       - global_style_suffix: one consistent art style string for ALL scene prompts
       - global_negative_prompt: baseline exclusions for ALL scenes
       - thumbnail_concept: rewrite to be CTR-optimised — child sees it and MUST click
       - thumbnail_negative_prompt: exclusions for the thumbnail
       - colour_story: one sentence arc of colours across the whole video

    FLUX 1.1 PRO PROMPT TIPS:
       - Flux responds well to: specific textures, lighting adjectives, composition terms
       - Use terms like: "rim lighting", "volumetric light rays", "bokeh background",
         "shallow depth of field", "rule of thirds composition", "leading lines",
         "colour grading: warm/cool/pastel"
       - Flux does NOT need negative prompts as strongly as SD, but they still help
       - Keep character description consistent — copy it verbatim every time

    OUTPUT FORMAT:
    Return ONLY valid JSON matching the schema. No markdown, no explanation.
    Start with { and end with }.
""").strip()





# ─────────────────────────────────────────────────────────────────────────────
#  SCENE REFINER CLASS
# ─────────────────────────────────────────────────────────────────────────────


def _script_with_scenes(script: VideoScript, scenes) -> VideoScript:
    """Return a copy of the script with only the given subset of scenes."""
    data = script.model_dump()
    data["scenes"] = [s.model_dump() for s in scenes]
    return VideoScript(**data)


def _build_refine_prompt(script: VideoScript, is_first_pass: bool = True) -> str:
    """
    Build the refinement prompt for one pass.

    is_first_pass=True  → include global fields in required output
    is_first_pass=False → only ask for scenes (no global fields needed)
    """
    scenes_summary = []
    for s in script.scenes:
        scenes_summary.append({
            "scene_number": s.scene_number,
            "narration": s.narration,
            "current_on_screen_text": s.on_screen_text,
            "current_image_prompt": s.image_prompt,
            "camera_movement": s.camera_movement,
            "duration_seconds": s.duration_seconds,
            "emotion": s.emotion,
            "sound_effects": [
                {"name": sfx.name, "timing": sfx.timing, "volume": sfx.volume}
                for sfx in s.sound_effects
            ],
            "transition": s.transition,
        })

    scene_nums = [s.scene_number for s in script.scenes]
    scene_range = f"scenes {scene_nums[0]}-{scene_nums[-1]}"

    if is_first_pass:
        output_spec = """{{
  "title": "{title}",
  "slug": "{slug}",
  "category": "{category}",
  "moral": "{moral}",
  "main_character": "{main_character}",
  "setting": "{setting}",
  "background_music_mood": "{background_music_mood}",
  "youtube_description": <keep unchanged>,
  "youtube_tags": <keep unchanged>,
  "thumbnail_concept": "<rewritten CTR-optimised thumbnail>",
  "thumbnail_negative_prompt": "<thumbnail negative prompt>",
  "global_style_suffix": "<consistent art style for all 12 scenes>",
  "global_negative_prompt": "<baseline negatives for all scenes>",
  "colour_story": "<one sentence colour arc>",
  "scenes": [ ... {scene_range} refined scenes ... ]
}}""".format(
    title=script.title, slug=script.slug, category=script.category,
    moral=script.moral, main_character=script.main_character,
    setting=script.setting, background_music_mood=script.background_music_mood,
    scene_range=scene_range
)
        extra_instruction = (
            "Include ALL global fields (thumbnail_concept, thumbnail_negative_prompt, "
            "global_style_suffix, global_negative_prompt, colour_story) "
            "plus the refined scenes."
        )
    else:
        output_spec = """{{
  "scenes": [ ... {scene_range} refined scenes only ... ]
}}""".format(scene_range=scene_range)
        extra_instruction = (
            "Return ONLY a JSON object with a single key 'scenes' containing "
            f"the {len(script.scenes)} refined scenes for {scene_range}. "
            "No global fields needed — just the scenes array."
        )

    return f"""Refine these kids video scenes for high-quality AI image generation with Fal.ai Flux.

STORY CONTEXT:
Title         : {script.title}
Main character: {script.main_character}
Setting       : {script.setting}
Moral         : {script.moral}
Music mood    : {script.background_music_mood}

SCENES TO REFINE ({scene_range}):
{json.dumps(scenes_summary, indent=2)}

INSTRUCTIONS:
1. Keep narration text EXACTLY unchanged — not a single word modified
2. Keep scene_number, camera_movement, duration_seconds, emotion, sound_effects, transition UNCHANGED
3. Rewrite on_screen_text: 1-4 punchy emotional words (e.g. "OH NO!", "YOU DID IT!", "So scared...")
4. Enhance image_prompt to 80-140 words with: character description verbatim, specific action,
   facial expression, foreground/mid/background depth, lighting quality, atmosphere details
5. Add negative_prompt: start with global exclusions, add scene-specific ones
6. Add colour_palette: 3 hex codes matching the scene emotion
7. Set fal_aspect_ratio: "9:16" always
{extra_instruction}

REQUIRED OUTPUT STRUCTURE:
{output_spec}

Return ONLY valid JSON. No markdown fences. No explanation. Start with {{ end with }}."""


class SceneRefiner:
    """
    Refines a Stage 1 VideoScript into a Stage 2 RefinedScript.

    Example:
        from pipeline.story_generator import StoryGenerator
        from pipeline.scene_refiner import SceneRefiner

        script = StoryGenerator.load_script("sparks-big-brave-moment")
        refiner = SceneRefiner()
        refined = refiner.refine(script)
        print(refined.scenes[0].on_screen_text)   # "OH NO!"
        print(refined.global_style_suffix)
    """

    def __init__(self):
        if not config.ANTHROPIC_API_KEY:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not found. "
                "Create a .env file in the project root with your API key."
            )
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    @retry(
        stop=stop_after_attempt(config.MAX_RETRIES),
        wait=wait_exponential(min=config.RETRY_WAIT_MIN_SEC, max=config.RETRY_WAIT_MAX_SEC),
        retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.RateLimitError)),
        reraise=True,
    )
    def _call_claude(self, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=config.STORY_MODEL,
            max_tokens=config.REFINE_MAX_TOKENS,
            temperature=0.7,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Detect truncation — stop_reason "max_tokens" means response was cut off
        if response.stop_reason == "max_tokens":
            raise ValueError(
                "Response was truncated (hit max_tokens). "
                "This will be handled by the two-pass split strategy."
            )
        return response.content[0].text

    def _normalize(self, data: dict, original: VideoScript) -> dict:
        """
        Repair Stage 2 response before Pydantic validation.
        Ensures all required fields exist, narration is preserved,
        sound_effects are proper dicts, and colour_palette has valid hex codes.
        """
        import re

        # ── Top-level fields — fall back to original if missing ───────────────
        for field in ["title", "slug", "category", "moral", "main_character",
                      "setting", "background_music_mood", "youtube_description",
                      "youtube_tags"]:
            if field not in data:
                data[field] = getattr(original, field)

        # youtube_tags: fix string → list
        tags = data.get("youtube_tags", [])
        if isinstance(tags, str):
            data["youtube_tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        elif not tags:
            data["youtube_tags"] = getattr(original, "youtube_tags", ["kids stories"])

        if "thumbnail_concept" not in data:
            data["thumbnail_concept"] = original.thumbnail_concept

        if "thumbnail_negative_prompt" not in data:
            data["thumbnail_negative_prompt"] = (
                "text, watermark, blurry, dark, scary, realistic, photo, "
                "3d render, multiple characters crowding foreground, cluttered background, "
                "ugly, deformed, low quality"
            )

        if "global_style_suffix" not in data:
            data["global_style_suffix"] = (
                "children's book illustration style, Pixar-inspired, bright cheerful colours, "
                "soft cel-shading, clean outlines, cute friendly design, "
                "9:16 vertical composition, high quality, detailed"
            )

        if "global_negative_prompt" not in data:
            data["global_negative_prompt"] = (
                "text, words, letters, watermark, signature, ugly, deformed, "
                "extra limbs, bad anatomy, blurry, low quality, dark, scary, violent, "
                "adult content, realistic photo, 3d render, anime, manga, grainy, noise"
            )

        if "colour_story" not in data:
            data["colour_story"] = (
                "Warm sunny yellows open the story, cool blues carry the sad moment, "
                "then rainbow celebration colours burst through at the end."
            )

        # ── Scene-level fixes ─────────────────────────────────────────────────
        orig_scenes = {s.scene_number: s for s in original.scenes}
        valid_emotions    = {"happy","excited","sad","scared","surprised",
                             "curious","proud","calm","magical","funny"}
        valid_cameras     = {"slow_zoom_in","slow_zoom_out","pan_left","pan_right",
                             "pan_up","pan_down","static"}
        valid_transitions = {"cut","fade","wipe"}
        hex_re = re.compile(r'^#[0-9A-Fa-f]{6}$')

        default_palettes = {
            "happy":     ["#FFD700", "#FF9500", "#FFF0A0"],
            "excited":   ["#FF6B6B", "#FFD93D", "#6BCB77"],
            "sad":       ["#6B8CFF", "#B0C4DE", "#9B9BB4"],
            "scared":    ["#7B68EE", "#483D8B", "#B0A8D9"],
            "surprised": ["#FF6B9D", "#FFD700", "#A8E6CF"],
            "curious":   ["#4ECDC4", "#45B7D1", "#FFA07A"],
            "proud":     ["#FFD700", "#FF8C00", "#FFF8DC"],
            "calm":      ["#A8E6CF", "#7EC8E3", "#DCEDC8"],
            "magical":   ["#C77DFF", "#7B2FBE", "#E0AAFF"],
            "funny":     ["#FFD93D", "#FF6B6B", "#6BCB77"],
        }

        for scene in data.get("scenes", []):
            n = scene.get("scene_number", 0)
            orig = orig_scenes.get(n)

            # ALWAYS preserve original narration — never let Claude change it
            if orig:
                scene["narration"] = orig.narration

            # on_screen_text: clean up if too long or missing
            ost = scene.get("on_screen_text", "")
            if not ost or len(ost.split()) > 5:
                if orig:
                    # Take most emotional word(s) from narration
                    words = orig.narration.split()
                    scene["on_screen_text"] = " ".join(words[:3]).rstrip(".,") + "!"
                else:
                    scene["on_screen_text"] = "Watch this!"

            # image_prompt: ensure style suffix present
            prompt = scene.get("image_prompt", "")
            if not prompt and orig:
                prompt = orig.image_prompt
            if data.get("global_style_suffix") and \
               data["global_style_suffix"][:20] not in prompt:
                prompt = prompt.rstrip() + ", " + data["global_style_suffix"]
            scene["image_prompt"] = prompt

            # negative_prompt: must exist
            if not scene.get("negative_prompt"):
                scene["negative_prompt"] = data.get("global_negative_prompt",
                    "text, watermark, ugly, deformed, blurry, dark, scary, realistic photo")

            # colour_palette: must be list of 3 valid hex codes
            palette = scene.get("colour_palette", [])
            if not isinstance(palette, list):
                palette = []
            valid_palette = [c for c in palette if isinstance(c, str) and hex_re.match(c)]
            if len(valid_palette) < 3:
                emotion = scene.get("emotion", "happy")
                scene["colour_palette"] = default_palettes.get(emotion, ["#FFD700","#FF9500","#FFF0A0"])
            else:
                scene["colour_palette"] = valid_palette[:3]

            # Restore unchanged fields from original
            if orig:
                if scene.get("camera_movement") not in valid_cameras:
                    scene["camera_movement"] = orig.camera_movement
                if scene.get("emotion") not in valid_emotions:
                    scene["emotion"] = orig.emotion
                if scene.get("transition") not in valid_transitions:
                    scene["transition"] = orig.transition
                try:
                    scene["duration_seconds"] = max(3, min(8, int(
                        scene.get("duration_seconds", orig.duration_seconds))))
                except (TypeError, ValueError):
                    scene["duration_seconds"] = orig.duration_seconds

            # sound_effects: strings → dicts
            fixed_sfx = []
            for sfx in scene.get("sound_effects", []):
                if isinstance(sfx, str):
                    fixed_sfx.append({"name": sfx, "timing": "start", "volume": 0.6})
                elif isinstance(sfx, dict):
                    sfx.setdefault("name", "sound effect")
                    sfx.setdefault("timing", "start")
                    sfx.setdefault("volume", 0.6)
                    if sfx["timing"] not in {"start", "middle", "end"}:
                        sfx["timing"] = "start"
                    fixed_sfx.append(sfx)
            if not fixed_sfx and orig:
                fixed_sfx = [
                    {"name": s.name, "timing": s.timing, "volume": s.volume}
                    for s in orig.sound_effects
                ]
            scene["sound_effects"] = fixed_sfx

            # fal_aspect_ratio default
            scene.setdefault("fal_aspect_ratio", "9:16")

        return data

    def _parse_and_validate(self, raw_json: str, original: VideoScript) -> RefinedScript:
        """Parse, normalize, and validate the Stage 2 response."""
        text = raw_json.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Stage 2 returned invalid JSON: {e}\n\nRaw:\n{raw_json[:500]}")

        data = self._normalize(data, original)

        try:
            refined = RefinedScript(**data)
        except Exception as e:
            raise ValueError(f"RefinedScript validation failed after normalization: {e}")

        if len(refined.scenes) != config.NUM_SCENES:
            raise ValueError(f"Expected {config.NUM_SCENES} scenes, got {len(refined.scenes)}")

        return refined

    def _save_refined(self, refined: RefinedScript) -> Path:
        """Save refined script as output/stories/<slug>_refined.json."""
        path = Path(config.STORIES_DIR) / f"{refined.slug}_refined.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(refined.model_dump_json(indent=2))
        return path

    def refine(
        self,
        script: VideoScript,
        save: bool = True,
        main_character: dict | None = None,
        supporting_characters: list[dict] | None = None,
    ) -> RefinedScript:
        """
        Refine a Stage 1 VideoScript into a Stage 2 RefinedScript.

        Automatically splits scenes into batches of SCENES_PER_PASS (6) so each
        Claude call stays well within REFINE_MAX_TOKENS.  Works for any scene count:
          12 scenes  -> 2 passes  (6 + 6)
          30 scenes  -> 5 passes  (6 x 4 + 6)
          60 scenes  -> 10 passes (6 x 10)
          90 scenes  -> 15 passes
        Pass 1 also generates all global fields (style suffix, colour story, etc.).
        All passes are merged into one complete RefinedScript.

        If main_character is provided, the flux_anchor is enforced in every image
        prompt after each pass — Claude cannot drift the character appearance.
        """
        import math
        SCENES_PER_PASS = 6

        n_scenes = len(script.scenes)
        n_passes = math.ceil(n_scenes / SCENES_PER_PASS)

        print(f"\n{'='*60}")
        print(f"  Stage 2: Refining '{script.title}'")
        print(f"{'='*60}")
        print(f"  Model    : {config.STORY_MODEL}")
        print(f"  Scenes   : {n_scenes}")
        print(f"  Passes   : {n_passes}  ({SCENES_PER_PASS} scenes each)")
        print(f"  Max tok  : {config.REFINE_MAX_TOKENS} per pass")
        if main_character:
            print(f"  Character: {main_character['name']} (flux anchor locked)")
        print()

        t_start = time.time()
        raw_passes = []

        for pass_num in range(n_passes):
            slice_start = pass_num * SCENES_PER_PASS
            slice_end   = slice_start + SCENES_PER_PASS
            batch       = script.scenes[slice_start:slice_end]
            is_first    = (pass_num == 0)

            scene_nums = [s.scene_number for s in batch]
            label = f"scenes {scene_nums[0]}-{scene_nums[-1]}"
            if is_first:
                label = "global fields + " + label

            print(f"  Pass {pass_num + 1}/{n_passes} ({label})...", end="", flush=True)
            t_pass = time.time()

            script_batch = _script_with_scenes(script, batch)
            prompt       = _build_refine_prompt(script_batch, is_first_pass=is_first)
            raw          = self._call_claude(prompt)
            raw_passes.append(raw)

            print(f" done ({time.time() - t_pass:.1f}s)")

        elapsed = time.time() - t_start

        # ── Merge all passes ──────────────────────────────────────────────────
        print("  Merging and validating...", end="", flush=True)
        refined = self._merge_all_passes(raw_passes, script)
        print(" done")

        print(f"  Total time : {elapsed:.1f}s")

        # ── Flux anchor enforcement ──────────────────────────────────────────
        # If a locked character was passed, verify every scene image_prompt
        # contains the flux_anchor. If Claude omitted it, append it now.
        # This is the final guarantee of visual consistency across all scenes.
        if main_character and main_character.get("flux_anchor"):
            anchor       = main_character["flux_anchor"]
            anchor_check = anchor[:30].lower()
            fixed        = 0
            updated_scenes = []
            for scene in refined.scenes:
                if anchor_check not in scene.image_prompt.lower():
                    new_prompt = scene.image_prompt.rstrip(" .,") + f", {anchor}"
                    updated_scenes.append(scene.model_copy(update={"image_prompt": new_prompt}))
                    fixed += 1
                else:
                    updated_scenes.append(scene)
            if fixed:
                refined = refined.model_copy(update={"scenes": updated_scenes})
                print(f"  ⚙️   Flux anchor injected into {fixed}/{len(refined.scenes)} scenes.")

            # Enforce supporting character anchors in scenes that mention them by name
            if supporting_characters:
                for sup in supporting_characters:
                    sup_anchor = sup.get("flux_anchor", "")
                    sup_name   = sup.get("name", "").lower()
                    if not sup_anchor:
                        continue
                    sup_check = sup_anchor[:30].lower()
                    updated_scenes = []
                    for scene in refined.scenes:
                        prompt_lower = scene.image_prompt.lower()
                        if sup_name in prompt_lower and sup_check not in prompt_lower:
                            new_prompt = scene.image_prompt.rstrip(" .,") + f", {sup_anchor}"
                            updated_scenes.append(scene.model_copy(update={"image_prompt": new_prompt}))
                        else:
                            updated_scenes.append(scene)
                    refined = refined.model_copy(update={"scenes": updated_scenes})

        if save:
            path = self._save_refined(refined)
            print(f"  Saved      : {path}")

        print()
        print(f"  Global style : {refined.global_style_suffix[:70]}...")
        print(f"  Colour story : {refined.colour_story}")
        print()

        return refined

    def _merge_all_passes(self, raw_passes: list, original: VideoScript) -> RefinedScript:
        """
        Parse every pass and merge into one complete RefinedScript.
        Pass 0 provides global fields; all passes contribute their scenes in order.
        """
        def parse_raw(raw: str) -> dict:
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return json.loads(text)

        parsed = []
        for i, raw in enumerate(raw_passes):
            try:
                parsed.append(parse_raw(raw))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Pass {i + 1} returned invalid JSON: {e}\n"
                    f"Raw (first 400 chars):\n{raw[:400]}"
                )

        # Global fields come from Pass 0 (first pass)
        merged = dict(parsed[0])

        # Collect all scenes from every pass, in order
        all_scenes = []
        for data in parsed:
            all_scenes.extend(data.get("scenes", []))

        merged["scenes"] = all_scenes

        merged = self._normalize(merged, original)

        try:
            refined = RefinedScript(**merged)
        except Exception as e:
            raise ValueError(f"RefinedScript validation failed after merge: {e}")

        if len(refined.scenes) != config.NUM_SCENES:
            raise ValueError(
                f"Expected {config.NUM_SCENES} scenes after merging {len(raw_passes)} passes, "
                f"got {len(refined.scenes)}. "
                f"Scene counts per pass: {[len(p.get('scenes', [])) for p in parsed]}"
            )

        return refined

    @staticmethod
    def load_refined(slug_or_path: str) -> RefinedScript:
        """Load a previously saved refined script by slug or full path."""
        path = Path(slug_or_path)
        if not path.suffix:
            path = Path(config.STORIES_DIR) / f"{slug_or_path}_refined.json"
        if not path.exists():
            raise FileNotFoundError(f"Refined script not found: {path}")
        with open(path, encoding="utf-8") as f:
            return RefinedScript(**json.load(f))


# ─────────────────────────────────────────────────────────────────────────────
#  PRETTY PRINTER
# ─────────────────────────────────────────────────────────────────────────────

def print_refined_summary(refined: RefinedScript):
    div = "─" * 60
    print(f"\n{div}")
    print(f"  REFINED SCRIPT SUMMARY")
    print(div)
    print(f"  Title         : {refined.title}")
    print(f"  Duration      : ~{refined.total_duration_seconds}s")
    print(f"  Colour story  : {refined.colour_story}")
    print(f"\n  Style suffix  : {refined.global_style_suffix}")
    print(f"  Global neg.   : {refined.global_negative_prompt[:80]}...")
    print(f"\n  Thumbnail     : {refined.thumbnail_concept[:100]}...")
    print(f"\n{div}")
    print(f"  REFINED SCENE BREAKDOWN")
    print(div)

    emotion_icons = {
        "happy":"😊","excited":"🤩","sad":"😢","scared":"😨","surprised":"😲",
        "curious":"🤔","proud":"😤","calm":"😌","magical":"✨","funny":"😄"
    }

    for scene in refined.scenes:
        icon = emotion_icons.get(scene.emotion, "🎬")
        palette_str = "  ".join(scene.colour_palette)
        print(f"  [{scene.scene_number:02d}] {icon}  [{scene.emotion}]  {palette_str}")
        print(f"       Subtitle  : \"{scene.on_screen_text}\"")
        print(f"       Narration : {scene.narration[:70]}...")
        print(f"       Prompt    : {scene.image_prompt[:80]}...")
        print(f"       Neg.prompt: {scene.negative_prompt[:60]}...")
        print()

    print(div)
    print(f"  FULL NARRATION")
    print(div)
    print(f"  {refined.full_narration[:200]}...")
    print(div)