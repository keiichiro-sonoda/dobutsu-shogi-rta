#!/usr/bin/python3
"""比べる2つの dat/ が, 記録 #33・#34 の本走そのものかを確かめる (記録試行ではない)。

    python3 experiments/sorted_compare_34/identify.py <#33 の作業ディレクトリ> \
        <#34 の作業ディレクトリ> > experiments/sorted_compare_34/logs/identify.txt

作業ディレクトリは tools/run.sh が runs/ の下に作るもの (dat/ と, 本走の生ログを持つ)。
照らすもの:
- 本走の生ログ (env.txt・time.txt・vmstat.tsv・hugefree.txt・freq.log・kaiseki_log/ の tsv 3つ) が,
  results/<記録>/ の同じ名前のファイルとバイト一致する。#33 の env.txt は, 本走のあとで
  finished の2行を足してあるので, その2行を除いて比べる
- dat/ のファイルの数と合計バイト数が results/<記録>/sizecheck.txt と同じ
- #33: dat/ の md5 一覧の sha256 が results/33_hot_layout/bytecompare.txt の #33 の値と同じ
  (一覧の作り方は bytecompare.txt と同じ: ./<名前> を C ロケールの順に並べた md5sum の出力)
- #34: results/34_unmove/ には並びに依る dat/ の値 (md5 一覧) が残っていない。代わりに,
  dat/ のファイルの更新時刻が, 本走の開始 (env.txt) から 開始 ＋ 経過時間 (time.txt) の間に
  収まることを見る (本走のあとで書き換わっていない)。md5 一覧の sha256 はこの先のために出しておく
どれかが合わなければ終了コード 1。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOGS = (
    ("env.txt", "env.txt"),
    ("time.txt", "time.txt"),
    ("vmstat.tsv", "vmstat.tsv"),
    ("hugefree.txt", "hugefree.txt"),
    ("freq.log", "freq.log"),
    ("kaiseki_log/forward.tsv", "forward.tsv"),
    ("kaiseki_log/forward_summary.tsv", "forward_summary.tsv"),
    ("kaiseki_log/retreat_summary.tsv", "retreat_summary.tsv"),
)


def md5_list_sha256(dat: pathlib.Path) -> str:
    lines = []
    for name in sorted(p.name for p in dat.iterdir()):
        h = hashlib.md5((dat / name).read_bytes()).hexdigest()
        lines.append(f"{h}  ./{name}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def drop_finished(text: bytes) -> bytes:
    keep = (ln for ln in text.splitlines(keepends=True))
    return b"".join(ln for ln in keep if not ln.startswith((b"finished:", b"finished_jst:")))


def check(label: str, run: pathlib.Path, res: pathlib.Path) -> bool:
    ok = True
    print(f"== #{label}: {run.name} と results/{res.name}/")
    for src, dst in LOGS:
        a, b = (run / src).read_bytes(), (res / dst).read_bytes()
        if src == "env.txt":
            b = drop_finished(b)
        same = a == b
        ok &= same
        print(f"  生ログ {src}: {'一致' if same else '不一致'}")
    dat = run / "dat"
    files = [p for p in dat.iterdir()]
    nbytes = sum(p.stat().st_size for p in files)
    size = (res / "sizecheck.txt").read_text(encoding="utf-8")
    want_files = int(re.search(r"^files:\s+(\d+)", size, re.M).group(1))
    want_bytes = int(re.search(r"^bytes:\s+(\d+)", size, re.M).group(1))
    same = (len(files), nbytes) == (want_files, want_bytes)
    ok &= same
    print(
        f"  dat/: {len(files)} ファイル / {nbytes} バイト"
        f" (sizecheck.txt は {want_files} / {want_bytes}): {'一致' if same else '不一致'}"
    )
    digest = md5_list_sha256(dat)
    print(f"  dat/ の md5 一覧の sha256: {digest}")
    return ok


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    run33, run34 = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    ok = check("33", run33, ROOT / "results/33_hot_layout")
    bc = (ROOT / "results/33_hot_layout/bytecompare.txt").read_text(encoding="utf-8")
    want = re.search(r"^\s+#33 ([0-9a-f]{64})$", bc, re.M).group(1)
    got = md5_list_sha256(run33 / "dat")
    verdict = "一致" if got == want else "不一致"
    print(f"  results/33_hot_layout/bytecompare.txt の #33: {want}: {verdict}")
    ok &= got == want
    print()
    ok &= check("34", run34, ROOT / "results/34_unmove")
    env = (ROOT / "results/34_unmove/env.txt").read_text(encoding="utf-8")
    start = dt.datetime.fromisoformat(re.search(r"^started:\s+(\S+)", env, re.M).group(1))
    tm = (ROOT / "results/34_unmove/time.txt").read_text(encoding="utf-8")
    m = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)", tm)
    elapsed = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    end = start + dt.timedelta(seconds=elapsed)
    mt = [dt.datetime.fromtimestamp(p.stat().st_mtime, dt.UTC) for p in (run34 / "dat").iterdir()]
    # started は秒で切ってあり, time.txt の経過は bash の起動から測る。両端に 1 秒の余裕を見る
    inside = start - dt.timedelta(seconds=1) <= min(mt) and max(mt) <= end + dt.timedelta(seconds=1)
    ok &= inside
    print(f"  dat/ の更新時刻: {min(mt).isoformat()} 〜 {max(mt).isoformat()}")
    print(
        f"  本走: {start.isoformat()} 〜 {end.isoformat()} (開始 ＋ 経過 {elapsed:.2f} 秒): "
        f"{'収まる' if inside else '収まらない'}"
    )
    print()
    print(f"判定: {'本走の dat/ と照らせた' if ok else '照らせない'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
