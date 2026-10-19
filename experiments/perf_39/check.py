#!/usr/bin/python3
"""1本ごとの検査 (実験 perf_39。記録試行ではない)。run_one.sh が呼ぶ。

    python3 check.py huge <ラベル>      thp_fault_fallback の前後差が 0 で, 巨大ページが表と配列の全部に付いた
    python3 check.py rounds <ラベル>    forward.tsv の件数の列が results/39_rank_lean/forward.tsv と同じ
    python3 check.py answer <dat/>     dat/ の md5 一覧の sha256 が #39 本走と同じ (a982b554596c…. #37・#38 本走とも同じ値)

experiments/perf_38/check.py の写しを #39 に向けたもの。巨大ページのしきい値は門番 #39 と同じ値。
"""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = pathlib.Path(os.environ.get("LOGS", HERE / "logs"))  # 試しの本は run_one.sh が logs/trial/ を渡す
REF = ROOT / "results" / "39_rank_lean" / "forward.tsv"
BYTECOMPARE = ROOT / "results" / "39_rank_lean" / "bytecompare.txt"
# 発見済み表は 855,232,344 ビットを 2 MiB に切り上げた 51 枚。準備の配列と手数の配列は,
# どちらも 855,232,344 バイトを 2 MiB に切り上げた 408 枚 (835,584 kB) の和
HUGE = {
    ("forward_summary", "anonhuge_seen_kB"): 104_448,
    ("retreat_summary", "anonhuge_init_kB"): 1_671_168,
    ("retreat_summary", "anonhuge_loop_kB"): 1_671_168,
}
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")


def value(label: str, name: str, key: str) -> int:
    text = (LOGS / f"{label}_{name}.tsv").read_text(encoding="utf-8")
    values = [v for k, _, v in (ln.partition("\t") for ln in text.splitlines()) if k == key]
    if len(values) != 1:
        raise SystemExit(f"{label}_{name}.tsv に {key} が1行ない")
    return int(values[0])


def huge(label: str) -> bool:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index("thp_fault_fallback")
    fb = int(rows[2][i]) - int(rows[1][i])
    print(f"thp_fault_fallback の前後差: {fb}")
    ok = fb == 0
    for (name, key), need in HUGE.items():
        got = value(label, name, key)
        print(f"{key}: {got} kB (要 {need} kB 以上)")
        ok &= got >= need
    return ok


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds(label: str) -> bool:
    a, b = table(REF), table(LOGS / f"{label}_forward.tsv")
    ok = len(a) == len(b) and all(ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in KEYS)
    print(f"{len(b)} ラウンド（#39 は {len(a)}）/ 件数の列 {'一致' if ok else '**不一致**'}")
    return ok


def md5_list_sha(d: pathlib.Path) -> str:
    """find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ (dat/ の中へ cd しない)。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def answer(dat: pathlib.Path) -> bool:
    m = re.search(r"^\s+#39 ([0-9a-f]{64})$", BYTECOMPARE.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"{BYTECOMPARE} に #39 の md5 一覧の sha256 が無い")
    got = md5_list_sha(dat)
    ok = got == m.group(1)
    print(f"md5 一覧の sha256: {got} / #39 本走 {m.group(1)[:12]} => {'一致' if ok else '**不一致**'}")
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return ok


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("huge", "rounds", "answer"):
        raise SystemExit(__doc__)
    what, arg = sys.argv[1], sys.argv[2]
    ok = huge(arg) if what == "huge" else rounds(arg) if what == "rounds" else answer(pathlib.Path(arg))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
