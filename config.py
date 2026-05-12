"""
config.py — Central configuration for the AI Kids Video Generator pipeline.
Copy .env.example to .env and fill in your API keys before running.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Always load .env from project root regardless of working directory
_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_ROOT / ".env", override=True)

# ─────────────────────────────────────────────
#  API KEYS  (loaded from .env — never hardcode)
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "").strip().strip("'").strip('"')
FAL_KEY            = os.getenv("FAL_KEY", "").strip()
PIXABAY_API_KEY    = os.getenv("PIXABAY_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()

# ─────────────────────────────────────────────
#  CLAUDE MODEL SETTINGS
# ─────────────────────────────────────────────
STORY_MODEL        = "claude-sonnet-4-5"
STORY_MAX_TOKENS   = 4096    # overridden dynamically — see story_max_tokens_for()

def story_max_tokens_for(num_scenes: int) -> int:
    """
    Return the right max_tokens for Claude Stage 1 based on scene count.
    Each scene needs ~200 tokens of output (narration + image prompt + fields).
    Add 2048 headroom for top-level fields.
    Capped at 16384 (Claude's safe output limit for complex JSON).
    """
    per_scene = 250
    headroom  = 2048
    return min(16384, max(4096, num_scenes * per_scene + headroom))
REFINE_MAX_TOKENS  = 8192
STORY_TEMPERATURE  = 1.0

# ─────────────────────────────────────────────
#  STORY SETTINGS
# ─────────────────────────────────────────────
NUM_SCENES         = 12        # 12 scenes × ~5s = ~60s video
SCENE_DURATION_SEC = 5
TARGET_VIDEO_SEC   = 60

STORY_CATEGORIES = [
    "animal_adventure",
    "friendship_and_emotions",
    "magic_and_fantasy",
    "learning_and_educational",
    "bedtime_and_calming",
]

# ─────────────────────────────────────────────
#  VIDEO SETTINGS
# ─────────────────────────────────────────────
VIDEO_WIDTH        = 1080
VIDEO_HEIGHT       = 1920
VIDEO_FPS          = 30
VIDEO_ASPECT_RATIO = "9:16"

# ─────────────────────────────────────────────
#  OUTPUT PATHS
# ─────────────────────────────────────────────
OUTPUT_DIR    = "output"
RAW_DIR       = f"{OUTPUT_DIR}/raw"
AUDIO_DIR     = f"{OUTPUT_DIR}/audio"
MUSIC_DIR     = f"{OUTPUT_DIR}/music"
SUBTITLES_DIR = f"{OUTPUT_DIR}/subtitles"
FINAL_DIR     = f"{OUTPUT_DIR}/final"
STORIES_DIR   = f"{OUTPUT_DIR}/stories"
THUMBS_DIR    = f"{OUTPUT_DIR}/thumbnails"

# ─────────────────────────────────────────────
#  RETRY SETTINGS
# ─────────────────────────────────────────────
MAX_RETRIES        = 3
RETRY_WAIT_MIN_SEC = 2
RETRY_WAIT_MAX_SEC = 10

# ─────────────────────────────────────────────
#  ELEVENLABS VOICE SETTINGS
# ─────────────────────────────────────────────

# Free premade voices (work on free ElevenLabs plan)
# Run discover_voices.py to see all voices available on your account
VOICE_WARM_NARRATOR = "XrExE9yKIg1WjnnlVkGX"   # Matilda — warm, professional
VOICE_ENERGETIC     = "cgSgspJ2msm6clMCkdW9"   # Jessica — playful, bright
VOICE_CHARACTER     = "2OEeJcYw2f3bWMzzjVMU"   # Clara   — Children's Storyteller
VOICE_DEFAULT       = VOICE_WARM_NARRATOR

# To use your chosen library voices (requires Starter plan $5/mo):
# VOICE_WARM_NARRATOR = "lXiPxoDwq0d2OK7NdaXw"
# VOICE_ENERGETIC     = "Iz2kaKkJmFf0yaZAMDTV"
# VOICE_CHARACTER     = "qXpMhyvQqiRxWQs4qSSB"

# Emotion → voice assignment
VOICE_EMOTION_MAP = {
    "happy":     VOICE_ENERGETIC,
    "excited":   VOICE_ENERGETIC,
    "funny":     VOICE_ENERGETIC,
    "surprised": VOICE_ENERGETIC,
    "proud":     VOICE_ENERGETIC,
    "sad":       VOICE_WARM_NARRATOR,
    "scared":    VOICE_WARM_NARRATOR,
    "calm":      VOICE_WARM_NARRATOR,
    "magical":   VOICE_WARM_NARRATOR,
    "curious":   VOICE_WARM_NARRATOR,
}

ELEVENLABS_MODEL      = "eleven_multilingual_v2"   # Best quality
ELEVENLABS_MODEL_FAST = "eleven_flash_v2_5"        # Faster/cheaper for testing
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"

VOICE_SETTINGS = {
    "stability":         0.35,
    "similarity_boost":  0.80,
    "style":             0.40,
    "use_speaker_boost": True,
}

# ─────────────────────────────────────────────
#  IMAGE GENERATION (Fal.ai Flux)
# ─────────────────────────────────────────────
FAL_IMAGE_MODEL   = "fal-ai/flux-pro/v1.1"
FAL_IMAGE_SIZE    = "portrait_16_9"      # 9:16 vertical for Shorts
FAL_IMAGE_FORMAT  = "png"
FAL_MAX_CONCURRENT = 4                   # parallel image generations

# ─────────────────────────────────────────────
#  MUSIC SETTINGS (Stage 5)
# ─────────────────────────────────────────────
MUSIC_VOLUME       = 0.20   # background music volume (0.0-1.0), under narration
MUSIC_FADE_IN_SEC  = 1.5   # fade in at the very start of the music track
MUSIC_FADE_OUT_SEC = 3.0   # fade out at the very end of the music track
MUSIC_INTRO_SEC    = 1.5   # seconds of music-only BEFORE narration starts
MUSIC_OUTRO_SEC    = 2.0   # seconds of music-only AFTER narration ends

# Pixabay free music search terms per mood
MUSIC_MOOD_KEYWORDS = {
    "playful":         "playful children cartoon",
    "adventurous":     "adventure kids upbeat",
    "magical":         "magical fantasy children",
    "calm_and_soothing": "calm gentle lullaby children",
    "dramatic":        "dramatic adventure kids",
    "funny":           "funny cartoon kids",
    "heartwarming":    "heartwarming gentle kids",
}

# ─────────────────────────────────────────────
#  THUMBNAIL SETTINGS (Stage 9)
# ─────────────────────────────────────────────
THUMB_WIDTH  = 1280
THUMB_HEIGHT = 720
THUMB_MODEL  = "fal-ai/flux-pro/v1.1"

# ─────────────────────────────────────────────
#  FFMPEG PATH (Windows fix)
# ─────────────────────────────────────────────
FFMPEG_BIN = (
    r"C:\Users\omidg\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin"
)