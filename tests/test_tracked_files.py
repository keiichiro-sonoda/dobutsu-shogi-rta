"""追跡してよいドットファイルを名指しで固定する。

作業ディレクトリには、サンドボックスが読み取りを塞ぐために置いた **0 バイトの
読み取り専用ファイル**が並んでいる（`.gitconfig` / `.zshrc` / `.claude/agents` など）。
`git add -A` を打つとこれを巻き込む。実際に記録 #15 の後片付けで巻き込みかけ、
pre-commit の `end-of-file-fixer` が `PermissionError` で落ちて気づいた。

一括追加をやめるのが本筋（CLAUDE.md の「コミット」）だが、それだけだと1回の
打ち間違いで通ってしまうので、**追跡してよい名前をここに列挙して機械に見張らせる**。

網は2枚で、役目が違う。**追跡されているもの**を見る側（`ALLOWED`）と、
**`.gitignore` の方針**を見る側（無視してよい名前／無視してはいけない名前／
深さによらず無視すべき名前）。前者だけだと、共有すべき名前をうっかり
`.gitignore` に入れても気づけない。

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
    # ⚠️ 先頭だけでなく、どの成分が `.` で始まっても拾う。
    #    impl/<番号>_<名前>/.claude/.cc-writes/ がまさにその形で、そこは
    #    tools/run.sh の impl_sha256 が find . -type f で見ている場所。
    #    いま追跡中のファイルに入れ子のドット成分は1つも無いので、広げても誤検知は増えない
    return sorted(
        p
        for p in out.stdout.split("\0")
        if p and any(part.startswith(".") for part in p.split("/"))
    )


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


def ignored_by_repo(path: str) -> bool:
    """このリポジトリの .gitignore だけで無視されるか。

    ⚠️ `core.excludesFile=/dev/null` でグローバル ignore を外す。外さないと
    「手元では無視されるが clone では無視されない」を見逃す。実際 `.cc-writes` は
    リポジトリ側がルート固定で、入れ子は作者のグローバル設定が肩代わりしていた。
    """
    return (
        subprocess.run(
            ["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "-q", "--no-index", path],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


# プロジェクトのファイルには絶対ならない名前。無視してよい
SAFE_TO_IGNORE = (
    ".bashrc",
    ".bash_profile",
    ".zshrc",
    ".zprofile",
    ".profile",
    ".gitconfig",
    ".ripgreprc",
    ".idea",
    ".vscode",
)

# 同じ 0 バイトの覆いが置かれるが、共有すべき本物が同名で来る名前。無視してはいけない
MUST_STAY_VISIBLE = (
    ".gitmodules",
    ".mcp.json",
    ".claude/settings.json",
    ".claude/agents",
    ".claude/commands",
    ".claude/hooks",
    ".claude/workflows",
)

# Claude Code がどの階層にも作るもの。深さによらず無視されていなければならない
LOCAL_ANYWHERE = (
    ".claude/.cc-writes/x",
    "impl/16_example/.claude/.cc-writes/x",
    "experiments/gate_16_example/.claude/.cc-writes/x",
    ".claude/settings.local.json",
    "impl/16_example/.claude/settings.local.json",
)


def test_the_safe_shadows_are_ignored() -> None:
    """★覆いのうち、無視してよいものが実際に無視されていること。"""
    visible = [n for n in SAFE_TO_IGNORE if not ignored_by_repo(n)]
    assert visible == [], f"無視されていない: {visible}"


def test_the_shareable_names_are_not_ignored() -> None:
    """★共有すべき本物が同名で来る名前を、無視してしまっていないこと。

    ⚠️ これを無視すると `git add` が `-f` を要求し、本物を入れるときに詰まる。
    `.claude/settings.local.json` だけを無視する上流の区別を壊さないための歯止め。
    """
    hidden = [n for n in MUST_STAY_VISIBLE if ignored_by_repo(n)]
    assert hidden == [], (
        f"無視されている: {hidden}。どれも共有すべき本物が同名で来る。.gitignore から外すこと"
    )


def test_the_local_generated_files_are_ignored_at_any_depth() -> None:
    """★Claude Code のローカル生成物が、深さによらず無視されること。

    中間にスラッシュのあるパターンはルートに固定されるので `**/` が要る。
    impl/<番号>_<名前>/ の下に置かれると `tools/run.sh` の `impl_sha256`
    （`find . -type f`）に入り、記録の証拠のハッシュが動く。
    """
    visible = [n for n in LOCAL_ANYWHERE if not ignored_by_repo(n)]
    assert visible == [], f"深いところで無視されていない: {visible}"
