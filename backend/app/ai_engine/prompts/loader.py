"""Load versioned prompt files from Markdown with in-process caching."""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the raw body of a prompt file (without frontmatter)."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    text = path.read_text(encoding="utf-8")
    return _strip_frontmatter(text)


@lru_cache(maxsize=None)
def load_metadata(name: str) -> dict[str, str]:
    """Return frontmatter key/value pairs as strings."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    text = path.read_text(encoding="utf-8")
    return _parse_frontmatter(text)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split '---\\nkey: value\\n---\\nbody' into (frontmatter, body)."""
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2].lstrip("\n")


def _strip_frontmatter(text: str) -> str:
    return _split_frontmatter(text)[1].rstrip() + "\n"


def _parse_frontmatter(text: str) -> dict[str, str]:
    raw, _ = _split_frontmatter(text)
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result
