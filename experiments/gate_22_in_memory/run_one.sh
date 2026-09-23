#!/bin/bash
# 門番 #22: 空の dat/ から完走を1本 (記録試行ではない)
#
#   run_one.sh <old|chunk|whole> <ラベル>
#
# 単位は完走. #22 から後退解析はファイルを読まない (全探索がメモリに残したものを P0 が詰める)
# ので, 全探索の出力 (runs/g19_fixture_bin/dat) から後退解析だけを回す門番では
# P0 の受け渡しを通せない. 完走でも1本3分半ほど.
#
# 答えの検査は2つ.
#   - オラクル174行 (tools/verify_log.py)
#   - dat/ の md5 一覧の sha256 が, 記録 #21 本走の dat/ の値 (results/21_hugepages/bytecompare.txt。
#     #19・#20 と同じ値) と一致すること. 一致しなければ dat/ を残して止める (止める条件①)
# chunk は, その場で forward.tsv の件数の列を #21 本走と照合する (止める条件②).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (old|chunk|whole)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/exp_g22_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
BC="$HERE/logs/bytecompare.tsv"
REF_21="f18f3075ba25f13987c520fe98cba074a5916c08ead02eb4719af2a87141b488"

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

mkdir -p "$W/dat" "$W/kaiseki_log" "$HERE/logs"
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
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi
# gate_stats.py の forward モードが「全探索 合計」として読む行 (要約ファイルの生値)
FT=$(awk -F'\t' '$1 == "forward_total" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
echo "全探索の所要時間：$FT 秒"
grep -E "^(rounds|F0|F1|F2|F5|F6)\s" "$W/kaiseki_log/forward_summary.tsv" | tr '\n' ' ' || true
grep -E "^(P0|P1|P2|loop174|retreat_total)\s" "$W/kaiseki_log/retreat_summary.tsv" \
    | tr '\n' ' ' || true
echo

echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

SHA=$(md5_list_sha "$W/dat")
FILES=$(find "$W/dat" -type f | wc -l)
BYTES=$(find "$W/dat" -type f -printf '%s\n' | awk '{s+=$1} END {print s}')
if [ "$SHA" = "$REF_21" ]; then VS="一致"; else VS="不一致"; fi
[ -s "$BC" ] || printf 'label\tarm\tfiles\tbytes\tmd5_list_sha256\tvs_record21\n' > "$BC"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$LABEL" "$ARM" "$FILES" "$BYTES" "$SHA" "$VS" >> "$BC"
echo "--- dat/ のバイト比較 (#21 本走と): $FILES ファイル / $BYTES バイト / $VS ---"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/kaiseki_log7.txt" "$HERE/logs/${LABEL}_sub.log"
cp "$W/kaiseki_log/forward.tsv" "$HERE/logs/${LABEL}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

if [ "$VS" = "不一致" ]; then
    echo "!!! $ARM の出力が #21 本走と違う. 調査用に dat/ を残して止める" >&2
    exit 1
fi
if [ "$ARM" = chunk ]; then
    echo "--- chunk の件数の列を #21 本走と照合 ---"
    if ! python3 "$HERE/stop_rule.py" rounds "$HERE/logs/${LABEL}_forward.tsv"; then
        echo "!!! chunk のラウンドの分け方が #21 と違う. 調査用に dat/ を残して止める" >&2
        exit 1
    fi
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
