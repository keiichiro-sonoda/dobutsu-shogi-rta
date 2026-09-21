"""追跡してよいドットファイルを名指しで固定する。

作業ディレクトリには、サンドボックスが読み取りを塞ぐために置いた **0 バイトの
読み取り専用ファイル**が並んでいる（`.gitconfig` / `.zshrc` / `.claude/agents` など）。
`git add -A` を打つとこれを巻き込む。実際に記録 #15 の後片付けで巻き込みかけ、
pre-commit の `end-of-file-fixer` が `PermissionError` で落ちて気づいた。

一括追加をやめるのが本筋（CLAUDE.md の「コミット」）だが、それだけだと1回の
打ち間違いで通ってしまうので、**追跡してよい名前をここに列挙して機械に見張らせる**。

⚠️ **新しく共有したいドットファイルが出たら、ここに足してから `git add` する。**
落ちるのは仕様。`.gitignore` に入れて黙らせるのは、その名前が
プロジェクトのファイルには絶対ならないと言い切れるときだけ。
"""

from __future__ import annotations

import subprocess

from conftest import ROOT

# 追跡してよい正確なパス
ALLOWED = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".pre-commit-config.yaml",
    }
)

# 追跡してよい接頭辞。⚠️ `.claude/` 全体ではなく `.claude/skills/` だけ。
# `.claude/settings.json` などは共有し得るが、入れるときは意識して足す
ALLOWED_PREFIXES = (".github/", ".claude/skills/")


def tracked_dotfiles() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(p for p in out.stdout.split("\0") if p.startswith("."))


def test_only_named_dotfiles_are_tracked() -> None:
    """★列挙していないドットファイルが追跡されていないこと。"""
    unexpected = [
        p for p in tracked_dotfiles() if p not in ALLOWED and not p.startswith(ALLOWED_PREFIXES)
    ]
    assert unexpected == [], (
        f"名指ししていないドットファイルが追跡されている: {unexpected}。"
        "サンドボックスの 0 バイトの覆いを git add -A で巻き込んでいないか確かめること。"
        "意図して共有するなら tests/test_tracked_files.py の ALLOWED に足す"
    )


def test_the_allowlist_is_not_stale() -> None:
    """★列挙したのに存在しない名前を残さない（許可が空振りしていないか）。

    ⚠️ 空振りした許可は「見張っているつもり」を作る。`.claude/skills/` を
    消したのに接頭辞が残っていたら、その接頭辞は何も守っていない。
    """
    tracked = tracked_dotfiles()
    for name in sorted(ALLOWED):
        assert name in tracked, f"{name} は追跡されていない。ALLOWED から外すこと"
    for prefix in ALLOWED_PREFIXES:
        assert any(p.startswith(prefix) for p in tracked), (
            f"{prefix} で始まる追跡ファイルが無い。ALLOWED_PREFIXES から外すこと"
        )


def test_the_shadows_are_ignored_or_visible() -> None:
    """★0 バイトの覆いが「追跡されている」状態になっていないこと。

    `.gitignore` に入れたもの（`.gitconfig` など）は `git status` から消え、
    入れていないもの（`.gitmodules` / `.mcp.json` / `.claude/*`）は未追跡として
    見え続ける。⚠️ **どちらでもよいが「追跡されている」だけは駄目。**
    """
    shadows = (
        ".bashrc",
        ".zshrc",
        ".gitconfig",
        ".ripgreprc",
        ".gitmodules",
        ".mcp.json",
        ".claude/settings.json",
        ".claude/agents",
    )
    tracked = set(tracked_dotfiles())
    for name in shadows:
        assert name not in tracked, f"{name} が追跡されている（覆いを巻き込んだ?）"
