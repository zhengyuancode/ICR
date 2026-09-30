"""Write stable SHA-256 checksums for the public artifact."""
from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "external"}
SKIP_NAMES = {"MANIFEST.sha256", "reproduced_claims.json", "main.pdf"}


def main() -> None:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if (not path.is_file() or path.name in SKIP_NAMES
                or any(part in SKIP_PARTS or part.endswith(".egg-info") for part in path.parts)):
            continue
        data = path.read_bytes()
        # .gitattributes stores text with LF even when a Windows worktree has
        # CRLF, so hash the bytes readers obtain from a fresh Git checkout.
        if b"\0" not in data and path.suffix.lower() != ".pdf":
            data = data.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(data).hexdigest()
        rows.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    (ROOT / "MANIFEST.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} checksums.")


if __name__ == "__main__":
    main()
