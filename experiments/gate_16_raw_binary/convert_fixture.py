#!/usr/bin/env python3
"""門番のフィクスチャを、**採番順を保ったまま** pickle から生バイナリへ写す。

    python3 convert_fixture.py <pickle の dat/> <出力する dat/>

⚠️ ここが門番の要。`tools/rebuild_forward_fixture.py` は使えない。あちらは
書き出しに `array("Q", set(boards))` を通すので、集合を作り直して順序が動く。

記録 #15 が `pickle.load(f)` で読むと、**保存されている順ではなく「読み直した
集合の反復順」**が出てくる (pickle の往復は set の反復順を保たない。1,000,000 件で
99.9% の位置が動くことを実測した)。記録 #16 は `frombytes` でファイルの順を
そのまま読む。

だからここでは `array("Q", pickle.load(f))` をそのまま書く。こうすると
**#16 がファイルから読む順 = #15 が pickle から読む順**になり、両腕の採番順が
一致する。形式だけを1変数にできる。

一致したことは走ったあとに確かめられる。ただし **`array("Q", pickle.load(f))` を
「#15 が書いた順」として #16 の出力と比べてはいけない**。`pickle.load()` は順序を
崩すので、採番順が同じでも食い違って見える（CLAUDE.md の「pickle が書いた順を
知りたいときは `pickletools.genops` でストリームから取る」を見ること。記録 #16 の
門番でこの取り違えを実際に踏んだ）。書かれた順はストリームから直に取り、
#16 の `.bin` と比べる。
"""

from __future__ import annotations

import pathlib
import pickle
import sys
from array import array


def convert(src: pathlib.Path, dst: pathlib.Path) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    if any(dst.iterdir()):
        raise SystemExit(f"{dst} が空でない")
    n = 0
    for path in sorted(src.iterdir()):
        if path.suffix != ".pickle":
            continue
        with path.open("rb") as f:
            boards = pickle.load(f)
        (dst / (path.stem + ".bin")).write_bytes(array("Q", boards).tobytes())
        n += 1
    return n


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    n = convert(pathlib.Path(argv[1]), pathlib.Path(argv[2]))
    print(f"{n} ファイルを写した (採番順は保っている)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
