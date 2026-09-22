"""
Put the current version of Savora online on Hugging Face Spaces (free plan).

    python scripts/deploy_hf.py https://huggingface.co/spaces/YOUR_NAME/YOUR_SPACE

The Space must be created with the Gradio SDK (Docker is a paid option).
Savora doesn't use Gradio: the free plan just runs space_app.py, which starts
Savora's own web server on the port Hugging Face expects.

What this script changes, in the copy sent to Hugging Face only:
  README.md         adds the short settings block Hugging Face needs at the top
                    (on GitHub that block would show as an odd table)
  requirements.txt  asks for the CPU-only version of torch, which is much
                    smaller; the free server has no graphics card anyway

Your GitHub repo and your local files are never changed. It uploads exactly
what is in your last git commit, so commit first.

The first upload asks you to sign in: your Hugging Face username, and an
access token with "write" permission as the password.
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
sdk: gradio
sdk_version: 5.9.1
python_version: "3.11"
app_file: space_app.py
pinned: false
short_description: Know what's in your food before you order it
---

"""

CPU_TORCH = "--extra-index-url https://download.pytorch.org/whl/cpu\ntorch\n"


def git(*args, env=None) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def committed(path: str) -> bytes:
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT,
                          capture_output=True, check=True).stdout


def store(content: bytes) -> str:
    """Save bytes into git and return their id. Bytes, not text: on Windows,
    text mode would silently change the line endings."""
    return subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input=content,
                          capture_output=True, check=True).stdout.decode().strip()


def build_commit() -> str:
    """The last commit's files, with the Hugging Face-only changes applied."""
    overrides = {
        "README.md":        HEADER.encode("utf-8") + committed("README.md"),
        "requirements.txt": CPU_TORCH.encode("utf-8") + committed("requirements.txt"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", "HEAD", env=env)
        for path, content in overrides.items():
            git("update-index", "--cacheinfo", f"100644,{store(content)},{path}", env=env)
        tree = git("write-tree", env=env)
    return git("commit-tree", tree, "-m", f"Deploy {git('rev-parse', '--short', 'HEAD')}")


def main():
    if len(sys.argv) != 2 or "huggingface.co/spaces/" not in sys.argv[1]:
        sys.exit(__doc__)
    space_url = sys.argv[1].rstrip("/")
    if not space_url.endswith(".git"):
        space_url += ".git"

    if git("status", "--porcelain", "--untracked-files=no"):
        print("Note: you have uncommitted changes. Only your last commit will be uploaded.\n")

    commit = build_commit()
    print(f"Uploading to {space_url} ...")
    push = subprocess.run(["git", "push", "--force", space_url, f"{commit}:refs/heads/main"], cwd=ROOT)
    if push.returncode != 0:
        sys.exit("\nUpload failed. If it asked for a password, use a Hugging Face "
                 "access token with write permission, not your account password.")

    print("\nUploaded. Hugging Face is now building it (about 5-10 minutes the first time).")
    print(f"Watch progress: {space_url[:-4]}")


if __name__ == "__main__":
    main()
