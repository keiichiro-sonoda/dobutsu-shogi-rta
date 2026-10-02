#!/usr/bin/python3
"""2腕の .so で, 関数ごとの call の行き先を数える (門番 #29。記録試行ではない)。

    python3 experiments/gate_29_static_const_moves/calls.py <old の .so> <new の .so>

`objdump -d` の `call` 命令を, 呼んでいる関数ごとに行き先で数える。行き先が `名前@plt` なら
PLT を経由する呼び出し, `名前` だけなら同じ .so の中への直接の呼び出し。
-fno-semantic-interposition は, 同じ .so の中の関数が実行時に差し替えられうるという前提を外す。
効いていれば, `名前@plt` のうち .so の中で定義した関数への呼び出しが直接の呼び出しになるか,
インライン展開されて消える。

表には, 2腕で数が違う (呼び出し元, 行き先) の組だけを出す。libc への呼び出し
(`free@plt` など) は両腕とも PLT のままなので, 数が変わらない限り出ない。
.so は門番の本が作ったもの (runs/exp_g29_<ラベル>/animal_shogi.so) を渡す。
"""

from __future__ import annotations

import collections
import hashlib
import pathlib
import re
import subprocess
import sys

HEAD = re.compile(r"^[0-9a-f]+ <(\S+)>:$")
# 呼び出しの前後の雑務 (crt の関数) は数えない
SKIP = ("_init", "_fini", "deregister_tm_clones", "register_tm_clones", "__do_global_dtors_aux")


def calls(so: pathlib.Path) -> collections.Counter[tuple[str, str]]:
    out = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", str(so)], capture_output=True, text=True, check=True
    ).stdout
    count: collections.Counter[tuple[str, str]] = collections.Counter()
    fn = ""
    for line in out.splitlines():
        if m := HEAD.match(line):
            fn = m.group(1)
        elif "\tcall" in line and fn not in SKIP:
            count[(fn, line.split()[-1].strip("<>"))] += 1
    return count


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    old_so, new_so = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    for arm, so in (("old", old_so), ("new", new_so)):
        print(f"- `{arm}`: so sha256 {hashlib.sha256(so.read_bytes()).hexdigest()[:12]}")
    old, new = calls(old_so), calls(new_so)
    print()
    print("| 呼び出し元 | 行き先 | `old` | `new` |")
    print("|---|---|---|---|")
    for caller, callee in sorted(set(old) | set(new)):
        a, b = old[(caller, callee)], new[(caller, callee)]
        if a != b:
            print(f"| `{caller}` | `{callee}` | {a} | {b} |")
    print()
    for arm, table in (("old", old), ("new", new)):
        plt = sum(n for (_, callee), n in table.items() if callee.endswith("@plt"))
        direct = sum(n for (_, callee), n in table.items() if not callee.endswith("@plt"))
        normal = sum(n for (_, callee), n in table.items() if callee.startswith("normalBoard"))
        print(f"- `{arm}`: PLT 経由 {plt} / 直接 {direct} / normalBoard への call {normal}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
