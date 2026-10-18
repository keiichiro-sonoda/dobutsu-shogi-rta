#!/usr/bin/python3
"""1本の dat/ の答えを確かめる (門番 #38。記録試行ではない)。

    python3 check_answer.py <dat/>

#38 は全探索の生成器にキャッチの先行判定を入れたが, 戻り値・後続の列 (並びまで)・キャッチ抜きの数は #37 と同じ
(experiments/f1_select_catch が到達可能な全局面で確かめた). 全探索の待ち行列も, 後退解析が局面を決める順も
変わらないので, dat/ は #37 とバイト一致するはず.
そこで両腕とも, dat/ の md5 一覧の sha256 (results/*/bytecompare.txt と同じ作り方) が #37 本走の値と
同じかを見る. #37 本走の値は results/37_mirror1/bytecompare.txt の最後の行「md5 一覧の sha256 (全桁)」
(門番 #37 の new の7本とも同じ値だった).
オラクル174行は run_one.sh が見る.
最後の行に PASS / FAIL。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BYTECOMPARE = ROOT / "results" / "37_mirror1" / "bytecompare.txt"


def md5_list_sha(d: pathlib.Path) -> str:
    """find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ。"""
    names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
    lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
    return hashlib.sha256(lines.encode()).hexdigest()


def ref_sha() -> str:
    text = BYTECOMPARE.read_text(encoding="utf-8")
    m = re.search(r"^md5 一覧の sha256 \(全桁\): ([0-9a-f]{64})$", text, re.M)
    if not m:
        raise SystemExit(f"{BYTECOMPARE} に #37 の md5 一覧の sha256 が無い")
    return m.group(1)


def main(argv: list[str]) -> int:
    dat = pathlib.Path(argv[1])
    n = sum(1 for p in dat.iterdir() if p.is_file())
    got, want = md5_list_sha(dat), ref_sha()
    ok = got == want
    print(f"ファイル {n} 個. md5 一覧の sha256: {got[:12]} / #37 本走 {want[:12]} => "
          f"{'一致' if ok else '不一致'}")  # fmt: skip
    print("答えの検査: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
