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
| R2 | 予測の節が、登録の時点でこの実験の `logs/` にあった数 (＝見たあとの数) を引いている |
| R3 | 回す前のはずの本が、登録より前に始まっている (`logs/console*.log` の「開始」) |
| R3 | 登録の時点で `logs/` にファイルが既にあった (時刻の無いログも捕まえる) |
| R0 | 参考: `※` の注記を足しただけの行 (注記に「あとで足した」と書いてあるかを目で見る) |

「登録した節」は、見出しに「〜前に書いた」「〜前に決めた」「〜前に数えた」を含む `##` の節。
「登録のコミット」は、その見出しの行を初めて足したコミット。

R2 は「見たあとの数」を次のように絞る。
- 予測の節 (見出しに「予測」「見込み」「事前登録」) の数を、登録の版から取る
- 登録のコミットの時点で `<実験>/logs/` にあったファイルの数と、丸めの桁を合わせて比べる
  (予測の 9.8 は、ログの 9.773 と同じ数として扱う)
- ログの側の数が、登録のコミットの親の時点で、この実験の外 (記録・ほかの実験) に既に
  書いてあったなら、前から知っていた数なので外す (辺の総数 938671869 など)
- 3桁以下の整数と、有効数字1桁の小数は見ない (記録の番号や「0.5〜1.5」のような幅で鳴りすぎる)
- 予測の行が出どころを名指ししている (`#28`・`gate_18_opt` のような、ほかの記録・実験・
  `results/`) なら外す。「gate_18_opt の −3.75 と同程度」は、たまたまこの実験のログにも
  3.747 があっても、前から知っていた数

R2 が見ないもの (目で見る):
- **前から知っていた数から計算できる数。** 探すのはログの値そのもので、割り算や和は見ない。
  実験 unmove_bench の「平均 3.8」は辺の総数 ÷ 全局面 (938,671,869 ÷ 246,803,167) で回す前に
  出せたが、ログの 3.803 はリポジトリに無いので鳴る。README に出どころを書けば読む人には分かる
- **出どころを1つ名指しした行の、ほかの数。** 名指しは行単位で見るので、`#33` が1つある行は
  同じ行の見たあとの数もまとめて外れる
- **ログから計算した数** (「候補の 61% が捨てられる」) と、数でない見立て

R3 の2つめの形は、回す前に数えたもの (番地・命令の数・単射の検査) を予測と同じコミットに
入れた門番でも鳴る。それが回す前に数えたものか、本を回した結果かを README で確かめる。

⚠️ R2 に出た数が、すべて悪いわけではない。「回す前に数えた」節 (番地・命令の数) を予測が
   引くのは正しい使い方。見るのは、**その数を回す前に知り得たと README に書いてあるか**。
   書いてなければ、事前の見込みではなく、見たあとの見込みになっている。

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
from decimal import ROUND_HALF_UP, Decimal

ROOT = pathlib.Path(__file__).resolve().parent.parent

REGISTERED = re.compile(r"^## .*前に(?:書いた|決めた|数えた)")
PREDICTION = re.compile(r"予測|見込み|事前登録")
H2 = re.compile(r"^## ")
NUMBER = re.compile(
    r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|(?<![\d.,])\d+(?:\.\d+)?(?![\d])"
)
# ※ の注記: 括弧ごと足したもの (「（※ …）」) と、記号だけを足したもの
NOTE = re.compile(r"\s*[（(]※[^）)]*[）)]|\s*※")
# 予測の行が、数の出どころとして名指しするもの (この実験の外の記録・実験・証拠)
CITE = re.compile(r"#\d+|gate_\w+|lever_scan\w*|gen_bench|unmove_bench|numa_bind|results/|\w+_\w+/")
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
    return NOTE.sub("", line)


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


def numbers(text: str) -> Iterator[tuple[str, Decimal]]:
    """数を (書いてあるとおりの文字列, 値) で返す。カンマ区切りも1つの数として読む。"""
    for m in NUMBER.finditer(text):
        word = m.group(0)
        yield word, Decimal(word.replace(",", ""))


