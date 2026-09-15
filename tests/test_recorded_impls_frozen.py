"""記録を取った実装は、そのあと書き換えない。

`results/<番号>_<ラベル>/env.txt` は `impl_sha256` と `git_commit` で
「何を走らせたのか」を指している。あとから実装を1文字でも直すと、この指し先が嘘になる。
タイプミスやコメントの訂正であっても、記録済みの実装は触らず、次の試行を新しい
ディレクトリに作る (`baseline/` と同じ扱い)。

ハッシュそのものではなく git の内容比較で見る。ハッシュの計算式は e186af8 で
`LC_ALL=C` を足したときに一度変わっていて、記録 #1 の `impl_sha256` は
その前の値になっているため (実装の中身は動いていない)。
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
from conftest import RESULTS_DIR, ROOT


def env_field(text: str, name: str) -> str | None:
    m = re.search(rf"^{name}:\s*(\S+)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


def recorded_runs() -> list[tuple[pathlib.Path, str, pathlib.Path]]:
    """(env.txt, 記録時のコミット, 実装ディレクトリ) を記録ごとに返す。"""
    out = []
    for env_path in sorted(RESULTS_DIR.glob("*/env.txt")):
        text = env_path.read_text(encoding="utf-8")
        commit = env_field(text, "git_commit")
        name = env_field(text, "impl") or env_field(text, "label")
        assert commit, f"{env_path} に git_commit が無い"
        assert name, f"{env_path} に impl も label も無い"
        impl_dir = ROOT / "baseline" if name == "baseline" else ROOT / "impl" / name
        out.append((env_path, commit, impl_dir))
    return out


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def test_every_record_points_at_an_implementation_that_still_exists() -> None:
    for env_path, _, impl_dir in recorded_runs():
        assert impl_dir.is_dir(), (
            f"{env_path.relative_to(ROOT)} が指す {impl_dir.relative_to(ROOT)} が無い"
        )


def test_recorded_implementations_have_not_changed_since_they_were_measured() -> None:
    """記録時のコミットと作業ツリーで、実装ディレクトリの中身が同じであること。"""
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("git リポジトリではない")

    for env_path, commit, impl_dir in recorded_runs():
        if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            pytest.skip(f"{commit} が見えない (浅いクローン)。CI は fetch-depth: 0 で取る")
        rel = impl_dir.relative_to(ROOT).as_posix()
        diff = git("diff", "--name-only", commit, "--", rel)
        assert diff.returncode == 0, diff.stderr
        assert not diff.stdout.strip(), (
            f"{rel} が記録後に変わっている\n"
            f"  {env_path.relative_to(ROOT)} は {commit} を指している\n"
            f"{diff.stdout}"
            f"記録済みの実装は凍結する。直したいことがあれば次の試行を新しいディレクトリに作る"
        )
