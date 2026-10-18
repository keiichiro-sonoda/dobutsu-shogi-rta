#!/usr/bin/env python3
"""コミットのときに回すテストを、変わったファイルから選ぶ (pre-commit のフックが使う)。

`make check` と CI は今までどおり全部を回す。ここで選ぶのはコミットのときだけ。

重いテスト (実装をビルドして走らせ、版どうしを比べるもの。SELECTIVE) は、
凍結した実装どうしを比べていて、実装もテストも変わっていなければ何度回しても同じ結果になる。そこで、変わったファイルがそのテストの
入力に当たるときだけ回す。重くないテストは毎回回す (合わせて約 10 秒)。

重いテスト T を回すのは、変わったファイル P が次のどれかに当たるとき:
  - T 自身、または T が (たどって) import している tests/ のモジュール
  - `impl/<名前>/…`・`experiments/<名前>/…`・`results/<名前>/…` で、<名前> が T の本文に出てくる
  - `tools/<名前>.py` で、<名前> が T の本文に出てくる
  - SCANS[T] の前置きで始まる (ディレクトリを丸ごと走査するテスト)
本文に名前が出てくるかは部分文字列で見る (多めに当たる側に倒す)。

全部を回す (安全側に倒す): 変わったファイルに FULL_TRIGGERS があるとき、`baseline/`・`oracle/`
(答えを固定しているもの. どの重いテストが間接に使うかを追いきれない) が変わったとき、または KNOWN の
どれにも当たらない場所が変わったとき (分類できないものは、何に効くか分からないので)。

使い方:
    python3 tools/select_tests.py --staged             # git に足したもの (pre-commit から)
    python3 tools/select_tests.py --staged --run [-- pytest の引数…]
    python3 tools/select_tests.py <変わったファイル>…   # 確かめる用
出力は回すテストファイルを1行に1つ (全部なら `tests` の1行)。--run なら pytest をそれで起動する。
"""

from __future__ import annotations

import argparse
import functools
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

# 重いテスト (変わったときだけ回す) の名前の形
SELECTIVE = re.compile(r"^test_(impl_\w+|\w+_equivalence|hot_layout_padding)\.py$")
# ディレクトリを丸ごと走査するので、名前の当て方では足りないテスト
SCANS = {"test_hot_layout_padding.py": ("impl/",)}
# どれかが変わったら全部回す (テストの土台・依存・選び方そのもの)
FULL_TRIGGERS = (
    "tests/conftest.py",
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".pre-commit-config.yaml",
    "tools/select_tests.py",
)
FULL_PREFIXES = ("baseline/", "oracle/")
# 分類できる場所。ここに当たらないものが変わったら全部回す
KNOWN = (
    "tests/",
    "tools/",
    "impl/",
    "experiments/",
    "results/",
    "docs/",
    ".claude/",
    ".github/",
)
KNOWN_ROOT_SUFFIXES = (".md",)
IMPORT = re.compile(r"^(?:from|import)\s+(test_\w+)\b", re.M)


def is_known(path: str) -> bool:
    if path.startswith(KNOWN):
        return True
    return "/" not in path and path.endswith(KNOWN_ROOT_SUFFIXES)


@functools.cache
def text(name: str) -> str:
    return (TESTS / name).read_text(encoding="utf-8")


@functools.cache
def imported(name: str) -> frozenset[str]:
    """テストファイル name が (たどって) import している tests/ のモジュールのファイル名。"""
    seen: set[str] = set()
    stack = [name]
    while stack:
        for mod in IMPORT.findall(text(stack.pop())):
            f = f"{mod}.py"
            if f not in seen and (TESTS / f).is_file():
                seen.add(f)
                stack.append(f)
    return frozenset(seen)


def depends(test: str, path: str) -> bool:
    """重いテスト test (tests/ の中のファイル名) が、変わったファイル path に当たるか。"""
    if path == f"tests/{test}" or any(path == f"tests/{m}" for m in imported(test)):
        return True
    if path.startswith(SCANS.get(test, ())):
        return True
    parts = path.split("/")
    body = text(test)
    if parts[0] in ("impl", "experiments", "results") and len(parts) > 1:
        return parts[1] in body
    if parts[0] == "tools" and len(parts) == 2 and parts[1].endswith(".py"):
        return parts[1].removesuffix(".py") in body
    return False


def select(changed: list[str]) -> list[str]:
    """回すテスト (リポジトリからの相対パス)。全部なら ["tests"]。"""
    if any(p in FULL_TRIGGERS or p.startswith(FULL_PREFIXES) or not is_known(p) for p in changed):
        return ["tests"]
    out = []
    for f in sorted(p.name for p in TESTS.glob("test_*.py")):
        if not SELECTIVE.match(f) or any(depends(f, p) for p in changed):
            out.append(f"tests/{f}")
    return out


def staged() -> list[str]:
    """git に足した変更のパス (消したもの・名前を変えたものの元の名前も含む)。"""
    done = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in done.stdout.splitlines() if ln]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--staged", action="store_true", help="git に足した変更から選ぶ")
    ap.add_argument("--run", action="store_true", help="選んだテストで pytest を起動する")
    ap.add_argument("files", nargs="*", help="変わったファイル (--staged のときは pytest の引数)")
    args = ap.parse_args(argv)
    if args.staged:
        changed, extra = staged(), args.files
    else:
        changed, extra = args.files, []
    chosen = select(changed)
    if not args.run:
        print("\n".join(chosen))
        return 0
    n_heavy = sum(1 for c in chosen if SELECTIVE.match(pathlib.Path(c).name))
    label = "全部" if chosen == ["tests"] else f"{len(chosen)} ファイル (うち重いテスト {n_heavy})"
    print(f"select_tests: 変わったファイル {len(changed)} 個から {label} を回す", file=sys.stderr)
    return subprocess.run([sys.executable, "-m", "pytest", *extra, *chosen], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
