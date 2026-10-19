#!/usr/bin/env python3
"""事前登録の節を、回したあとで読み直す (レビューの道具。push は止めない)。

門番と実験の README は、予測・止める条件・判定の量を「回す前に書いた」節に置き、
回す前にコミットする。履歴で確かめられることが、その節の値打ちのすべて。
ところが人の目は「コミットが計時より前か」までは見ても、**節の中身が回す前に
知り得たものだけでできているか**までは見落とす (実験 unmove_bench の見込みは、
一致の検査で見たあとの「候補が平均 9.8 個」を根拠に使っていて、本文の
「見込みには載せない」と食い違っていた。レビューは時刻の順だけを見て通した)。

| ID | 内容 |
|----|------|
| R1 | 登録した節の行が、登録のコミットのあとで書き換わった・消えた (`※` を足しただけの行は R0) |
| R2 | 登録の時点で、この実験の `logs/` にファイルが既にあった (見たあとの数を予測に使えた) |
| R3 | 回す前のはずの本が、登録より前に始まっている (`logs/console*.log` の「開始」) |
| R0 | 参考: `※` の注記を足しただけの行 (注記に「あとで足した」と書いてあるかを目で見る) |

「登録した節」は、見出しに「〜前に書いた」「〜前に決めた」「〜前に数えた」を含む `##` の節。
「登録のコミット」は、その見出しの行を初めて足したコミット。

R2 は、予測が見たあとの数を使ったかを**機械では決めない**。登録の時点で `logs/` が空なら、
見たあとの数は無いので鳴らない (ふつうの実験はこれ)。ファイルがあったときだけ、登録のコミットごとに
1件、そのファイルを並べて出す。見る人は、予測の節が何を根拠にしたか (回す前に数えたもの・
前の段の結果・前からリポジトリにあった数) が README に書いてあるかを確かめる。
以前は予測の数をログの数と丸めの桁を合わせて突き合わせていたが、型の無いテキストの中では
短い小数ほど偶然に一致し (実験 rank_fast の段2で 117 件のほぼ全部)、本物が埋もれた。
R2 が鳴りうる場面はもともと「登録の時点でログがあった」ときだけなので、その事実だけを出す。

R2 は、回す前に数えたもの (番地・命令の数・単射の検査) を予測と同じコミットに入れた門番でも、
段を分けた実験の2つめの段でも鳴る。どちらも正しい使い方で、見るのは
**何を見てから書いたかが README に書いてあるか**。

使い方:

    python3 tools/prereg_check.py experiments/<名前> ...   # 実験を名指しする
    python3 tools/prereg_check.py                        # origin/main..HEAD で変わった実験を見る
    python3 tools/prereg_check.py --base <ref>           # 比較先を変える

終了コード: 0 指摘なし (R0 だけを含む) / 1 R1〜R3 あり / 2 git が答えを返さなかった。
"""

from __future__ import annotations

import argparse
import difflib
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent

REGISTERED = re.compile(r"^## .*前に(?:書いた|決めた|数えた)")
H2 = re.compile(r"^## ")
# ※ の注記: 括弧ごと足したもの (「（※ …）」) と、記号だけを足したもの.
# 括弧ごとの注記は, 開き括弧に対応する閉じ括弧までを入れ子を数えて読む (注記の中のリンク
# 「[stage1.md](stage1.md)」の閉じ括弧で注記を終わらせない). 全角と半角の括弧は同じに数える
NOTE_OPEN = re.compile(r"\s*[（(]※")
NOTE_MARK = re.compile(r"\s*※")
OPENS, CLOSES = "（(", "）)"
ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)")


class GitError(RuntimeError):
    """git が答えを返さなかった。指摘ゼロと区別する。"""


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    message: str


Git = Callable[[list[str]], str]


def run_git(args: list[str], cwd: pathlib.Path = ROOT) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


# ---- 本文の読み方 (git を使わない) -----------------------------------------


def sections(text: str) -> dict[str, list[str]]:
    """登録した `##` の節を、見出し → 本文の行 で返す。本文は次の `##` まで。"""
    out: dict[str, list[str]] = {}
    current: str | None = None
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        if not fence and H2.match(line):
            current = line if REGISTERED.match(line) else None
            if current is not None:
                out[current] = []
            continue
        if current is not None:
            out[current].append(line)
    return out


def strip_notes(line: str) -> str:
    out = []
    i = 0
    while (m := NOTE_OPEN.search(line, i)) is not None:
        depth = 0
        end = None
        for j in range(m.end() - 2, len(line)):
            if line[j] in OPENS:
                depth += 1
            elif line[j] in CLOSES:
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is None:  # 閉じていない括弧は注記として読まない (記号だけを落とす)
            out.append(line[i : m.end() - 1])
            i = m.end()
            continue
        out.append(line[i : m.start()])
        i = end
    out.append(line[i:])
    return NOTE_MARK.sub("", "".join(out))


