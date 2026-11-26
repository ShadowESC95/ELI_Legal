"""Fetch the eli-sdk wheel from its private GitHub release, check it, and point pip at it.

eli-sdk is kept private, so its release files cannot be downloaded by address. A build (CI or a
release) runs this before installing: it asks the GitHub API for the release asset with a
read-only token (ELI_SDK_TOKEN, a fine-grained token with Contents: read on eli-sdk only), checks
the file against the SHA-256 pinned here, puts it in the folder given, and, under GitHub Actions,
sets PIP_FIND_LINKS for the rest of the job so every ``pip install`` finds it there.

A machine that already has eli-sdk installed (a developer's environment) needs none of this.

    python scripts/fetch_eli_sdk.py <folder>
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = "ShadowESC95/eli-sdk"
TAG = "v1.2.1"
WHEEL = "eli_sdk-1.2.1-py3-none-any.whl"
SHA256 = "3efe5cf3e2b7e8850a203899968e96760e129ea9fc2dc00c9945138d119180f3"
API = "https://api.github.com"


def _get(url: str, token: str, accept: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "eli-legal-build",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https host
        return bytes(response.read())


def fetch(folder: Path, token: str) -> Path:
    release = json.loads(_get(f"{API}/repos/{REPO}/releases/tags/{TAG}", token,
                              "application/vnd.github+json"))  # fmt: skip
    asset = next((a for a in release.get("assets", []) if a.get("name") == WHEEL), None)
    if asset is None:
        raise SystemExit(f"{WHEEL} is not among the files of {REPO} {TAG}")
    body = _get(f"{API}/repos/{REPO}/releases/assets/{asset['id']}", token,
                "application/octet-stream")  # fmt: skip
    digest = hashlib.sha256(body).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"{WHEEL} does not match its pinned SHA-256 (got {digest}); not used")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / WHEEL
    path.write_bytes(body)
    return path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    token = os.environ.get("ELI_SDK_TOKEN", "").strip()
    if not token:
        print(
            "ELI_SDK_TOKEN is not set: add a fine-grained token with Contents: read on "
            f"{REPO} as the secret ELI_SDK_TOKEN of this repository",
            file=sys.stderr,
        )
        return 1
    folder = Path(argv[1]).resolve()
    path = fetch(folder, token)
    print(f"{path.name}: SHA-256 checked, in {folder}")
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env:
            env.write(f"PIP_FIND_LINKS={folder}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
