"""Fail if the release tree contains credentials, machine paths, or work files."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "external"}
FORBIDDEN_NAMES = {
    "config.local.json", ".env", "memory.md", "agents.md",
}
TEXT_SUFFIXES = {
    ".py", ".md", ".tex", ".bib", ".json", ".cff", ".txt", ".yaml", ".yml",
}
PATTERNS = {
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\", re.I),
    "Unix home path": re.compile(r"/home/[^/\s]+/"),
    "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "AWS key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "long bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.I),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "Codex work trace": re.compile(r"\b(?:codex|chatgpt)\b", re.I),
}


def tracked_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts):
            continue
        yield path


def main() -> None:
    failures = []
    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if path.name.lower() in FORBIDDEN_NAMES:
            failures.append(f"forbidden file: {relative}")
        if path.suffix.lower() in {".pdf", ".tex", ".bib", ".png", ".svg", ".jpg", ".jpeg"}:
            failures.append(f"manuscript or image file: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{label}: {relative}")
    if failures:
        raise SystemExit("Release audit failed:\n" + "\n".join(sorted(set(failures))))
    print(f"Release audit passed for {sum(1 for _ in tracked_files())} files.")


if __name__ == "__main__":
    main()
