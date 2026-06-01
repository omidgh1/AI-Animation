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
#  SUBJECT / NICHE
#  Controls which prompts/ subfolder is used.
#  "kids"    → prompts/*.txt   (default kids video prompts)
#  "facts"   → prompts/facts/*.txt  (surprising facts for adults)
#  Add new niches by creating prompts/<subject>/ with custom .txt files.
# ─────────────────────────────────────────────
SUBJECT = "kids"   # overridden by test.py at runtime

# ─────────────────────────────────────────────
#  STORY SETTINGS
# ─────────────────────────────────────────────
NUM_SCENES         = 12        # 12 scenes × ~5s = ~60s video
SCENE_DURATION_SEC = 5
TARGET_VIDEO_SEC   = 60

_CATEGORIES_BY_SUBJECT = {
    "kids": [
        "animal_adventure", "friendship_and_emotions", "magic_and_fantasy",
        "learning_and_educational", "bedtime_and_calming",
    ],
    "facts": [
        "science", "history", "nature", "psychology",
        "technology", "space", "animals", "general",
    ],
}

_MUSIC_MOODS_BY_SUBJECT = {
    "kids": ["playful", "adventurous", "magical", "calm_and_soothing", "dramatic", "funny", "heartwarming"],
    "facts": ["upbeat", "tense", "mysterious", "inspiring", "energetic", "dramatic", "curious"],
}

# These are set dynamically at runtime based on SUBJECT (see below)
STORY_CATEGORIES: list[str] = _CATEGORIES_BY_SUBJECT["kids"]
MUSIC_MOODS: list[str]      = _MUSIC_MOODS_BY_SUBJECT["kids"]

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

# ── Kids voices (free premade, work on free ElevenLabs plan) ──
_VOICES_KIDS = {
    "warm_narrator": "XrExE9yKIg1WjnnlVkGX",   # Matilda — warm, professional
    "energetic":     "cgSgspJ2msm6clMCkdW9",   # Jessica — playful, bright
    "character":     "2OEeJcYw2f3bWMzzjVMU",   # Clara   — Children's Storyteller
}
_EMOTION_MAP_KIDS = {
    "happy":     _VOICES_KIDS["energetic"],
    "excited":   _VOICES_KIDS["energetic"],
    "funny":     _VOICES_KIDS["energetic"],
    "surprised": _VOICES_KIDS["energetic"],
    "proud":     _VOICES_KIDS["energetic"],
    "sad":       _VOICES_KIDS["warm_narrator"],
    "scared":    _VOICES_KIDS["warm_narrator"],
    "calm":      _VOICES_KIDS["warm_narrator"],
    "magical":   _VOICES_KIDS["warm_narrator"],
    "curious":   _VOICES_KIDS["warm_narrator"],
}

# ── Facts / adult voices (free premade) ──
# George: deep authoritative male  |  Charlie: conversational male
# Rachel: clear confident female   |  Liam: energetic male
_VOICES_FACTS = {
    "warm_narrator": "JBFqnCBsd6RMkjVDRZzb",   # George — deep, authoritative
    "energetic":     "IKne3meq5aSn9XLyUdCD",   # Charlie — conversational, engaging
    "character":     "JBFqnCBsd6RMkjVDRZzb",   # George — same for facts (no character)
}
_EMOTION_MAP_FACTS = {
    # Single narrator for all emotions — facts videos don't need voice switching
    "surprised":  _VOICES_FACTS["warm_narrator"],
    "excited":    _VOICES_FACTS["warm_narrator"],
    "funny":      _VOICES_FACTS["warm_narrator"],
    "curious":    _VOICES_FACTS["warm_narrator"],
    "calm":       _VOICES_FACTS["warm_narrator"],
    "tense":      _VOICES_FACTS["warm_narrator"],
    "mysterious": _VOICES_FACTS["warm_narrator"],
    "inspiring":  _VOICES_FACTS["warm_narrator"],
    "dramatic":   _VOICES_FACTS["warm_narrator"],
    "happy":      _VOICES_FACTS["warm_narrator"],
    "sad":        _VOICES_FACTS["warm_narrator"],
    "scared":     _VOICES_FACTS["warm_narrator"],
    "proud":      _VOICES_FACTS["warm_narrator"],
    "magical":    _VOICES_FACTS["warm_narrator"],
}

# Active voice settings — overridden by test.py based on SUBJECT
VOICE_WARM_NARRATOR = _VOICES_KIDS["warm_narrator"]
VOICE_ENERGETIC     = _VOICES_KIDS["energetic"]
VOICE_CHARACTER     = _VOICES_KIDS["character"]
VOICE_DEFAULT       = VOICE_WARM_NARRATOR
VOICE_EMOTION_MAP   = _EMOTION_MAP_KIDS

ELEVENLABS_MODEL      = "eleven_multilingual_v2"   # Best quality
ELEVENLABS_MODEL_FAST = "eleven_flash_v2_5"        # Faster/cheaper for testing
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"

# ── Kids voice style — expressive and warm ──
_VOICE_SETTINGS_KIDS = {
    "stability":         0.35,
    "similarity_boost":  0.80,
    "style":             0.40,
    "use_speaker_boost": True,
}

# ── Facts voice style — steady and clear, less theatrical ──
_VOICE_SETTINGS_FACTS = {
    "stability":         0.55,
    "similarity_boost":  0.75,
    "style":             0.25,
    "use_speaker_boost": True,
}

VOICE_SETTINGS = _VOICE_SETTINGS_KIDS   # overridden by test.py

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

# Pixabay free music search terms per mood — subject-aware
_MUSIC_KEYWORDS_KIDS = {
    "playful":           "playful children cartoon",
    "adventurous":       "adventure kids upbeat",
    "magical":           "magical fantasy children",
    "calm_and_soothing": "calm gentle lullaby children",
    "dramatic":          "dramatic adventure kids",
    "funny":             "funny cartoon kids",
    "heartwarming":      "heartwarming gentle kids",
}

_MUSIC_KEYWORDS_FACTS = {
    "upbeat":      "upbeat corporate background",
    "tense":       "tense suspense documentary",
    "mysterious":  "mysterious dark ambient",
    "inspiring":   "inspiring cinematic background",
    "energetic":   "energetic electronic upbeat",
    "dramatic":    "dramatic cinematic orchestral",
    "curious":     "curious documentary background",
}

MUSIC_MOOD_KEYWORDS = _MUSIC_KEYWORDS_KIDS   # overridden by test.py

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