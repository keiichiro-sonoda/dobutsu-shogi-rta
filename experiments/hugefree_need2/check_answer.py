#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (実験 hugefree_need2。記録試行ではない)。

    python3 check_answer.py <dat/>

dat/ の md5 一覧の sha256 (results/*/bytecompare.txt と同じ作り方) が, #38 本走の値
(results/38_precheck/bytecompare.txt の「#38」の行) と同じかを見る。実装は impl/38_precheck のままなので,
dat/ は #38 本走とバイト一致するはず。オラクル174行は run_one.sh が見る。最後の行に PASS / FAIL。
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
