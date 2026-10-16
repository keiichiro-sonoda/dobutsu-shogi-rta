#!/bin/bash
# 標本の帰属を確かめる (実験 perf_branch_34。記録試行ではない. 本物のデータは使わない)
#
#   probe/run_probe.sh      → logs/probe_attr.txt
#
# attr.c (乱数で転ぶ分岐を1つだけ持つループ) を perf record の下で回し, 標本の番地がどこに付くかを見る:
#   - br_misp_retired.all_branches_pebs を :up (precise 1) と :upp (precise 2) で
#   - br_inst_retired.all_branches_pebs を :upp で (同じ回数だけ実行される2つの分岐に, 標本が同じ割合で付くか)
#   - LBR (-j any,u) で, 外れの印と, 区間から組み立てた実行回数
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/perf_branch_34/probe"
OUT="$HERE/../logs/probe_attr.txt"
mkdir -p "$W"
gcc -O2 -g -Wall -Wextra "$HERE/attr.c" -o "$W/attr"
{
    echo "# 標本の帰属の確かめ ($(date --iso-8601=seconds))"
    perf --version
    echo "kernel.perf_event_paranoid = $(cat /proc/sys/kernel/perf_event_paranoid)"
    echo "cpu/caps/max_precise = $(cat /sys/bus/event_source/devices/cpu/caps/max_precise)"
    echo "cpu/caps/branches (LBR の深さ) = $(cat /sys/bus/event_source/devices/cpu/caps/branches)"
    echo "# attr の分岐のまわり (objdump)"
    objdump -d --no-show-raw-insn "$W/attr" | awk '/<work>:/,/ret/' | grep -E "test|j[a-z]+ |add|cmp|probe" \
        | sed -e 's/^ *//'
    for spec in "br_misp_retired.all_branches_pebs:up 10007" "br_misp_retired.all_branches_pebs:upp 10007" \
                "br_inst_retired.all_branches_pebs:upp 100003"; do
        read -r ev period <<< "$spec"
        echo
        echo "## perf record -e $ev -c $period"
        perf record -q -o "$W/p.data" -e "$ev" -c "$period" -- "$W/attr" > /dev/null 2> /dev/null
        perf script -i "$W/p.data" -F ip,sym,symoff 2> /dev/null > "$W/p.txt"
        python3 "$HERE/check_attr.py" "$W/attr" "$ev" "$W/p.txt"
    done
    echo
    echo "## perf record -j any,u -e cycles:u -c 100003 (LBR)"
    perf record -q -o "$W/l.data" -j any,u -e cycles:u -c 100003 -- "$W/attr" > /dev/null 2> /dev/null
    perf script -i "$W/l.data" -F brstacksym 2> /dev/null > "$W/l.txt"
    python3 "$HERE/check_attr.py" "$W/attr" lbr "$W/l.txt"
} > "$OUT"
cat "$OUT"
