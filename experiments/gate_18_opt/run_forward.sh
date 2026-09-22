#!/bin/bash
# 門番 #18 (全探索側): 空の dat/ から searchAll() だけを走らせ, gcc の最適化段だけを
# 1変数にする (記録試行ではない)
#
#   run_forward.sh <o0|o1|o2|o3|o2n> <ラベル> [keep]
#
# ⚠️ **全腕とも impl/17_no_set のソースを使う.** 記録 #18 は Makefile の gcc 行に
#    -O<段> を足すだけで, C も .h も Python も #17 とバイト同一. 門番は Makefile を
#    通さず gcc を直に叩くので, これで動くのは CFLAGS だけになる.
#
# 判定を完走タイムではなく「全探索合計」で行う. 完走タイムの雑音はほぼ全部
# 後退解析から来ていて (4本ずつの95%半幅が 1.4〜5.7 s 対 28 s), かつ
# いちばん計算寄りの段 (F1 153.8 秒) が全探索側に居る.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (o0|o1|o2|o3|o2n)}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"

# ⚠️ o0 は -O0 と明示しない. 記録 #17 までの Makefile と字面を揃える
case "$ARM" in
    o0)  CFLAGS="" ;;
    o1)  CFLAGS="-O1" ;;
    o2)  CFLAGS="-O2" ;;
    o3)  CFLAGS="-O3" ;;
    o2n) CFLAGS="-O2 -fno-semantic-interposition" ;;
    *)   echo "腕は o0 o1 o2 o3 o2n のどれか: $ARM" >&2; exit 2 ;;
esac
IMPL="impl/17_no_set"
SRC="$ROOT/$IMPL"
W="$ROOT/runs/exp_gate18f_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)

if ! command -v numactl > /dev/null; then
    echo "numactl が無い" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
# 成果物は約 2 GB. 余裕を見る
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 8000000 ]; then
    echo "空きが 8 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

echo "=== 開始 $LABEL ($ARM gcc「${CFLAGS:-フラグなし}」/ $IMPL) $(date --iso-8601=seconds) ==="
# ⚠️ dat/ は空で作る. レギュレーションと同じ出発点
mkdir -p "$W/dat" "$W/kaiseki_log"
cp "$SRC/animal_shogi.py" "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$W/"
# ⚠️ CFLAGS はクォートしない. o0 の腕では空なので, 空の引数を渡さないため
# shellcheck disable=SC2086
(cd "$W" && gcc $CFLAGS animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)

# ⚠️ import animal_shogi は .so を拾う (C 拡張が .py より優先される)
# searchAll() は forward.tsv / forward_summary.tsv を自分で書き, 終端の書き出し
# (flushTerminalBoards) と発見済み表の解放まで含む. retreatAnalysis() は呼ばない
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

# 1分おきに CPU 周波数・温度・スロットル回数と, メモリの状態
# ⚠️ 列は experiments/numa_bind と同じ8列. 前半5列は tools/run.sh と同じ名前・順番
sample_hw() {
    while :; do
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$(TZ=Asia/Tokyo date +%Y-%m-%dT%H:%M:%S)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.0f", m/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{s+=$1; n++} END {if (n) printf "%.0f", s/n/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.1f", m/1000}' \
                /sys/class/thermal/thermal_zone*/temp 2>/dev/null || echo -)" \
            "$(cat /sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count 2>/dev/null || echo -)" \
            "$(awk '/^MemFree:/{print $2}' /proc/meminfo 2>/dev/null || echo -)" \
            "$(awk '/^Cached:/{print $2}' /proc/meminfo 2>/dev/null || echo -)" \
            "$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null || echo -)"
        sleep 60
    done
}
printf 'time_jst\tfreq_max_mhz\tfreq_mean_mhz\tpkg_temp_c\tthrottle\tmem_free_kb\tmem_cached_kb\tmem_available_kb\n' > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
# 途中で止められてもサンプラを孤児にしない
trap 'kill "$SPID" 2>/dev/null || true' EXIT

set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Minor \(reclaiming|File system outputs" "$W/time.txt" || true
grep -E "^(F[0-6]|  F4|--) |総未知盤面数|で全探索終了" "$W/kaiseki_log/kaizenkaiseki1.txt" || true

if [ "$RC" -ne 0 ]; then
    echo "!!! 全探索が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

# ⚠️ 手数別174行はオラクルだが, あれは後退解析の出力なので全探索だけでは出ない.
#    代わりに「到達可能な全局面数」で答えを見る. 未知 + キャッチ + トライ負けが
#    oracle/totals.tsv の reachable_total と一致しなければならない.
#    174行そのものは本走で閉じる.
echo "--- オラクル 到達可能な全局面数 ---"
if ! python3 - "$ROOT" "$W/kaiseki_log/kaizenkaiseki1.txt" <<'PY'
import re
import sys

root, log = sys.argv[1], sys.argv[2]
want = None
for line in open(root + "/oracle/totals.tsv", encoding="utf-8"):
    if line.startswith("reachable_total\t"):
        want = int(line.split("\t")[1])
if want is None:
    print("FAIL: oracle/totals.tsv に reachable_total が無い")
    raise SystemExit(1)
text = open(log, encoding="utf-8").read()
m = re.search(r"^総未知盤面数：(\d+), 総勝ち盤面数：(\d+), 総負け盤面数：(\d+)$", text, re.MULTILINE)
if not m:
    print("FAIL: メインログに総数の行が無い")
    raise SystemExit(1)
uk, win, lose = (int(g) for g in m.groups())
got = uk + win + lose
print("  未知 %d / キャッチ %d / トライ負け %d" % (uk, win, lose))
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

# 検証が済んだら dat/ は捨てる (2 GB × 8本になるため).
# ⚠️ keep を渡した本だけ残す. -O は値も順序も1ビットも変えないはずなので,
#    5腕の dat/ が全部バイト同一になることを確かめるのに要る
if [ "$KEEP" = "keep" ]; then
    # ⚠️ 絶対パスを出さない (publish_lint の「ユーザ名を含む絶対パス」)
    echo "dat/ は残した (腕どうしのバイト比較用): ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
