#!/usr/bin/env python3
"""文書の分量を機械に見張らせる。

`README.md` は 1479行まで伸びて、`⚠️` が 139個 (10.6行に1個) になった。
`CLAUDE.md` には規約が書いてあったのに止まらなかった。個別に見れば `⚠️` は
どれも本物の罠を指していて、1個ずつ判断するかぎり毎回「これは必要」という
結論が出る。総量を見ている人がいないのが原因なので、上限は機械に持たせる。

| ID | 内容 | 既定値 |
|----|------|--------|
| D1 | ファイルの行数上限 | `README.md` 400 / その他 300 |
| D2 | `⚠️` は1見出し節につき1個まで | 1 |
| D3 | `🔑` は使わない | 0 |

D2 を総数ではなく節ごとにするのは、総数だと長いファイルほど薄まって
通ってしまうため。節ごとなら「この節で一番効く警告はどれか」を毎回1つ選ぶ。

既存の債務は `tools/doc_lint_baseline.txt` に固定してあり、**新しく増えた
ぶんだけ**が FAIL になる。一括修正は強制しない。既定値そのものは当て推量なので、
baseline がある状態で後から締められる。

記号の「使用」と「言及」は区別する。**インラインコードとフェンスの中に出てきた
記号は数えない**ので、記号そのものの話をするときはバッククォートで囲む
(このファイルの上の表がまさにそう書いてある)。

使い方:

    python3 tools/doc_lint.py                     # 検査 (新規違反があれば終了コード 1)
    python3 tools/doc_lint.py --update-baseline   # いまの違反を baseline に固定する
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from collections.abc import Iterable, Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tools" / "doc_lint_baseline.txt"

# 検査する文書。results/ baseline/ impl/ は凍結された証拠なので入れない
ALWAYS = ("README.md", "CLAUDE.md")
GLOBS = ("docs/**/*.md", "experiments/**/*.md")

LINE_LIMITS = {"README.md": 400}
DEFAULT_LINE_LIMIT = 300
WARN_PER_SECTION = 1

# ⚠️ は U+26A0 (+ 異体字セレクタ)、🔑 は U+1F511
WARN = re.compile("⚠️?")
KEY = re.compile("\U0001f511")

FENCE = re.compile(r"^\s*(?:```|~~~)")
HEADING = re.compile(r"^#{1,6} (.+)$")
INLINE_CODE = re.compile(r"`[^`]*`")

PREAMBLE = "(前文)"

# (ルール, パス, 節, 個数)
Violation = tuple[str, str, str, int]


def documents(root: pathlib.Path) -> list[pathlib.Path]:
    """検査対象の文書を集める。"""
    found = [root / name for name in ALWAYS]
    for pattern in GLOBS:
        found += sorted(root.glob(pattern))
    return [p for p in found if p.is_file()]


def sections(text: str) -> list[tuple[str, str]]:
    """見出しから次の見出しまでを1節として切り出す。

    フェンスとインラインコードの中身は落とす (記号の「言及」を数えないため)。
    見出し行そのものはその節の一部として数える。同じ見出しが2度出てきたら
    ` [2]` を付けて区別する (baseline の行を一意にするため)。
    """
    out: list[tuple[str, str]] = []
    locator = PREAMBLE
    buf: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            out.append((locator, "\n".join(buf)))
            locator = m.group(1).strip().replace("\t", " ")
            buf = [INLINE_CODE.sub("", m.group(1))]
        else:
            buf.append(INLINE_CODE.sub("", line))
    out.append((locator, "\n".join(buf)))

    seen: dict[str, int] = {}
    unique: list[tuple[str, str]] = []
    for loc, body in out:
        seen[loc] = seen.get(loc, 0) + 1
        unique.append((loc if seen[loc] == 1 else f"{loc} [{seen[loc]}]", body))
    return unique


def inspect(path: pathlib.Path, root: pathlib.Path) -> Iterator[Violation]:
    """1つの文書を検査する。"""
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")

    limit = LINE_LIMITS.get(rel, DEFAULT_LINE_LIMIT)
    n_lines = len(text.splitlines())
    if n_lines > limit:
        yield ("D1", rel, f"上限 {limit} 行", n_lines)

    for locator, body in sections(text):
        n_warn = len(WARN.findall(body))
        if n_warn > WARN_PER_SECTION:
            yield ("D2", rel, locator, n_warn)
        n_key = len(KEY.findall(body))
        if n_key:
            yield ("D3", rel, locator, n_key)


def collect(root: pathlib.Path) -> list[Violation]:
    found: list[Violation] = []
    for path in documents(root):
        found += inspect(path, root)
    return sorted(found)


def dump(found: Iterable[Violation]) -> str:
    head = (
        "# doc_lint の既知の違反。新しく増えたぶんだけを FAIL させるための固定点。\n"
        "# 減らすのは歓迎 (--update-baseline で締め直す)。\n"
        "# ルール\tファイル\t節\t個数\n"
    )
    return head + "".join(f"{r}\t{p}\t{loc}\t{n}\n" for r, p, loc, n in found)


def load(path: pathlib.Path) -> dict[tuple[str, str, str], int]:
    known: dict[tuple[str, str, str], int] = {}
    if not path.is_file():
        return known
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rule, rel, locator, count = line.split("\t")
        known[(rule, rel, locator)] = int(count)
    return known


def compare(
    found: Iterable[Violation], known: dict[tuple[str, str, str], int]
) -> tuple[list[str], list[str]]:
    """baseline と突き合わせて (FAIL する行, 参考情報の行) を返す。"""
    bad: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for rule, rel, locator, count in found:
        key = (rule, rel, locator)
        seen.add(key)
        before = known.get(key)
        if before is None:
            bad.append(f"{rule} 新規  {rel}: {locator} ({count})")
        elif count > before:
            bad.append(f"{rule} 増えた {rel}: {locator} ({before} → {count})")
    info = [
        f"{rule} 解消  {rel}: {locator}"
        for (rule, rel, locator) in sorted(known)
        if (rule, rel, locator) not in seen
    ]
    return bad, info


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="文書の分量を検査する")
    parser.add_argument(
        "--update-baseline", action="store_true", help="いまの違反を baseline に固定する"
    )
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="検査するリポジトリ")
    parser.add_argument("--baseline", type=pathlib.Path, default=BASELINE)
    args = parser.parse_args(argv)

    found = collect(args.root)
    if args.update_baseline:
        args.baseline.write_text(dump(found), encoding="utf-8")
        print(f"{args.baseline} に {len(found)} 件を固定した")
        return 0

    bad, info = compare(found, load(args.baseline))
    for line in info:
        print(line)
    if info:
        print(f"（{len(info)} 件が baseline から消えた。--update-baseline で締め直せる）")
    if bad:
        print("\n新しい違反:")
        for line in bad:
            print(f"  {line}")
        print(
            f"\ndoc_lint: 新規違反 {len(bad)} 件。"
            "⚠️ は1節1個まで、🔑 は使わない、README は 400行まで。"
        )
        return 1
    print(f"doc_lint: 新規違反ゼロ（既知 {len(found)} 件は baseline に固定済み）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
