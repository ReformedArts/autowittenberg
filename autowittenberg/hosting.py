"""Temporary public hosting for the images Instagram downloads when we publish.

Instagram fetches each image from a public URL. We put the slides on a throwaway branch of this
repository (`ig-media`) that is force-replaced every time, so nothing accumulates, and read them
back through raw.githubusercontent.com.
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
BRANCH = "ig-media"


def _repo_slug():
    return os.environ.get("GITHUB_REPOSITORY") or "ReformedArts/autowittenberg"


def _git(*args, cwd):
    result = subprocess.run(["git", "-c", "user.name=AutoWittenberg bot",
                             "-c", "user.email=autowittenberg-bot@users.noreply.github.com", *args],
                            cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def publish_images(paths):
    """Uploads the files to the throwaway branch; returns their public URLs, in order."""
    work = Path(tempfile.mkdtemp(prefix="ig-media-"))
    tree = work / "tree"
    try:
        _git("worktree", "add", "--detach", str(tree), "HEAD", cwd=ROOT)
        _git("checkout", "--orphan", "ig-media-tmp", cwd=tree)
        _git("rm", "-rfq", ".", cwd=tree)
        stamp = str(int(time.time()))
        names = []
        for i, path in enumerate(paths):
            name = f"{stamp}_{i + 1}_{Path(path).name}"
            shutil.copy(path, tree / name)
            names.append(name)
        _git("add", "-A", cwd=tree)
        _git("commit", "-qm", "Temporary media for Instagram publishing", cwd=tree)
        _git("push", "--force", "origin", f"ig-media-tmp:{BRANCH}", cwd=tree)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)
        subprocess.run(["git", "branch", "-D", "ig-media-tmp"], cwd=ROOT, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    urls = [f"https://raw.githubusercontent.com/{_repo_slug()}/{BRANCH}/{n}" for n in names]
    for url in urls:  # wait until GitHub actually serves each image as a JPEG
        for _ in range(12):
            r = requests.head(url, timeout=20)
            if r.status_code == 200 and "image/jpeg" in r.headers.get("Content-Type", ""):
                break
            time.sleep(5)
        else:
            raise RuntimeError(f"Image not publicly reachable yet: {url}")
    return urls
