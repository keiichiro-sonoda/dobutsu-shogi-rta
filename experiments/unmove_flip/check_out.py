#!/usr/bin/python3
"""書き出した成果物を確かめる (実験 unmove_flip。記録試行ではない)。

    python3 experiments/unmove_flip/check_out.py <書き出し先> <#33 の dat/>

1. ファイルの名前の集合と, ファイルごとの件数 (大きさ) が #33 本走の dat/ と同じ
2. 手数ごとの件数が oracle/distribution.tsv と同じ (1手勝ちはキャッチ局面 140,298,614 を除く.
   0手負けは distribution に行が無いので, ここでは見ない. 3 の指紋では見る)
3. 指紋 (手数ごとの件数・総和・XOR) が oracle/fingerprint.tsv と同じ
   (tools/fingerprint_dat.py --against)
ファイルの中の並びは揃えないので, バイト比較はしない。最後の行に PASS / FAIL を出す。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
N_CATCH = 140_298_614
NAME = re.compile(r"^(win|lose)(\d+)te_\d+\.bin$")


def sizes(d: pathlib.Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in d.iterdir() if p.is_file()}


def main(argv: list[str]) -> int:
    out, ref = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    a, b = sizes(out), sizes(ref)
    ok = True
    if set(a) != set(b):
        ok = False
        only_a, only_b = sorted(set(a) - set(b))[:10], sorted(set(b) - set(a))[:10]
        print(f"ファイルの名前が違う: 書き出しだけ {only_a} / dat/ だけ {only_b}")
    diff = [n for n in sorted(set(a) & set(b)) if a[n] != b[n]]
    if diff:
        ok = False
        print(f"件数が違うファイル: {len(diff)} 個 (例 {diff[:10]})")
    same = "同じ" if set(a) == set(b) and not diff else "違う"
    print(f"1. ファイル {len(a)} 個 (dat/ は {len(b)} 個). 名前と件数: {same}")
    count: dict[tuple[int, str], int] = {}
    for n, sz in a.items():
        m = NAME.match(n)
        if m:
            key = (int(m.group(2)), m.group(1))
            count[key] = count.get(key, 0) + sz // 8
    count[(1, "win")] = count.get((1, "win"), 0) - N_CATCH
    want = {}
    for line in (ROOT / "oracle" / "distribution.tsv").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        d, r, c = line.split("\t")
        want[(int(d), r)] = int(c)
    got = {k: v for k, v in count.items() if k[0] != 0}
    bad = sorted(k for k in set(want) | set(got) if want.get(k, 0) != got.get(k, 0))
    if bad:
        ok = False
        print(f"手数ごとの件数が違う: {bad[:10]}")
    print(f"2. 手数ごとの件数 ({len(want)} 行): {'distribution.tsv と同じ' if not bad else '違う'}")
    fp = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "fingerprint_dat.py"), str(out), "--against",
         str(ROOT / "oracle" / "fingerprint.tsv")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    last = (fp.stdout.strip().splitlines() or ["(出力なし)"])[-1]
    print(f"3. 指紋: {last} (終了コード {fp.returncode})")
    if fp.returncode != 0:
        ok = False
        print(fp.stdout[-2000:] + fp.stderr[-2000:])
    print("成果物の確かめ: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
