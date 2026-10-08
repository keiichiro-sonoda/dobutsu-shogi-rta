#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (門番 #34。記録試行ではない)。

    python3 check_answer.py <old|new> <dat/> <#33 本走の dat/>

old (impl/33_hot_layout): dat/ の md5 一覧の sha256 が #33 本走
  (results/33_hot_layout/bytecompare.txt) と一致。
new (impl/34_unmove): 後退解析の採番順が変わるので, 後退解析の側はバイト比較ではなく次で見る。
  1. 全探索の側のファイル (lose000te_* と, キャッチ局面を書く win001te_000〜028) が
     #33 本走とバイト一致 (キャッチ局面 140,298,614 を 5,000,000 ずつ区切ると 29 ファイル.
     030 までの残りは後退解析の1手勝ち)
  2. ファイルの名前の集合と, ファイルごとの件数 (大きさ) が #33 本走と同じ
  3. 指紋 (手数ごとの件数・総和・XOR) が oracle/fingerprint.tsv と同じ
     (tools/fingerprint_dat.py --against)
  ほかに, 後退解析の側のファイルのうち #33 本走とバイトまで同じものの数を出す
  (並びが揃ったかどうか. 判定には使わない)
オラクル174行は run_one.sh が tools/verify_log.py で見る。最後の行に PASS / FAIL。
"""

from __future__ import annotations

import hashlib
import math
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
N_CATCH = 140_298_614
BOARD_NUM_MAX = 5_000_000


def md5_list_sha(d: pathlib.Path) -> str:
    """results/*/bytecompare.txt の md5 一覧の sha256 と同じ値。

    find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def ref_sha() -> str:
    text = (ROOT / "results" / "33_hot_layout" / "bytecompare.txt").read_text(encoding="utf-8")
    m = re.search(r"#33 ([0-9a-f]{64})", text)
    if not m:
        raise SystemExit("results/33_hot_layout/bytecompare.txt に #33 の値が無い")
    return m.group(1)


def forward_side(name: str) -> bool:
    if name.startswith("lose000te_"):
        return True
    m = re.match(r"^win001te_(\d+)\.bin$", name)
    return bool(m) and int(m.group(1)) < math.ceil(N_CATCH / BOARD_NUM_MAX)


def main(argv: list[str]) -> int:
    arm, dat, ref = argv[1], pathlib.Path(argv[2]), pathlib.Path(argv[3])
    if arm == "old":
        got = md5_list_sha(dat)
        ok = got == ref_sha()
        verdict = "一致" if ok else "不一致"
        print(f"md5 一覧の sha256: {got[:12]} / #33 本走 {ref_sha()[:12]} => {verdict}")
        print("答えの検査: " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    a = {p.name: p for p in dat.iterdir() if p.is_file()}
    b = {p.name: p for p in ref.iterdir() if p.is_file()}
    fwd = sorted(n for n in b if forward_side(n))
    fwd_bad = [n for n in fwd if n not in a or a[n].read_bytes() != b[n].read_bytes()]
    print(f"1. 全探索の側のファイル {len(fwd)} 個: #33 本走とバイト一致しないもの "
          f"{len(fwd_bad)} 個 {fwd_bad[:5]}")  # fmt: skip
    size_bad = sorted(n for n in set(a) & set(b) if a[n].stat().st_size != b[n].stat().st_size)
    names_ok = set(a) == set(b)
    same_names = "同じ" if names_ok else "違う"
    print(f"2. ファイル {len(a)} 個 (#33 本走は {len(b)} 個). 名前の集合: {same_names} / "
          f"件数の違うファイル {len(size_bad)} 個 {size_bad[:5]}")  # fmt: skip
    fp = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "fingerprint_dat.py"), str(dat), "--against",
         str(ROOT / "oracle" / "fingerprint.tsv")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    last = (fp.stdout.strip().splitlines() or ["(出力なし)"])[-1]
    print(f"3. 指紋: {last.strip()} (終了コード {fp.returncode})")
    if fp.returncode != 0:
        print(fp.stdout[-2000:] + fp.stderr[-2000:])
    back = sorted(n for n in set(a) & set(b) if not forward_side(n))
    same = sum(1 for n in back if a[n].read_bytes() == b[n].read_bytes())
    print(f"参考: 後退解析の側のファイル {len(back)} 個のうち, "
          f"#33 本走とバイトまで同じもの {same} 個")  # fmt: skip
    ok = not fwd_bad and names_ok and not size_bad and fp.returncode == 0
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
