"""
models.py — Pydantic data models shared across the entire pipeline.

Stage 1 produces  → VideoScript
Stage 2 produces  → RefinedScript   (richer prompts, negative prompts, colour palette)
Stage 3+ consumes → RefinedScript
"""

from pydantic import BaseModel, Field
from typing import Literal


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 1 MODELS
# ─────────────────────────────────────────────────────────────────────────────

class SoundEffect(BaseModel):
    name: str
    timing: Literal["start", "middle", "end"] = "start"
    volume: float = Field(default=0.7, ge=0.0, le=1.0)


class StoryScene(BaseModel):
    scene_number: int
    narration: str
    on_screen_text: str
    image_prompt: str
    camera_movement: Literal[
        "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right",
        "pan_up", "pan_down", "static",
    ]
    duration_seconds: int = Field(default=5, ge=3, le=8)
    emotion: Literal[
        "happy", "excited", "sad", "scared", "surprised",
        "curious", "proud", "calm", "magical", "funny"
    ]
    sound_effects: list[SoundEffect] = Field(default_factory=list)
    transition: Literal["cut", "fade", "wipe"] = "cut"


class VideoScript(BaseModel):
    title: str
    slug: str
    category: Literal[
        "animal_adventure", "friendship_and_emotions", "magic_and_fantasy",
        "learning_and_educational", "bedtime_and_calming",
    ]
    moral: str
    main_character: str
    setting: str
    background_music_mood: Literal[
        "playful", "adventurous", "magical", "calm_and_soothing",
        "dramatic", "funny", "heartwarming"
    ]
    youtube_description: str
    youtube_tags: list[str]
    thumbnail_concept: str
    scenes: list[StoryScene]

    @property
    def total_duration_seconds(self) -> int:
        return sum(s.duration_seconds for s in self.scenes)

    @property
    def full_narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)


# ─────────────────────────────────────────────────────────────────────────────
#  STAGE 2 MODELS
# ─────────────────────────────────────────────────────────────────────────────

class RefinedScene(BaseModel):
    """
    One scene after Stage 2 refinement.
    Adds: punchy on_screen_text, stronger image_prompt,
          negative_prompt, colour_palette.
    """
    # Carried over unchanged from Stage 1
    scene_number: int
    narration: str
    camera_movement: Literal[
        "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right",
        "pan_up", "pan_down", "static",
    ]
    duration_seconds: int
    emotion: Literal[
        "happy", "excited", "sad", "scared", "surprised",
        "curious", "proud", "calm", "magical", "funny"
    ]
    sound_effects: list[SoundEffect] = Field(default_factory=list)
    transition: Literal["cut", "fade", "wipe"] = "cut"

    # Refined fields
    on_screen_text: str = Field(
        description="1-4 punchy emotional words for the bold subtitle. e.g. 'OH NO!', 'YOU DID IT!'"
    )
    image_prompt: str = Field(
        description="Enhanced 80-140 word prompt with character, action, expression, background, lighting, composition, style suffix."
    )
    negative_prompt: str = Field(
        description="What to exclude from this image. Always starts with global exclusions then adds scene-specific ones."
    )
    colour_palette: list[str] = Field(
        description="3 dominant hex colour codes for this scene. e.g. ['#FFD700', '#FF6B9D', '#7EC8E3']"
    )
    fal_aspect_ratio: Literal["9:16", "16:9", "1:1", "4:3", "3:4"] = "9:16"


class RefinedScript(BaseModel):
    """
    Fully refined video script — primary input for all stages 3 through 10.
    Saved as output/stories/<slug>_refined.json.
    """
    # Carried over from Stage 1
    title: str
    slug: str
    category: Literal[
        "animal_adventure", "friendship_and_emotions", "magic_and_fantasy",
        "learning_and_educational", "bedtime_and_calming",
    ]
    moral: str
    main_character: str
    setting: str
    background_music_mood: Literal[
        "playful", "adventurous", "magical", "calm_and_soothing",
        "dramatic", "funny", "heartwarming"
    ]
    youtube_description: str
    youtube_tags: list[str]

    # Refined top-level fields
    thumbnail_concept: str = Field(
        description="CTR-optimised thumbnail description with character pose, expression, background, text overlay, dominant colour."
    )
    thumbnail_negative_prompt: str = Field(
        description="Negative prompt for thumbnail generation."
    )
    global_style_suffix: str = Field(
        description="Art style string appended to every scene image prompt for visual consistency."
    )
    global_negative_prompt: str = Field(
        description="Negative prompt applied to every scene image."
    )
    colour_story: str = Field(
        description="One sentence describing the colour journey across the full video."
    )
    scenes: list[RefinedScene]

    @property
    def total_duration_seconds(self) -> int:
        return sum(s.duration_seconds for s in self.scenes)

    @property
    def full_narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)