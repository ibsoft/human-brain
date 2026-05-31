import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def git_version():
    root = Path(__file__).resolve().parents[2]

    def run(args):
        try:
            return subprocess.check_output(args, cwd=root, stderr=subprocess.DEVNULL, text=True, timeout=1).strip()
        except Exception:
            return ""

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    commit = run(["git", "rev-parse", "--short", "HEAD"]) or "unknown"
    dirty = bool(run(["git", "status", "--porcelain"]))
    return {"branch": branch, "commit": commit, "dirty": dirty}