def decimals(word: str) -> int:
    return len(word.split(".", 1)[1]) if "." in word else 0


def worth_checking(word: str, value: Decimal) -> bool:
    """鳴りすぎる数を外す: 3桁以下の整数と、有効数字1桁の小数。"""
    if decimals(word) == 0:
        return len(word.replace(",", "")) >= 4
    return len(word.replace(",", "").replace(".", "").lstrip("0")) >= 2 and value != 0


def same_number(pred: str, pred_value: Decimal, log_value: Decimal) -> bool:
    """予測の桁に丸めたら同じか。ログのほうが粗い (桁が少ない) ときは比べない。"""
    places = decimals(pred)
    if places == 0:
        return log_value == pred_value
    return log_value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) == pred_value


def cites_elsewhere(line: str, own: str) -> bool:
    """予測の行が、この実験の外の出どころを名指ししているか。"""
    return any(m.group(0).rstrip("/") != own for m in CITE.finditer(line))


def seen_numbers(
    prediction: str, logs: dict[str, str], own: str = ""
) -> Iterator[tuple[str, str, int, str]]:
    """予測の数のうち、ログにも出てくるものを (予測の数, ログ, 行番号, ログの数) で返す。

    出どころを名指しした行の数は外す (`cites_elsewhere`)。`own` はこの実験の名前。
    """
    wanted = [
        (t, v)
        for line in prediction.splitlines()
        if not cites_elsewhere(line, own)
        for t, v in numbers(line)
        if worth_checking(t, v)
    ]
    seen: set[tuple[str, str]] = set()
    for path, text in sorted(logs.items()):
        for lineno, line in enumerate(text.splitlines(), 1):
            for log_word, log_value in numbers(line):
                for word, value in wanted:
                    if decimals(log_word) < decimals(word):
                        continue
                    if (word, log_word) in seen:
                        continue
                    if same_number(word, value, log_value):
                        seen.add((word, log_word))
                        yield word, path, lineno, log_word


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


def known_before(git: Git, commit: str, word: str, directory: str) -> bool:
    """ログの数が、登録のコミットの親の時点で、この実験の外に書いてあったか。"""
    plain = word.replace(",", "")
    forms = {re.escape(plain), re.escape(word)}
    pattern = "(^|[^0-9.,])(" + "|".join(sorted(forms)) + ")([^0-9]|$)"
    try:
        out = git(["grep", "-l", "-E", "-e", pattern, f"{commit}^", "--", ".", f":!{directory}"])
    except GitError:
        # git grep は見つからないとき終了コード 1 を返す。親が無いコミットもここに来る
        return False
    return bool(out.strip())


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

        if PREDICTION.search(heading):
            logs = {
                path: show(git, commit, path) for path in files_at(git, commit, f"{directory}/logs")
            }
            for word, path, lineno, log_word in seen_numbers(
                "\n".join(then), logs, pathlib.PurePosixPath(directory).name
            ):
                if known_before(git, commit, log_word, directory):
                    continue
                found.append(
                    Finding(
                        "R2",
                        where,
                        f"予測の {word} は、登録 ({short}) の時点で既にあった "
                        f"{path}:{lineno} の {log_word} と同じ数",
                    )
                )

        registered.append((at, short))
        with_logs = files_at(git, commit, f"{directory}/logs")
        if with_logs and commit not in seen_commits:
            seen_commits.add(commit)
            names = " ".join(pathlib.PurePosixPath(p).name for p in with_logs[:8])
            more = f" ほか {len(with_logs) - 8} 件" if len(with_logs) > 8 else ""
            found.append(
                Finding(
                    "R3",
                    where,
                    f"登録の時点 ({short}) で logs/ にファイルが既にあった: "
                    f"{names}{more}。回す前に数えたものか、本を回した結果かを README で確かめる",
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
