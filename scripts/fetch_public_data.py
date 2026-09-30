"""Fetch and verify the public benchmark files used by the experiments."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANBENCH_URL = "https://github.com/JiayuJeff/PlanBench-XL.git"
PLANBENCH_COMMIT = "a24bfd5f1a6ad7ad3c5d5204525272c6488225ac"

TASKBENCH = {
    "multimedia": {
        "data.json": "a809825f62da8addc5c05b94108a06b1041b9f46d9a1fa3a67ebfd199538b2e5",
        "graph_desc.json": "1065e6041fecbf55c18891fcfb5a4e24ea941dcac3dab670423148902fe6dc55",
        "tool_desc.json": "6300f287ebf7dd04f7e8f4d76462b2fe83b823f1cccf432608818f3df67ed0d7",
    },
    "huggingface": {
        "data.json": "10f6fbfed1ec88a479de1114be6f94c4e1cfcb719cdecc1af09c82b3aab4a301",
        "graph_desc.json": "48f774a01d1452ddf918ced6f04218fe311863725a0d6624d6e191e7ea6c4694",
        "tool_desc.json": "0eb0654faea9a5f07c0102ca57bfc6de3f9e03d8a00c2776b82e22b1b7c31fbd",
    },
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and digest(target) == expected:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "ICR"})
    temporary = target.with_suffix(target.suffix + ".download")
    with urllib.request.urlopen(request) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    actual = digest(temporary)
    if actual != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Hash mismatch for {url}: {actual}")
    temporary.replace(target)


def fetch_taskbench() -> None:
    for domain, files in TASKBENCH.items():
        destination = ROOT / "research" / "external" / f"taskbench_{domain}"
        for name, expected in files.items():
            url = (
                "https://raw.githubusercontent.com/microsoft/JARVIS/main/"
                f"taskbench/data_{domain}/{name}"
            )
            download(url, destination / name, expected)


def fetch_planbench() -> None:
    destination = ROOT / "external" / "PlanBench-XL-main"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", PLANBENCH_URL, str(destination)], check=True)
    if not (destination / ".git").exists():
        raise RuntimeError(f"Expected a Git checkout at {destination}")
    subprocess.run(["git", "checkout", "--detach", PLANBENCH_COMMIT], cwd=destination, check=True)
    manifest = json.loads((ROOT / "research" / "continuation_repair" /
                           "planbench_source_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        path = destination / relative
        actual = digest(path)
        if actual != expected:
            raise RuntimeError(f"Hash mismatch for {relative}: {actual}")


if __name__ == "__main__":
    fetch_taskbench()
    fetch_planbench()
    print("Public benchmark files downloaded and verified.")
