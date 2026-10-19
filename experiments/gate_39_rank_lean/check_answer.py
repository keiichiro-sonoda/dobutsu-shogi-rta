#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (門番 #39。記録試行ではない)。

    python3 check_answer.py <dat/>

#39 は局面の番号の計算 rankOf の命令を減らしたが, 番号の値は1つも変わらない
(experiments/rank_fast が到達可能な全局面・その全候補・乱数の盤 1 億で確かめた). 発見済みの表・準備の配列・
手数の配列の添字も, 全探索の待ち行列も, 後退解析が局面を決める順も変わらないので, dat/ は #38 とバイト一致するはず.
そこで両腕とも, dat/ の md5 一覧の sha256 (results/*/bytecompare.txt と同じ作り方) が #38 本走の値と
同じかを見る. #38 本走の値は results/38_precheck/bytecompare.txt の「md5_list_sha256:」の #38 の行
(#37 本走・門番 #38 の13本とも同じ値だった).
オラクル174行は run_one.sh が見る.
最後の行に PASS / FAIL。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BYTECOMPARE = ROOT / "results" / "38_precheck" / "bytecompare.txt"


def md5_list_sha(d: pathlib.Path) -> str:
    """find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def ref_sha() -> str:
    text = BYTECOMPARE.read_text(encoding="utf-8")
    m = re.search(r"^\s+#38 ([0-9a-f]{64})$", text, re.M)
    if not m:
        raise SystemExit(f"{BYTECOMPARE} に #38 の md5 一覧の sha256 が無い")
    return m.group(1)


def main(argv: list[str]) -> int:
    dat = pathlib.Path(argv[1])
    n = sum(1 for p in dat.iterdir() if p.is_file())
    got, want = md5_list_sha(dat), ref_sha()
    ok = got == want
    print(f"ファイル {n} 個. md5 一覧の sha256: {got[:12]} / #38 本走 {want[:12]} => "
          f"{'一致' if ok else '不一致'}")  # fmt: skip
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
