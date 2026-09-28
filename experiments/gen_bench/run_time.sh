#!/bin/bash
# 生成器の計時 (実験 gen_bench。記録試行ではない). run_verify.sh のあとに回す
#
#   run_time.sh
#
# 4つの版を1本ずつ別のプロセスで測る (.so は1つだけ開く. 本番の CDLL と同じ RTLD_LOCAL).
# 7周まわし, 周ごとに版の順番を1つずつずらす (どの版も7周で先頭から4番目までを回る).
# どの本も numactl でノード0に固定する. 版ごとに catch / try / unknown / mixed を1周温めてから1周測る.
# invBoard 単体は base と B だけ (mixed で測る).
# logs/verify.txt で exit=0 でなかった版は測らない (止める条件).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (CLAUDE.md「記録に残さないもの」)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
W="$ROOT/runs/gen_bench"
ROUNDS=7
VARIANTS=(base B A AB)
declare -A SYMBOL=([base]=nextBoardInvNormal [B]=nextBoardInvNormal [A]=nextBoardCatchFirst [AB]=nextBoardCatchFirst)
NUMA=(numactl --cpunodebind=0 --membind=0)
if [ -e "$HERE/logs/timing.tsv" ]; then
    echo "logs/timing.tsv が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
declare -A OK
for v in "${VARIANTS[@]}"; do
    case "$v" in
        base) OK[$v]=1 ;;
        B)    grep -qx 'exit=0 B invBoard' "$HERE/logs/verify.txt" && grep -qx 'exit=0 B' "$HERE/logs/verify.txt" && OK[$v]=1 || OK[$v]=0 ;;
        *)    grep -qx "exit=0 $v" "$HERE/logs/verify.txt" && OK[$v]=1 || OK[$v]=0 ;;
    esac
    [ "${OK[$v]}" = 1 ] || echo "!!! $v は一致の検査を通っていないので測らない"
done
echo "=== gen_bench 計時 開始 $(date --iso-8601=seconds) ==="
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
freq_header > "$HERE/logs/freq.log"
sample_hw >> "$HERE/logs/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
printf 'label\twhat\tsymbol\tkind\tn\tns_total\tns_per\n' > "$HERE/logs/timing.tsv"
for r in $(seq 1 "$ROUNDS"); do
    for i in 0 1 2 3; do
        v="${VARIANTS[$(( (i + r - 1) % 4 ))]}"
        [ "${OK[$v]}" = 1 ] || continue
        echo "--- r${r} $v ($(date +%H:%M:%S)) ---"
        so="$W/so/$v/animal_shogi.so"
        "${NUMA[@]}" "$W/bench" time-gen "$so" "${SYMBOL[$v]}" "$W/sample" "r${r}_$v" | tee -a "$HERE/logs/timing.tsv"
        if [ "$v" = base ] || [ "$v" = B ]; then
            "${NUMA[@]}" "$W/bench" time-inv "$so" "$W/sample" "r${r}_$v" | tee -a "$HERE/logs/timing.tsv"
        fi
    done
done
echo "=== gen_bench 計時 完了 $(date --iso-8601=seconds) ==="
