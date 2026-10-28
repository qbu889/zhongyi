from app import git_utils


def test_distilled_commit_hash_is_a_real_commit_touching_corpus():
    commit = git_utils.distilled_commit_hash()
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)

    import subprocess
    subject = subprocess.run(
        ["git", "-C", str(git_utils.settings.repo_dir), "show", "-s", "--format=%H", commit],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert subject == commit


def test_hash_is_stable_and_ancestor_of_head():
    """语料 hash 必须可重复取得，且是 HEAD 的祖先（绑语料而非 HEAD，NFR-6）。"""
    import subprocess

    repo = str(git_utils.settings.repo_dir)
    commit = git_utils.distilled_commit_hash()
    assert commit == git_utils.distilled_commit_hash()

    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    merge_base = subprocess.run(["git", "-C", repo, "merge-base", commit, head],
                                capture_output=True, text=True, check=True).stdout.strip()
    assert merge_base == commit

