#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (門番 #37。記録試行ではない)。run_one.sh が呼ぶ。

    python3 check_answer.py <old|new> <dat/> <手数ごとの集合の出力先 (new だけ)>

比べる相手は #36 本走の dat/ (runs/ の下. 読むだけで, 中へ cd しない)。オラクル174行は run_one.sh が見る。

old (impl/36_bb_unmove): dat/ の md5 一覧の sha256 (results/*/bytecompare.txt と同じ作り方) が #36 本走の値
  (results/36_bb_unmove/bytecompare.txt の #36 の行. #34・#35 本走とも同じ値) と同じ。
new (impl/37_mirror1): 前任の候補の並びが変わり, 後退解析が局面を決める順と後退解析の側の dat/ の並びが
  変わるので, 後退解析の側はバイト比較ではなく次で見る (門番 #34 と同じ形)。
  1. 全探索の側のファイル (lose000te_* と, キャッチ局面を書く win001te_000〜028 の 31 ファイル) が
     #36 本走とバイト一致 (全探索は変えていない)
  2. ファイルの名前の集合と, ファイルごとの件数 (大きさ) が #36 本走と同じ
  3. 指紋 (手数ごとの件数・総和・XOR) が oracle/fingerprint.tsv と同じ (tools/fingerprint_dat.py --against)
  4. 手数ごとに束ねた集合が #36 本走と同じ (experiments/sorted_compare_34/depth_compare.py.
     出力の列名の 33 は #36 本走, 34 は new の dat/)
  ほかに, 後退解析の側のファイルのうち #36 本走とバイトまで同じものの数 (判定には使わない) と,
  dat/ の md5 一覧の sha256 の全桁 (new の本ごとに同じかを stop_rule.py が見る) を出す。
最後の行に PASS / FAIL。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REF = ROOT / "runs" / "20261017-105455_36_bb_unmove" / "dat"
BYTECOMPARE = ROOT / "results" / "36_bb_unmove" / "bytecompare.txt"
SC34 = ROOT / "experiments" / "sorted_compare_34"
sys.path.insert(0, str(SC34))
from compare import forward_side  # noqa: E402


def md5_list_sha(d: pathlib.Path) -> str:
    """find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def ref_sha() -> str:
    text = BYTECOMPARE.read_text(encoding="utf-8")
    m = re.search(r"^\s+#36 ([0-9a-f]{64})$", text, re.M)
    if not m:
        raise SystemExit(f"{BYTECOMPARE} に #36 の md5 一覧の sha256 が無い")
    return m.group(1)


def old(dat: pathlib.Path) -> bool:
    got, want = md5_list_sha(dat), ref_sha()
    ok = got == want
    print(f"md5 一覧の sha256: {got[:12]} / #36 本走 {want[:12]} => {'一致' if ok else '不一致'}")
    return ok


def new(dat: pathlib.Path, depth_out: pathlib.Path) -> bool:
    a = {p.name: p for p in dat.iterdir() if p.is_file()}
    b = {p.name: p for p in REF.iterdir() if p.is_file()}
    fwd = sorted(n for n in b if forward_side(n))
    fwd_bad = [n for n in fwd if n not in a or a[n].read_bytes() != b[n].read_bytes()]
    print(f"1. 全探索の側のファイル {len(fwd)} 個: #36 本走とバイト一致しないもの "
          f"{len(fwd_bad)} 個 {fwd_bad[:5]}")  # fmt: skip
    size_bad = sorted(n for n in set(a) & set(b) if a[n].stat().st_size != b[n].stat().st_size)
    names_ok = set(a) == set(b)
    print(f"2. ファイル {len(a)} 個 (#36 本走は {len(b)} 個). 名前の集合: "
          f"{'同じ' if names_ok else '違う'} / 件数の違うファイル {len(size_bad)} 個 "
          f"{size_bad[:5]}")  # fmt: skip
    fp = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "fingerprint_dat.py"), str(dat), "--against",
         str(ROOT / "oracle" / "fingerprint.tsv")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    last = (fp.stdout.strip().splitlines() or ["(出力なし)"])[-1]
    print(f"3. 指紋: {last.strip()} (終了コード {fp.returncode})")
    if fp.returncode != 0:
        print(fp.stdout[-2000:] + fp.stderr[-2000:])
    dc = subprocess.run(
        [sys.executable, str(SC34 / "depth_compare.py"), str(REF), str(dat)],
        capture_output=True, text=True, check=False, cwd=str(SC34),
    )  # fmt: skip
    depth_out.write_text(dc.stdout, encoding="utf-8")
    rows = [ln.split("\t") for ln in dc.stdout.splitlines() if ln and not ln.startswith(("#", "group"))]
    same = sum(1 for r in rows if r[6] == "True")
    print(f"4. 手数ごとに束ねた集合: {len(rows)} 個のうち一致 {same} 個 (終了コード {dc.returncode})")
    if dc.stderr:
        print(dc.stderr[-2000:])
    back = sorted(n for n in set(a) & set(b) if not forward_side(n))
    bsame = sum(1 for n in back if a[n].read_bytes() == b[n].read_bytes())
    print(f"参考: 後退解析の側のファイル {len(back)} 個のうち, "
          f"#36 本走とバイトまで同じもの {bsame} 個")  # fmt: skip
    print(f"md5 一覧の sha256 (全桁): {md5_list_sha(dat)}")
    return (
        not fwd_bad and names_ok and not size_bad and fp.returncode == 0 and dc.returncode == 0
        and len(rows) == 176 and same == 176
    )  # fmt: skip


def main(argv: list[str]) -> int:
    arm, dat = argv[1], pathlib.Path(argv[2]).resolve()
    if not REF.is_dir():
        raise SystemExit(f"#36 本走の dat/ が無い: {REF}")
    if arm == "old":
        ok = old(dat)
    elif arm == "new":
        ok = new(dat, pathlib.Path(argv[3]))
    else:
        raise SystemExit(f"腕は old / new: {arm}")
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
