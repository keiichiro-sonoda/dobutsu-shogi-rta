#!/bin/bash
# 空の dat/ から完走を1本回し, そのあいだの 2 MiB 以上の空きを 0.2 秒おきに読む (実験 hugefree_need。記録試行ではない)
#
#   run_one.sh <pin|free> <ラベル> <何本目か>
#
#   pin   門番と同じ numactl --cpunodebind=0 --membind=0
#   free  本走と同じく固定しない
#
# 実装は impl/37 以降の門番と同じく, impl/38_precheck を runs/ の下に写してその Makefile でビルドする (impl/ は触らない).
# 走る前に, 2 MiB 以上の空きブロック (/proc/buddyinfo の order 9 以上) を両ノードで読み, logs/<ラベル>_before.txt に残す.
# 今の基準 HUGEFREE_MIN_GIB (既定 16) と比べる量は, pin はノード0, free は両ノードの合計 (門番の run_one.sh と tools/run.sh と同じ).
# 1本目が足りなければ走らせずに止める (exit 4. キャッシュは本人が落とす). 2本目からは, この実験では本を重ねたときの
# 減り方と持ち越しを見たいので, 足りなくても止めずに「今の基準なら止まっていた」と残して走らせる.
# 走っているあいだは sampler.py が 0.2 秒おきに両ノードの空きと, Python のプロセスの AnonHugePages・Rss を
# logs/<ラベル>_samples.tsv に書く. 走り終わった直後と, dat/ を消したあとの空きも logs/<ラベル>_after.txt に残す.
# 毎本その場で見て, 掛かったら dat/ を残して止める (止める条件 1・2):
#   - オラクル174行 (tools/verify_log.py)
#   - dat/ の md5 一覧の sha256 が #38 本走と同じ (check_answer.py)
#   - /proc/vmstat の thp_fault_fallback の前後差が 0
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
MODE="${1:?pin か free を指定すること}"
LABEL="${2:?ラベルを指定すること}"
NTH="${3:?何本目かを指定すること}"
SRC="$ROOT/impl/38_precheck"
W="$ROOT/runs/hugefree_need/$LABEL"
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-16}"
case "$MODE" in
    pin) PRE=(numactl --cpunodebind=0 --membind=0); WHICH=0 ;;
    free) PRE=(); WHICH=all ;;
    *) echo "pin か free: $MODE" >&2; exit 2 ;;
esac
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
mkdir -p "$HERE/logs" "$W"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$W/" \;
(cd "$W" && make --quiet animal_shogi.so)
mkdir -p "$W/dat" "$W/kaiseki_log"

snapshot() {  # snapshot <見出し>
    echo "# $1 ($(date --iso-8601=seconds)). 2 MiB 以上の空きブロック: node0 $(hugefree_gib 0) / node1 $(hugefree_gib 1) / 合計 $(hugefree_gib all) GiB"
    grep '^Node' /proc/buddyinfo 2>/dev/null || true
}
HAVE=$(hugefree_gib "$WHICH")
{
    snapshot "走る前 ($LABEL, $MODE, $NTH 本目. 今の基準と比べる量は $([ "$WHICH" = 0 ] && echo ノード0 || echo 両ノードの合計) $HAVE GiB, 基準 $HUGEFREE_MIN_GIB GiB)"
} > "$HERE/logs/${LABEL}_before.txt"
echo "--- $LABEL ($MODE) の前: $(sed -n 1p "$HERE/logs/${LABEL}_before.txt" | sed 's/^# //') ---"
if ! awk -v have="$HAVE" -v need="$HUGEFREE_MIN_GIB" 'BEGIN { exit !(have != "-" && have + 0 >= need + 0) }'; then
    if [ "$NTH" = 1 ]; then
        echo "!!! 1本目の前の空きが基準に満たない. 走らせずに止める (本人に知らせる. 止める条件 4)" >&2
        rm -rf "$W"
        exit 4
    fi
    echo "※ 今の基準 ($HUGEFREE_MIN_GIB GiB) なら止まっていた. この実験では止めずに走らせる"
fi

echo "=== 開始 $LABEL ($MODE: impl/38_precheck (so sha256 $(sha256sum "$W/animal_shogi.so" | cut -c1-12))) $(date --iso-8601=seconds) ==="
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"
set +e
(cd "$W" && exec /usr/bin/time -v "${PRE[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt) &
RUN=$!
python3 "$HERE/sampler.py" "$RUN" "$HERE/logs/${LABEL}_samples.tsv" 0.2 &
SAMP=$!
wait "$RUN"
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
wait "$SAMP" || true
snapshot "走り終わった直後 ($LABEL)" > "$HERE/logs/${LABEL}_after.txt"
echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

FB=$(awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "thp_fault_fallback") c = i}
                 NR == 2 {b = $c} NR == 3 {print $c - b}' "$W/vmstat.tsv")
echo "--- thp_fault_fallback の前後差: $FB ---"
if [ "$FB" != "0" ]; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件 2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ---"
set +e
python3 "$HERE/check_answer.py" "$W/dat" > "$HERE/logs/${LABEL}_answer.txt" 2>&1
RC=$?
set -e
cat "$HERE/logs/${LABEL}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
snapshot "dat/ を消したあと ($LABEL)" >> "$HERE/logs/${LABEL}_after.txt"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
