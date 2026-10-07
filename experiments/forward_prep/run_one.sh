#!/bin/bash
# 全探索だけを空の dat/ から1本 (実験 forward_prep。記録試行ではない)
#
#   run_one.sh <腕> <ラベル> <time|verify>     腕は old / recalc / carry / carry_check (build_arm.sh)
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 8) 以上あるかを見て logs/<ラベル>_hugefree.txt に残す.
# 足りなければ走らずに止める (exit 4). キャッシュを落とすかは本人が決める.
# numactl でノード0に固定し, driver.py で searchAll() だけを走らせる (後退解析は走らせない).
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - /proc/vmstat の thp_fault_fallback の前後差が 0
#   - 全探索の側の dat/ (win001te_* と lose000te_*) が, #33 本走の dat/ の同じ名前のファイルとバイト一致
#   - forward.tsv の件数の列 (round〜n_try_total) が results/33_hot_layout/forward.tsv と一致
#   - 全探索が後退解析に渡す3本の列の sha256 (並びまで含む) が, logs/out_ref.txt (一致の検査の old の本が書いた値) と一致
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること}"
LABEL="${2:?ラベルを指定すること}"
MODE="${3:?time か verify を指定すること}"
W="$ROOT/runs/forward_prep/$LABEL"
REFDAT="$ROOT/runs/20261004-091929_33_hot_layout/dat"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-8}"

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
[ -d "$REFDAT" ] || { echo "#33 本走の dat/ が無い: $REFDAT" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
FREE0=$(hugefree_gib 0)
{
    echo "# 走る前 ($(date --iso-8601=seconds)) のノード0の /proc/buddyinfo. 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB GiB)"
    grep '^Node 0' /proc/buddyinfo 2>/dev/null || true
} > "$HERE/logs/${LABEL}_hugefree.txt"
echo "--- $LABEL の前のノード0: 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB) ---"
if ! awk -v have="$FREE0" -v need="$HUGEFREE_MIN_GIB" 'BEGIN { exit !(have != "-" && have + 0 >= need + 0) }'; then
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める (本人に知らせる)" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W" 2>/dev/null | tail -1)
cp "$HERE/driver.py" "$W/"
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"
set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./driver.py "$MODE" > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true
echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 全探索が落ちた (exit=$RC). 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
FT=$(awk -F'\t' '$1 == "forward_total" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
echo "全探索の所要時間：$FT 秒"
grep -E "^F1\s" "$W/kaiseki_log/forward_summary.tsv" | tr '\n' ' ' || true
echo
for f in forward.tsv forward_summary.tsv; do cp "$W/kaiseki_log/$f" "$HERE/logs/${LABEL}_$f"; done
cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/stdout.txt" "$HERE/logs/${LABEL}_stdout.txt"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

FB=$(awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "thp_fault_fallback") c = i}
                 NR == 2 {b = $c} NR == 3 {print $c - b}' "$W/vmstat.tsv")
echo "--- thp_fault_fallback の前後差: $FB ---"
if [ "$FB" != "0" ]; then
    echo "!!! 巨大ページが頼んだぶん付かなかった. 調査用に dat/ を残して止める" >&2
    exit 1
fi
NF=0
NBAD=0
for f in "$W"/dat/*; do
    NF=$((NF + 1))
    b=$(basename "$f")
    if ! cmp -s "$f" "$REFDAT/$b"; then
        NBAD=$((NBAD + 1))
        echo "    バイト一致しない: $b"
    fi
done
echo "--- 全探索の側の dat/: $NF ファイル, #33 本走の dat/ の同じ名前のファイルと違うもの $NBAD ---"
if [ "$NF" -eq 0 ] || [ "$NBAD" -ne 0 ]; then
    echo "!!! 全探索の側の dat/ が #33 と違う (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
if ! cmp -s <(cut -f1-12 "$HERE/logs/${LABEL}_forward.tsv") <(cut -f1-12 "$ROOT/results/33_hot_layout/forward.tsv"); then
    echo "!!! forward.tsv の件数の列が #33 と違う (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- forward.tsv の件数の列 (round〜n_try_total): #33 と一致 ---"
grep '^出力の指紋 ' "$W/stdout.txt" > "$W/out_sha.txt"
if [ ! -e "$HERE/logs/out_ref.txt" ]; then
    if [ "$ARM" != "old" ] || [ "$MODE" != "verify" ]; then
        echo "!!! logs/out_ref.txt が無い (一致の検査の old の本が先に書く)" >&2
        exit 2
    fi
    cp "$W/out_sha.txt" "$HERE/logs/out_ref.txt"
    echo "--- 3本の列の sha256 を logs/out_ref.txt に書いた (基準) ---"
elif ! cmp -s "$W/out_sha.txt" "$HERE/logs/out_ref.txt"; then
    echo "!!! 全探索が後退解析に渡す列が old と違う (止める条件). 調査用に dat/ を残して止める" >&2
    diff "$W/out_sha.txt" "$HERE/logs/out_ref.txt" || true
    exit 1
else
    echo "--- 3本の列の sha256 (並びまで): old と一致 ---"
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
