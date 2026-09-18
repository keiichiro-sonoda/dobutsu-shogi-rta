#!/bin/bash
# 48要素バッファの毎回確保をやめるぶんだけを取り出して測る (記録試行ではない)
# 記録 #8 の門番 G1a。入力は全探索が終わった直後の dat/ で、後退解析だけを回す
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$ROOT/experiments/ffi_buffer_reuse"
W="$ROOT/runs/exp_ffi_buffer_reuse"
FIX="$ROOT/runs/g1_07_batch_forward_write/dat"

echo "=== 開始 $(date --iso-8601=seconds) ==="
rm -rf "$W"
mkdir -p "$W/kaiseki_log"
cp -r "$FIX" "$W/dat"
cp "$SRC/animal_shogi.py" "$W/"
# C は baseline のまま (この実験では触らない)
cp "$ROOT/baseline/animal_shogi.c" "$ROOT/baseline/animal_shogi.h" "$W/"
(cd "$W" && gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)

# ⚠️ import animal_shogi は .so を拾う (C 拡張が .py より優先される)
cat > "$W/driver.py" <<'PY'
import importlib.util
import time

spec = importlib.util.spec_from_file_location("expmod", "animal_shogi.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.time()
mod.retreatAnalysis()
print("後退解析の所要時間：%.1f 秒" % (time.time() - t))
PY

# 1分おきに CPU 周波数・温度・スロットル回数 (tools/run.sh と同じ項目)
sample_hw() {
    while :; do
        printf '%s\t%s\t%s\t%s\n' \
            "$(TZ=Asia/Tokyo date +%Y-%m-%dT%H:%M:%S)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.0f", m/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.1f", m/1000}' \
                /sys/class/thermal/thermal_zone*/temp 2>/dev/null || echo -)" \
            "$(cat /sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count 2>/dev/null || echo -)"
        sleep 60
    done
}
printf 'time_jst\tfreq_max_mhz\tpkg_temp_c\tthrottle\n' > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!

set +e
(cd "$W" && /usr/bin/time -v python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Percent of CPU" "$W/time.txt" || true
grep -E "^P[0-4] |辺の総数|読み込んだ局面" "$W/kaiseki_log/kaizenkaiseki1.txt" || true

if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 174行 ---"
# 答えが変わっていたらタイムに意味がない. FAIL なら止めて dat/ を残す
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 検証が済んだら dat/ は捨てる (2 GB)
rm -rf "$W/dat"
echo "=== 完了 $(date --iso-8601=seconds) ==="