def line_changes(old: list[str], new: list[str]) -> Iterator[tuple[str, str, str]]:
    """登録の版 → いまの版で、変わった・消えた行を (種類, 前, 後) で返す。足した行は返さない。

    種類は "note" (※ を足しただけ) / "changed" / "removed"。
    """
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "insert"):
            continue
        before = old[i1:i2]
        after = new[j1:j2] if tag == "replace" else []
        for k, line in enumerate(before):
            if k < len(after):
                kind = "note" if strip_notes(after[k]) == strip_notes(line) else "changed"
                yield kind, line, after[k]
            else:
                yield "removed", line, ""


def run_starts(text: str) -> Iterator[datetime]:
    """進行ログの「開始」の行の時刻。"""
    for line in text.splitlines():
        if "開始" not in line:
            continue
        m = ISO.search(line)
        if m:
            yield datetime.fromisoformat(m.group(0).replace("Z", "+00:00"))


# ---- git から読む ---------------------------------------------------------


def registration(git: Git, readme: str, heading: str) -> tuple[str, datetime]:
    """見出しの行を初めて足したコミットと、その時刻。"""
    out = git(["log", "--reverse", "--format=%H %cI", "-S", heading, "--", readme])
    first = out.splitlines()[0].split() if out.strip() else []
    if len(first) != 2:
        raise GitError(f"{readme} の「{heading}」を足したコミットが見つからない")
    return first[0], datetime.fromisoformat(first[1])


def files_at(git: Git, commit: str, directory: str) -> list[str]:
    out = git(["ls-tree", "-r", "--name-only", commit, "--", directory])
    return [line for line in out.splitlines() if line]


def show(git: Git, commit: str, path: str) -> str:
    return git(["show", f"{commit}:{path}"])


def check_experiment(git: Git, directory: str) -> list[Finding]:
    readme = f"{directory}/README.md"
    now = show(git, "HEAD", readme)
    found: list[Finding] = []
    registered: list[tuple[datetime, str]] = []
    seen_commits: set[str] = set()
    for heading in sections(now):
        commit, at = registration(git, readme, heading)
        short = commit[:7]
        then = sections(show(git, commit, readme)).get(heading, [])
        where = f"{readme}「{heading[3:]}」"
        for kind, before, after in line_changes(then, sections(now)[heading]):
            if kind == "note":
                found.append(Finding("R0", where, f"{short} のあとで ※ を足した: {after.strip()}"))
            elif kind == "changed":
                found.append(
                    Finding(
                        "R1",
                        where,
                        f"{short} のあとで書き換えた: {before.strip()} → {after.strip()}",
                    )
                )
            else:
                found.append(Finding("R1", where, f"{short} のあとで消した: {before.strip()}"))

        registered.append((at, short))
        with_logs = files_at(git, commit, f"{directory}/logs")
        if with_logs and commit not in seen_commits:
            seen_commits.add(commit)
            names = " ".join(pathlib.PurePosixPath(p).name for p in with_logs[:8])
            more = f" ほか {len(with_logs) - 8} 件" if len(with_logs) > 8 else ""
            found.append(
                Finding(
                    "R2",
                    where,
                    f"登録の時点 ({short}) で logs/ にファイルが既にあった: {names}{more}。"
                    "予測の節が何を根拠にしたか (回す前に数えたもの・前の段の結果) を"
                    " README で確かめる",
                )
            )

    if registered:
        at, short = min(registered)
        for path in files_at(git, "HEAD", f"{directory}/logs"):
            if not pathlib.PurePosixPath(path).name.startswith("console"):
                continue
            early = [t for t in run_starts(show(git, "HEAD", path)) if t < at]
            if early:
                found.append(
                    Finding(
                        "R3",
                        readme,
                        f"{path} の本が、最初の登録 ({short}, {at.isoformat()}) より前に"
                        f"始まっている: {min(early).isoformat()}",
                    )
                )
    return found


def changed_experiments(git: Git, base: str) -> list[str]:
    out = git(["diff", "--name-only", f"{base}...HEAD", "--", "experiments"])
    dirs = {"/".join(p.split("/")[:2]) for p in out.splitlines() if p.count("/") >= 2}
    return sorted(d for d in dirs if files_at(git, "HEAD", f"{d}/README.md"))


def report(results: Iterable[tuple[str, list[Finding]]]) -> int:
    worst = 0
    for directory, found in results:
        if not found:
            print(f"{directory}: 登録した節に指摘なし")
            continue
        print(f"{directory}:")
        for f in found:
            print(f"  {f.rule} {f.where}: {f.message}")
            if f.rule != "R0":
                worst = 1
    return worst


def main(argv: list[str] | None = None, git: Git = run_git) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "experiments", nargs="*", help="experiments/<名前> (無指定なら base との差)"
    )
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    try:
        targets = [d.rstrip("/") for d in args.experiments] or changed_experiments(git, args.base)
        if not targets:
            print("登録した節を持つ実験の変更は無い")
            return 0
        return report((d, check_experiment(git, d)) for d in targets)
    except GitError as e:
        print(f"prereg_check: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
