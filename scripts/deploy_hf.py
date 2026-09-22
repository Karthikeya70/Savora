"""
Put the current version of Savora online on Hugging Face Spaces.

    python scripts/deploy_hf.py https://huggingface.co/spaces/YOUR_NAME/YOUR_SPACE

What it does:
  Hugging Face needs a short settings block at the very top of README.md
  (which kind of app it is, which port, a title). On GitHub that block would
  show up as an odd table above your README, so this script adds it only to
  the copy sent to Hugging Face. Your GitHub repo and your local files are
  never changed.

It uploads exactly what is in your last git commit, so commit first.
The first upload asks you to sign in: use your Hugging Face username, and an
access token (with "write" permission) as the password.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = """---
title: AI Menu Assistant
emoji: 🥗
colorFrom: pink
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Know what's in your food before you order it
---

"""


def git(*args, env=None, stdin=None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, env=env, input=stdin,
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def main():
    if len(sys.argv) != 2 or "huggingface.co/spaces/" not in sys.argv[1]:
        sys.exit(__doc__)
    space_url = sys.argv[1].rstrip("/")
    if not space_url.endswith(".git"):
        space_url += ".git"

    if git("status", "--porcelain", "--untracked-files=no"):
        print("Note: you have uncommitted changes. Only your last commit will be uploaded.\n")

    # Build a copy of the last commit's files with the header added to README.md,
    # using a throwaway index so nothing in your working folder changes.
    readme = subprocess.run(["git", "show", "HEAD:README.md"], cwd=ROOT,
                            capture_output=True, check=True).stdout
    # Bytes, not text: on Windows, text mode would silently change line endings.
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT,
                          input=HEADER.encode("utf-8") + readme,
                          capture_output=True, check=True).stdout.decode().strip()

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", "HEAD", env=env)
        git("update-index", "--cacheinfo", f"100644,{blob},README.md", env=env)
        tree = git("write-tree", env=env)

    short = git("rev-parse", "--short", "HEAD")
    commit = git("commit-tree", tree, "-m", f"Deploy {short}")

    print(f"Uploading version {short} to {space_url} ...")
    push = subprocess.run(["git", "push", "--force", space_url, f"{commit}:refs/heads/main"], cwd=ROOT)
    if push.returncode != 0:
        sys.exit("\nUpload failed. If it asked for a password, use a Hugging Face "
                 "access token with write permission, not your account password.")

    page = space_url[:-4]
    print(f"\nUploaded. Hugging Face is now building it (about 5-10 minutes the first time).")
    print(f"Watch progress: {page}")


if __name__ == "__main__":
    main()
