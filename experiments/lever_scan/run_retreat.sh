#!/bin/bash
# 後退解析の門番 (実験 lever_scan。記録試行ではない)
#
#   run_retreat.sh <腕> <ラベル>
#
# runs/g19_fixture_bin/dat から retreatAnalysis() だけを走らせる
# (gate_19_c_gather/run.sh と同じ形).
#
# ⚠️ 入力は tools/rebuild_forward_fixture.py で組み直したものではない.
#    あれは未知の集合を深さ順に詰め直すので, 集合は戻るが並び (採番順) は戻らない.
#    ここで使うのは全探索の門番の base 1本目が書いた dat/ そのもので,
#    本走の searchAll() が書いて retreatAnalysis() が読むのと同じバイト列になる.
#
# ⚠️ 出力の dat/ は, 記録 #19 本走の dat/ とバイト一致するはず
#    (md5 一覧の sha256 は results/19_c_gather/bytecompare.txt の値).
#    全腕をこの値と比べる. base が外れたら入力が違うので, そこで止める
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること}"
LABEL="${2:?ラベルを指定すること}"
FIX="$ROOT/runs/g19_fixture_bin/dat"
W="$ROOT/runs/exp_lsr_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
BC="$HERE/logs/bytecompare_retreat.tsv"
REF_19="f18f3075ba25f13987c520fe98cba074a5916c08ead02eb4719af2a87141b488"

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
if [ "$(find "$FIX" -maxdepth 1 -name "*.bin" 2>/dev/null | wc -l)" -ne 51 ]; then
    echo "入力が無いか完成していない (51 ファイルでない): ${FIX#"$ROOT"/}" >&2
    echo "  run_all_forward.sh が全探索の base 1本目から作る" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi

mkdir -p "$W/kaiseki_log"
cp -r "$FIX" "$W/dat"
BUILD=$("$HERE/make_arm.sh" "$ARM" "$W")
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

cat > "$W/driver.py" <<PY
import importlib.util
import time

spec = importlib.util.spec_from_file_location("gatemod", "animal_shogi.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
$HUGE_HOOK
_wrap("indexFree")
t = time.perf_counter()
mod.retreatAnalysis()
print("後退解析の所要時間：%.2f 秒" % (time.perf_counter() - t))
PY

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
cat "$W/huge.txt" 2>/dev/null || true
grep -E "^(P0|P1|P2|P4|P4_count|P4_scatter|loop174)\s" "$W/kaiseki_log/retreat_summary.tsv" 2>/dev/null \
    | tr '\n' ' ' || true
echo
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 174行 ---"
# ⚠️ 止める条件はこれ. 速度では止めない
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

SHA=$(md5_list_sha "$W/dat")
FILES=$(find "$W/dat" -type f | wc -l)
BYTES=$(find "$W/dat" -type f -printf '%s\n' | awk '{s+=$1} END {print s}')
if [ "$SHA" = "$REF_19" ]; then VS="一致"; else VS="不一致"; fi
[ -s "$BC" ] || printf 'label\tarm\tfiles\tbytes\tmd5_list_sha256\tvs_record19\n' > "$BC"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$LABEL" "$ARM" "$FILES" "$BYTES" "$SHA" "$VS" >> "$BC"
echo "--- dat/ のバイト比較 (#19 本走と): $FILES ファイル / $BYTES バイト / $VS ---"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"
cp "$W/huge.txt" "$HERE/logs/${LABEL}_huge.txt"

if [ "$VS" = "不一致" ]; then
    if [ "$ARM" = "base" ]; then
        echo "!!! base の出力が #19 本走と違う. 入力が本走と同じ並びでない. 調査用に dat/ を残して止める" >&2
        exit 1
    fi
    echo "!!! $ARM は失格 (#19 本走と dat/ が違う). 調査用に dat/ を残す" >&2
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
