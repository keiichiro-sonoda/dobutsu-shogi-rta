#!/bin/bash
# 門番 #29: 空の dat/ から完走を1本 (記録試行ではない)
#
#   run_one.sh <old|new> <ラベル>
#
# 単位は完走. 変えたのは gcc 行のフラグ1つだけ (C も Python も同じ). 全探索と後退解析の全段を同じ本で見る.
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 16) 以上あるかを見る
# (門番は numactl でノード0に固定するので, ノード0だけで見る). 足りなければ走らずに止める.
# キャッシュを落とすのは人が別に行い, 門番を最初から回し直す (run_all.sh がこの本以降を回さない).
#
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - オラクル174行 (tools/verify_log.py)
#   - dat/ の md5 一覧の sha256 が results/28_march_native/bytecompare.txt の #28 の値と一致する
#   - forward.tsv の件数の列が results/28_march_native/forward.tsv と一致する (stop_rule.py rounds)
#   - /proc/vmstat の thp_fault_fallback の前後差が 0
#   - 巨大ページが発見済み表・索引・後退解析の配列の全部に付いている (両腕とも. stop_rule.py huge)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (old|new)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/exp_g29_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
BC="$HERE/logs/bytecompare.tsv"
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-16}"
# 基準は #28 本走の dat/ (#19〜#26 と同じ値). 手で写さず, 記録の証拠から読む
REF=$(grep -oE '#28 [0-9a-f]{64}' "$ROOT/results/28_march_native/bytecompare.txt" | cut -d' ' -f2)
[ -n "$REF" ] || { echo "results/28_march_native/bytecompare.txt から基準の値が読めない" >&2; exit 2; }

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 10000000 ]; then
    echo "空きが 10 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

mkdir -p "$HERE/logs"
FREE0=$(hugefree_gib 0)
{
    echo "# 走る前のノード0の /proc/buddyinfo. 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB GiB)"
    grep '^Node 0' /proc/buddyinfo 2>/dev/null || true
} > "$HERE/logs/${LABEL}_hugefree.txt"
echo "--- $LABEL の前のノード0: 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB) ---"
if ! awk -v have="$FREE0" -v need="$HUGEFREE_MIN_GIB" \
        'BEGIN { exit !(have != "-" && have + 0 >= need + 0) }'; then
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める" >&2
    echo "    root でキャッシュを落とし (drop_caches と compact_memory), 門番を最初から回し直す" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W")
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 再開せず, 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
# gate_stats.py の forward モードが「全探索 合計」として読む行 (要約ファイルの生値)
FT=$(awk -F'\t' '$1 == "forward_total" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
echo "全探索の所要時間：$FT 秒"
grep -E "^F1\s" "$W/kaiseki_log/forward_summary.tsv" | tr '\n' ' ' || true
grep -E "^(P2|P4|loop174)\s" "$W/kaiseki_log/retreat_summary.tsv" | tr '\n' ' ' || true
echo

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/kaiseki_log7.txt" "$HERE/logs/${LABEL}_sub.log"
cp "$W/kaiseki_log/forward.tsv" "$HERE/logs/${LABEL}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

FB=$(awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "thp_fault_fallback") c = i}
                 NR == 2 {b = $c} NR == 3 {print $c - b}' "$W/vmstat.tsv")
echo "--- thp_fault_fallback の前後差: $FB ---"
if [ "$FB" != "0" ]; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件③). 調査用に dat/ を残して止める" >&2
    exit 1
fi

echo "--- 巨大ページ (発見済み表・索引・後退解析の配列) ---"
if ! python3 "$HERE/stop_rule.py" huge "$LABEL"; then
    echo "!!! 巨大ページが表と配列の全部に付いていない (止める条件③). 調査用に dat/ を残して止める" >&2
    exit 1
fi

echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件①). 調査用に dat/ を残して止める" >&2
    exit 1
fi

SHA=$(md5_list_sha "$W/dat")
FILES=$(find "$W/dat" -type f | wc -l)
BYTES=$(find "$W/dat" -type f -printf '%s\n' | awk '{s+=$1} END {print s}')
if [ "$SHA" = "$REF" ]; then VS="一致"; else VS="不一致"; fi
[ -s "$BC" ] || printf 'label\tarm\tfiles\tbytes\tmd5_list_sha256\tvs_record28\n' > "$BC"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$LABEL" "$ARM" "$FILES" "$BYTES" "$SHA" "$VS" >> "$BC"
echo "--- dat/ のバイト比較 (#28 本走と): $FILES ファイル / $BYTES バイト / $VS ---"
if [ "$VS" = "不一致" ]; then
    echo "!!! $ARM の出力が #28 本走と違う (止める条件①). 調査用に dat/ を残して止める" >&2
    exit 1
fi

echo "--- 件数の列を #28 本走と照合 ---"
if ! python3 "$HERE/stop_rule.py" rounds "$HERE/logs/${LABEL}_forward.tsv"; then
    echo "!!! 件数の列が #28 と違う (止める条件①). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
