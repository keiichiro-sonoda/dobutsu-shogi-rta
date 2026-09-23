#!/bin/bash
# 門番 #21 (全探索側): 空の dat/ から searchAll() だけを走らせる (記録試行ではない)
#
#   run_forward.sh <old|new> <ラベル> [keep]
#
# experiments/gate_20_prefetch/run_forward.sh の写し. 巨大ページの証拠 (AnonHugePages) は
# 実装が forward_summary.tsv に書くので, 門番の driver は何もしない.
#
# ⚠️ 手数別174行は後退解析の出力なので, ここでは出ない. 答えは
#    「未知 + キャッチ + トライ負け = oracle/totals.tsv の reachable_total」と,
#    dat/ が後退解析の門番の入力 (runs/g19_fixture_bin/dat) とバイト一致することで見る.
#    入力は impl/19 の全探索の出力そのものなので, 巨大ページが書く値を変えなければ旧新とも一致する
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (old|new)}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"
W="$ROOT/runs/exp_g21f_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
BC="$HERE/logs/bytecompare_forward.tsv"
REF_FILE="$HERE/logs/ref_forward_sha256.txt"

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 8000000 ]; then
    echo "空きが 8 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W")
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

cat > "$W/driver.py" <<'PY'
import importlib.util
import time

spec = importlib.util.spec_from_file_location("gatemod", "animal_shogi.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.perf_counter()
mod.searchAll()
print("全探索の所要時間：%.2f 秒" % (time.perf_counter() - t))
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
if [ "$RC" -ne 0 ]; then
    echo "!!! 全探索が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 到達可能な全局面数 ---"
if ! python3 - "$ROOT" "$W/kaiseki_log/kaizenkaiseki1.txt" <<'PY'
import re
import sys

root, log = sys.argv[1], sys.argv[2]
want = None
for line in open(root + "/oracle/totals.tsv", encoding="utf-8"):
    if line.startswith("reachable_total\t"):
        want = int(line.split("\t")[1])
text = open(log, encoding="utf-8").read()
m = re.search(r"^総未知盤面数：(\d+), 総勝ち盤面数：(\d+), 総負け盤面数：(\d+)$", text, re.MULTILINE)
if want is None or not m:
    print("FAIL: reachable_total か総数の行が無い")
    raise SystemExit(1)
got = sum(int(g) for g in m.groups())
print("  合計 %d / oracle/totals.tsv の reachable_total %d" % (got, want))
if got != want:
    print("FAIL: 到達可能な全局面数が合わない")
    raise SystemExit(1)
print("PASS: 到達可能な全局面数が一致")
PY
then
    echo "!!! 検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# dat/ のバイト比較. 基準は後退解析の門番の入力 (run_all_forward.sh が最初に sha256 を取る)
SHA=$(md5_list_sha "$W/dat")
FILES=$(find "$W/dat" -type f | wc -l)
BYTES=$(find "$W/dat" -type f -printf '%s\n' | awk '{s+=$1} END {print s}')
REF=$(cat "$REF_FILE" 2>/dev/null || true)
if [ -z "$REF" ]; then VS="基準なし"; elif [ "$SHA" = "$REF" ]; then VS="一致"; else VS="不一致"; fi
[ -s "$BC" ] || printf 'label\tarm\tfiles\tbytes\tmd5_list_sha256\tvs_fixture\n' > "$BC"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$LABEL" "$ARM" "$FILES" "$BYTES" "$SHA" "$VS" >> "$BC"
echo "--- dat/ のバイト比較 (入力と): $FILES ファイル / $BYTES バイト / $VS ---"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/forward.tsv" "$HERE/logs/${LABEL}_forward.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

if [ "$VS" = "不一致" ]; then
    echo "!!! $ARM の dat/ が入力と違う. 調査用に dat/ を残して止める" >&2
    exit 1
fi
if [ "$KEEP" = "keep" ]; then
    echo "dat/ は残した: ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
