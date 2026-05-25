"""
prompts/loader.py — Prompt file loader
=======================================
All AI prompts live in this folder as .txt files.
Edit them freely without touching Python code.

Usage:
    from prompts.loader import load_prompt

    # Static prompt (no variables)
    system = load_prompt("refiner_system")

    # Dynamic prompt with substitutions ($variable syntax)
    user = load_prompt("story_user", topic="a tiny dragon", num_scenes=12)
"""

from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, **kwargs) -> str:
    """
    Load prompts/<name>.txt and substitute any $variables provided as kwargs.

    Uses Python's string.Template ($placeholder syntax) so JSON braces { }
    in prompt files are treated as plain text — no escaping needed.

    Unresolved placeholders are left as-is (safe_substitute).

    Args:
        name:    Filename without extension, e.g. "story_system"
        **kwargs: Variable substitutions, e.g. num_scenes=12, topic="..."

    Returns:
        The prompt string, stripped of leading/trailing whitespace.

    Raises:
        FileNotFoundError: If prompts/<name>.txt does not exist.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path}\n"
            f"Available prompts: {[p.stem for p in PROMPTS_DIR.glob('*.txt')]}"
        )
    text = path.read_text(encoding="utf-8")
    if kwargs:
        text = Template(text).safe_substitute(kwargs)
    return text.strip()
