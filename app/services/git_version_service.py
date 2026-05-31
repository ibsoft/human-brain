import os
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

    branch = (
        os.getenv("HUMAN_BRAIN_GIT_BRANCH")
        or os.getenv("GIT_BRANCH")
        or run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        or _branch_from_git_files(root)
        or "unknown"
    )
    commit = (
        os.getenv("HUMAN_BRAIN_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or run(["git", "rev-parse", "--short", "HEAD"])
        or _commit_from_git_files(root)
        or os.getenv("HUMAN_BRAIN_VERSION")
        or "unknown"
    )
    dirty = bool(run(["git", "status", "--porcelain"]))
    return {"branch": branch, "commit": commit, "dirty": dirty}


def _git_dir(root):
    git_path = root / ".git"
    if git_path.is_dir():
        return git_path
    if git_path.is_file():
        content = git_path.read_text(encoding="utf-8", errors="replace").strip()
        if content.startswith("gitdir:"):
            path = content.removeprefix("gitdir:").strip()
            candidate = Path(path)
            return candidate if candidate.is_absolute() else root / candidate
    return None


def _head_ref(root):
    git_dir = _git_dir(root)
    if not git_dir:
        return None, None
    head = git_dir / "HEAD"
    if not head.exists():
        return git_dir, None
    value = head.read_text(encoding="utf-8", errors="replace").strip()
    if value.startswith("ref:"):
        return git_dir, value.removeprefix("ref:").strip()
    return git_dir, value


def _branch_from_git_files(root):
    _, ref = _head_ref(root)
    if not ref or not ref.startswith("refs/heads/"):
        return None
    return ref.removeprefix("refs/heads/")


def _commit_from_git_files(root):
    git_dir, ref = _head_ref(root)
    if not git_dir or not ref:
        return None
    if not ref.startswith("refs/"):
        return ref[:7]
    ref_path = git_dir / ref
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8", errors="replace").strip()[:7]
    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists():
        for line in packed_refs.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0][:7]
    return None
