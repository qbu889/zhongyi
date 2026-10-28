"""语料版本：索引绑定 `distilled/` 的 git commit hash（PRD NFR-6）。

用 `git log -- distilled` 而不是 HEAD，因为 HEAD 前移但语料未变时会产出无意义的新版本。
"""

import subprocess

from app.config import settings


def distilled_commit_hash(repo_dir=None) -> str:
    repo = str(repo_dir or settings.repo_dir)
    out = subprocess.run(
        ["git", "-C", repo, "log", "-1", "--format=%H", "--", "distilled"],
        capture_output=True, text=True, check=True,
    )
    commit = out.stdout.strip()
    if not commit:
        raise ValueError(f"{repo} 中 distilled/ 无提交历史")
    return commit
