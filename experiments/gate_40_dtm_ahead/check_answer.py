#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (門番 #40。記録試行ではない)。

    python3 check_answer.py <dat/>

#40 は後退解析の unmoveStep で, 局面 i をふるう前に局面 i + 1 の候補を作って g_dtm の先読みを頼むようにしたが,
候補を作ることと番号を出すことは g_dtm も g_prep も見ず, ふるう・決めるの中身は変えていないので, 決める順も
found に積む順も変わらない (実験 dtm_ahead の一致の検査と, 完走 19 本の dat/ のバイト一致). dat/ は #39 とバイト一致するはず.
そこで両腕とも, dat/ の md5 一覧の sha256 (results/*/bytecompare.txt と同じ作り方) が #39 本走の値と
同じかを見る. #39 本走の値は results/39_rank_lean/bytecompare.txt の「md5_list_sha256:」の #39 の行
(#37〜#39 本走・門番 #39 の13本・実験 dtm_ahead の19本とも同じ値だった).
オラクル174行は run_one.sh が見る.
最後の行に PASS / FAIL。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BYTECOMPARE = ROOT / "results" / "39_rank_lean" / "bytecompare.txt"


def md5_list_sha(d: pathlib.Path) -> str:
    """find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def ref_sha() -> str:
    text = BYTECOMPARE.read_text(encoding="utf-8")
    m = re.search(r"^\s+#39 ([0-9a-f]{64})$", text, re.M)
    if not m:
        raise SystemExit(f"{BYTECOMPARE} に #39 の md5 一覧の sha256 が無い")
    return m.group(1)


def main(argv: list[str]) -> int:
    dat = pathlib.Path(argv[1])
    n = sum(1 for p in dat.iterdir() if p.is_file())
    got, want = md5_list_sha(dat), ref_sha()
    ok = got == want
    print(f"ファイル {n} 個. md5 一覧の sha256: {got[:12]} / #39 本走 {want[:12]} => "
          f"{'一致' if ok else '不一致'}")  # fmt: skip
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
