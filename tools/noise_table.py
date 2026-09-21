#!/usr/bin/env python3
"""段ごとの揺れの表を、門番のログから組み立てる。

`docs/measurement-noise.md` の「段ごとの揺れ」の表は、標本とそこから計算した
平均・sd・変動係数を同じ行に並べている。**手で書くと必ずずれる。**
記録 #15 のレビューで実際に出た4件はどれもこの表まわりだった:

- 1桁に丸めた標本から sd を計算し直して 2.52 を 2.50 にした（改悪）
- 自分のスクリプトが 36.9 と出した sd を 36.8 と書いた
- 「`gate_14` の README が 2.52 と書いている」と、無い記述を引用した
- 下書きの状態を指した説明をコミットメッセージに書いた

前の2つは計算を機械に渡せば消える。そこでこのツールが門番の生ログから表を作り、
文書の中身と突き合わせる。**文書は生成物**で、手で直さない。

⚠️ **標本は丸める前の値から計算する。** 174段ループの3本を1桁に丸めた
291.1 / 293.4 / 296.1 から sd を出すと 2.50 になるが、生値 291.08 / 293.43 / 296.12
から出るのは 2.52。`s2hms()` を通した段（P0〜P4）はログの時点で秒未満が
切り捨てられているので、整数がそのまま生値。

載せる条件は2つ。**このツールが読める形でログがコミットされていること**
（`<ラベル>_main.log` と `console.log` を並べた門番の形。いまは `gate_12` /
`gate_14` / `gate_15` の3つだけがこの形）と、**その段のコードが旧新でバイト同一で
あること**。P4 は `gate_12` の、P2 は `gate_15` のレバーなので、その組み合わせは載せない。

⚠️ **「全部載っている」とは言っていない。** 条件を満たす組み合わせは他にもある。
条件を満たさない観測の置き場所は `docs/measurement-noise.md` に書いてある。

使い方:

    python3 tools/noise_table.py            # 検査 (文書と食い違えば終了コード 1)
    python3 tools/noise_table.py --write    # 文書の表を組み直す
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "measurement-noise.md"

START = "<!-- noise-table:start -->"
END = "<!-- noise-table:end -->"

HEADER = (
    "| 段 | 標本（昇順） | 本数 | 平均 | sd | 変動係数 | 出どころ |\n|---|---|---|---|---|---|---|"
)

# main.log に出る段の見出し。s2hms() を通しているので秒未満は切り捨て済み
PHASE_LINES = {
    "P0": "P0 読み込み",
    "P1": "P1 索引",
    "P2": "P2 後続生成",
    "P4": "P4 前任リスト",
}
# 後退解析の合計から測った4段を引いた残り。174段ループとループ外の初期化・解放を含む
RESIDUAL = "174段＋残差"

HMS = re.compile(r"(\d+)時間(\d+)分(\d+)秒")
START_LINE = re.compile(r"^=== 開始 (?P<label>\S+) ")
RETREAT_TOTAL = re.compile(r"^後退解析の所要時間：(?P<sec>[\d.]+) 秒")


@dataclasses.dataclass(frozen=True)
class Row:
    """表の1行。どの門番のどの本から、どの段を取るか。"""

    name: str
    phase: str
    gate: str
    prefix: str
    note: str
    highlight: bool = False


# ⚠️ 並べるのは「その段のコードがバイト同一な観測」だけ。
#    評価しようとしている測定を雑音の基準に使うと循環する（CLAUDE.md）。
ROWS = (
    Row("P0 読み込み", "P0", "gate_12_c_predecessors", "", "旧新6本"),
    Row("P0 読み込み", "P0", "gate_15_c_successors", "old", "旧8本"),
    Row("P1 索引", "P1", "gate_12_c_predecessors", "", "旧新6本"),
    Row("P1 索引", "P1", "gate_14_c_retreat", "", "旧新6本"),
    Row("P2 後続生成", "P2", "gate_12_c_predecessors", "", "旧新6本"),
    Row("**P2 後続生成**", "P2", "gate_14_c_retreat", "", "旧新6本", True),
    Row("P2 後続生成", "P2", "gate_15_c_successors", "old", "旧8本"),
    Row("P4 前任リスト", "P4", "gate_15_c_successors", "old", "旧8本"),
    Row("**174段＋残差**", RESIDUAL, "gate_14_c_retreat", "old", "旧3本", True),
)


def hms_to_seconds(text: str) -> int:
    m = HMS.search(text)
    if not m:
        raise ValueError(f"時刻の書式が読めない: {text!r}")
    h, mi, s = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s


def logs_dir(gate: str) -> pathlib.Path:
    d = ROOT / "experiments" / gate / "logs"
    if not d.is_dir():
        raise FileNotFoundError(f"門番のログが無い: {d}")
    return d


def labels(gate: str, prefix: str) -> list[str]:
    found = sorted(
        p.name[: -len("_main.log")]
        for p in logs_dir(gate).glob("*_main.log")
        if p.name.startswith(prefix)
    )
    if not found:
        raise FileNotFoundError(f"{gate} に {prefix!r} で始まる main.log が無い")
    return found


def phase_seconds(gate: str, label: str, phase: str) -> int:
    head = PHASE_LINES[phase]
    text = (logs_dir(gate) / f"{label}_main.log").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(head + "："):
            return hms_to_seconds(line)
    raise ValueError(f"{gate}/{label} に {head} の行が無い")


def retreat_totals(gate: str) -> dict[str, float]:
    """console.log から、本ごとの後退解析の所要時間（秒）を拾う。"""
    out: dict[str, float] = {}
    label = None
    for line in (logs_dir(gate) / "console.log").read_text(encoding="utf-8").splitlines():
        m = START_LINE.match(line)
        if m:
            label = m.group("label")
            continue
        t = RETREAT_TOTAL.match(line)
        if t and label is not None:
            out[label] = float(t.group("sec"))
            label = None
    if not out:
        raise ValueError(f"{gate}/console.log から所要時間を拾えない")
    return out


def samples(row: Row) -> list[float]:
    names = labels(row.gate, row.prefix)
    if row.phase != RESIDUAL:
        return sorted(float(phase_seconds(row.gate, n, row.phase)) for n in names)
    totals = retreat_totals(row.gate)
    out: list[float] = []
    for n in names:
        if n not in totals:
            raise ValueError(f"{row.gate}/console.log に {n} の所要時間が無い")
        measured = sum(phase_seconds(row.gate, n, p) for p in PHASE_LINES)
        out.append(round(totals[n] - measured, 2))
    return sorted(out)


def show(values: list[float]) -> str:
    if all(v == int(v) for v in values):
        return " / ".join(str(int(v)) for v in values)
    return " / ".join(f"{v:.2f}" for v in values)


def render_row(row: Row) -> str:
    v = samples(row)
    sd = statistics.stdev(v)
    mean = statistics.fmean(v)
    cv = sd / mean * 100
    cvs = f"**{cv:.2f}%**" if row.highlight else f"{cv:.2f}%"
    src = f"[`{row.gate}`](../experiments/{row.gate}/) の{row.note}"
    return f"| {row.name} | {show(v)} | {len(v)} | {mean:.2f} | {sd:.2f} | {cvs} | {src} |"


def render() -> str:
    return "\n".join([HEADER, *(render_row(r) for r in ROWS)])


def spreads() -> list[tuple[float, float]]:
    """`sd X / Y%` の書き方と突き合わせるための (sd, 変動係数) の一覧。"""
    out = []
    for row in ROWS:
        v = samples(row)
        sd = statistics.stdev(v)
        out.append((round(sd, 2), round(sd / statistics.fmean(v) * 100, 2)))
    return out


def shown_path(path: pathlib.Path) -> str:
    """リポジトリの中なら相対で見せる。外なら そのまま (テストが差し替えるため)。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def split_doc() -> tuple[str, str, str]:
    text = DOC.read_text(encoding="utf-8")
    for marker in (START, END):
        if text.count(marker) != 1:
            raise ValueError(f"{DOC} に {marker} がちょうど1つ無い")
    i = text.index(START) + len(START)
    j = text.index(END)
    return text[:i], text[i:j], text[j:]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="文書の表を組み直す")
    args = ap.parse_args(argv)

    head, body, tail = split_doc()
    want = f"\n{render()}\n"
    if args.write:
        DOC.write_text(head + want + tail, encoding="utf-8")
        print(f"{shown_path(DOC)} の表を組み直した（{len(ROWS)} 行）")
        return 0
    if body == want:
        print(f"noise_table: 表は門番のログと一致している（{len(ROWS)} 行）")
        return 0
    print("noise_table: 文書の表が門番のログから作った表と違う")
    print(
        "".join(
            difflib.unified_diff(
                body.splitlines(keepends=True),
                want.splitlines(keepends=True),
                fromfile="文書",
                tofile="ログから生成",
                n=0,
            )
        )
    )
    print("python3 tools/noise_table.py --write で組み直せる")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
