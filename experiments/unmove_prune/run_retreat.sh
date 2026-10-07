#!/bin/bash
# 試作の後退解析 (unmove_catch の drop) を, 素朴な版 (naive) と絞った版 (pruned) の逆向きの生成器で交互に3本ずつ回す
# (実験 unmove_prune。記録試行ではない). run_verify.sh のあとに回す
#
#   run_retreat.sh [dat/]
#
#   並び: naive pruned pruned naive naive pruned
#
# どの本も numactl でノード0に固定する. 1本ごとに, 終わったら全局面の (勝敗, 手数) を dat/ と比べる (bench retreat).
# 止める条件: 一致の検査が PASS で, A が2マス以上の盤が 0 でなければ回さない (gate.sh).
#             どちらかの版が dat/ と一致しなかったら, そこで止める (食い違いの内訳はその本のログに出る).
# 進行は logs/console_retreat.log, 本ごとの段の内訳は logs/retreat_<ラベル>.txt
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (CLAUDE.md「記録に残さないもの」)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
# shellcheck source-path=SCRIPTDIR source=gate.sh
source "$HERE/gate.sh"
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
W="$ROOT/runs/unmove_prune"
NUMA=(numactl --cpunodebind=0 --membind=0)
ORDER=(naive pruned pruned naive naive pruned)
if [ -e "$HERE/logs/console_retreat.log" ]; then
    echo "logs/console_retreat.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
check_verify "$HERE"
exec > >(tee "$HERE/logs/console_retreat.log") 2>&1
echo "=== unmove_prune 試作の後退解析 開始 $(date --iso-8601=seconds) ==="
echo "prune.so sha256 $(sha256sum "$W/build/prune.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "先読み: どちらの版も, 候補のランクで cls の行を, 残った前任で dtm (と cnt) の行を取り寄せる (unmove_catch と同じ)"
echo "THP enabled: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
FB0=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
freq_header > "$HERE/logs/retreat_freq.log"
sample_hw >> "$HERE/logs/retreat_freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
i=0
for v in "${ORDER[@]}"; do
    i=$((i + 1))
    label="a${i}_$v"
    echo "--- $label 開始 $(date --iso-8601=seconds) ---"
    set +e
    "${NUMA[@]}" "$W/build/bench" retreat "$W/build/prune.so" "$DAT" "$W" "$v" "$label" > "$HERE/logs/retreat_$label.txt" 2>&1
    RC=$?
    set -e
    grep -E '^(初期化|一致の検査|RESULT|食い違いの内訳)' "$HERE/logs/retreat_$label.txt" || true
    if [ "$RC" -ne 0 ]; then
        echo "!!! $label が一致しなかった (または落ちた. exit=$RC). ここで止める"
        exit 1
    fi
done
FB1=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
echo "thp_fault_fallback の前後差: $((FB1 - FB0))"
echo "=== unmove_prune 試作の後退解析 全6本 完了 $(date --iso-8601=seconds) ==="
