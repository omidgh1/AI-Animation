"""
prompts/loader.py — Prompt file loader
=======================================
All AI prompts live in this folder as .txt files.
Edit them freely without touching Python code.

SUBJECT SUPPORT:
    Set config.SUBJECT = "facts" (or any niche name) to use subject-specific
    prompts from prompts/<subject>/<name>.txt. If a subject-specific file does
    not exist, it falls back to prompts/<name>.txt (the default kids prompts).

    To add a new niche (e.g. "finance"):
        1. Create folder:  prompts/finance/
        2. Copy any .txt files you want to customise from prompts/ into it
        3. Edit them for your niche
        4. Set SUBJECT = "finance" in test.py — done.

Usage:
    from prompts.loader import load_prompt

    # Static prompt (no variables)
    system = load_prompt("refiner_system")

    # Dynamic prompt with substitutions ($variable syntax)
    user = load_prompt("story_user", topic="a tiny dragon", num_scenes=12)
"""

import sys
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent


def _get_subject() -> str:
    """Read the active subject/niche from config (defaults to 'kids')."""
    try:
        # Import lazily to avoid circular imports at module load time
        import config
        return getattr(config, "SUBJECT", "kids")
    except ImportError:
        return "kids"


def load_prompt(name: str, **kwargs) -> str:
    """
    Load a prompt file and substitute any $variables provided as kwargs.

    Resolution order:
        1. prompts/<SUBJECT>/<name>.txt  (niche-specific override)
        2. prompts/<name>.txt            (default / kids fallback)

    Uses Python's string.Template ($placeholder syntax) so JSON braces { }
    in prompt files are treated as plain text — no escaping needed.
    Unresolved placeholders are left as-is (safe_substitute).

    Args:
        name:     Filename without extension, e.g. "story_system"
        **kwargs: Variable substitutions, e.g. num_scenes=12, topic="..."

    Returns:
        The prompt string, stripped of leading/trailing whitespace.

    Raises:
        FileNotFoundError: If neither subject-specific nor default prompt exists.
    """
    subject = _get_subject()

    # Try subject subfolder first, then fall back to root prompts/
    subject_path  = PROMPTS_DIR / subject / f"{name}.txt"
    fallback_path = PROMPTS_DIR / f"{name}.txt"

    if subject_path.exists():
        path = subject_path
    elif fallback_path.exists():
        path = fallback_path
    else:
        available_root    = [p.stem for p in PROMPTS_DIR.glob("*.txt")]
        available_subject = (
            [p.stem for p in subject_path.parent.glob("*.txt")]
            if subject_path.parent.exists() else []
        )
        raise FileNotFoundError(
            f"Prompt '{name}' not found for subject '{subject}'.\n"
            f"  Looked for: {subject_path}\n"
            f"  Fallback  : {fallback_path}\n"
            f"  Available in prompts/         : {available_root}\n"
            f"  Available in prompts/{subject}/: {available_subject}\n"
            f"  To add: create prompts/{subject}/{name}.txt"
        )

    text = path.read_text(encoding="utf-8")
    if kwargs:
        text = Template(text).safe_substitute(kwargs)
    return text.strip()
