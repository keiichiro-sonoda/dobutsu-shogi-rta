#!/bin/bash
# 完走を1本回して答えを確かめる (実験 unmove_gen。記録試行ではない. 計時には使わない)
#
#   run_full.sh <mirror1|bb_unmove>
#
# impl/35_bitboard の写しに腕のパッチを当てたもの (build_arm.sh) を, 作業用の場所 runs/unmove_gen/full_<腕>/ で
# 空の dat/ から走らせる (tools/run.sh・門番の run_one.sh と同じく, 作業ディレクトリへ cd して python3 ./animal_shogi.py).
# 一致の検査のあとに回すので, 一致の検査が通った腕だけを渡す (run_all.sh が見る).
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見て logs/full_<腕>_hugefree.txt に残す.
# 足りなければ走らずに止める (exit 4. キャッシュは本人が落とす). 走ったあと:
#   - 解析の終了コード, オラクル174行 (tools/verify_log.py)
#   - 答え (check_full.py): bb_unmove は dat/ の md5 一覧の sha256 が #35 本走と同じ.
#     mirror1 は 指紋・全探索の側のバイト一致・ファイルの名前と件数・手数ごとに束ねた集合の一致
# 外れたら dat/ を残して止める (exit 1). 通ったら dat/ を消す
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (mirror1|bb_unmove)}"
case "$ARM" in mirror1 | bb_unmove) ;; *) echo "知らない腕: $ARM" >&2; exit 2 ;; esac
LABEL="full_$ARM"
W="$ROOT/runs/unmove_gen/$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB=16
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 10000000 ]; then
    echo "空きが 10 GB 未満 ($AVAIL_KB KB)" >&2
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
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W")
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"
set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 調査用に dat/ を残して止める" >&2
    exit 1
fi
cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"
# time.txt の1行目は計時したコマンド行 (作業ディレクトリの絶対パスは入らないが, 念のため場所を伏せる)
sed -e "s|$ROOT|<repo>|g" "$W/time.txt" > "$HERE/logs/${LABEL}_time.txt"
echo "--- オラクル 174行 ---"
set +e
python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt" 2>&1 | sed -e "s|$ROOT|<repo>|g" \
    > "$HERE/logs/${LABEL}_oracle.txt"
RC=${PIPESTATUS[0]}
set -e
if [ "$RC" -ne 0 ]; then
    tail -3 "$HERE/logs/${LABEL}_oracle.txt"
    echo "!!! オラクル検証 FAIL (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
grep -E 'PASS|FAIL' "$HERE/logs/${LABEL}_oracle.txt"
echo "--- 答え ($ARM) ---"
set +e
# 失敗したときの出力にはパスが入りうるので, リポジトリの場所を伏せて残す
python3 "$HERE/check_full.py" "$ARM" "$W/dat" 2>&1 | sed -e "s|$ROOT|<repo>|g" > "$HERE/logs/${LABEL}_answer.txt"
RC=${PIPESTATUS[0]}
set -e
cat "$HERE/logs/${LABEL}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
