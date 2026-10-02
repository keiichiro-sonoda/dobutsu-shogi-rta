#!/usr/bin/python3
"""2腕の .so で, 移動表4本がどう読まれているかを出す (門番 #29。記録試行ではない)。

    python3 experiments/gate_29_static_const_moves/tables.py <old の .so> <new の .so>

次の3つを並べる。

1. `readelf -rW` の再配置のうち, 移動表を指すもの (GOT 経由なら `R_X86_64_GLOB_DAT` に出る)
2. `nm` の移動表のシンボルの種類 (`D` / `d` は書き換えられるデータ, `r` は読み出し専用)
3. 生成器 `nextBoardInvNormal()` の中で移動表に触れる命令 (`objdump -d` の注釈で表の名前が出る行)。
   GOT から番地を読むなら `mov ...(%rip)` で注釈が `<名前@@Base...>`,
   直接なら `lea ...(%rip)` で `<名前>`

.so は門番の本が作ったもの (runs/exp_g29_<ラベル>/animal_shogi.so) を渡す。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

TABLES = ("GIRAFFE_MOVE", "ELEPHANT_MOVE", "LION_MOVE", "CHICKEN2_MOVE")


def run(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def report(arm: str, so: pathlib.Path) -> None:
    print(f"### `{arm}`（so sha256 {hashlib.sha256(so.read_bytes()).hexdigest()[:12]}）")
    print()
    relocs = [ln.split() for ln in run("readelf", "-rW", str(so)).splitlines()]
    hits = [f"`{r[2]}` {r[4]}" for r in relocs if len(r) >= 5 and r[4] in TABLES]
    print(f"- 再配置: {len(hits)} 本 {' / '.join(hits)}")
    kinds = {}
    for ln in run("nm", str(so)).splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[2] in TABLES:
            kinds[parts[2]] = parts[1]
    print("- nm の種類: " + " / ".join(f"`{t}` {kinds.get(t, '無い')}" for t in TABLES))
    out = run("objdump", "-d", "--no-show-raw-insn", str(so))
    start = out.index("<nextBoardInvNormal>:\n")
    body = out[start : out.index("\n\n", start)].splitlines()
    lines = [ln.strip() for ln in body if any(t in ln for t in TABLES)]
    insns = sum(1 for ln in body if re.match(r"^\s+[0-9a-f]+:\t", ln))
    print(f"- 生成器の命令の数: {insns}")
    print(f"- 生成器の中で移動表に触れる命令: {len(lines)} か所")
    for ln in lines:
        print(f"  - `{re.sub(r'\\s+', ' ', ln.split(':', 1)[1].strip())}`")
    print()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    report("old", pathlib.Path(argv[1]))
    report("new", pathlib.Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
