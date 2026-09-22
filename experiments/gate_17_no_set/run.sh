#!/bin/bash
# 門番 #17: 後退解析を1本走らせ, 書き出しの set(...) だけを1変数にする (記録試行ではない)
#
#   run.sh <old|new> <ラベル> [keep]
#   old = impl/16_raw_binary (set(...) あり) / new = impl/17_no_set (外した)
#
# #17 は書き出しの set(...) を外したので, ファイルに並ぶ順序が「集合の反復順」から
# 「渡された並びそのまま」に変わる. 本走ではそれが採番順を動かし, P2・P4・174段ループの
# 局所性まで変えてしまうので, 本走の1本では「書き出しが速くなったぶん」と
# 「採番順が動いたぶん」が混ざる.
#
# ここは**両腕に同じフィクスチャ (同一のバイト列) を渡す**. 両腕とも frombytes で
# 読むので packed は完全に同一になり, P0〜P4 は同じ仕事をする. 動くのは
# 174段ループの書き出しと writeUnknownChunks だけ.
#
# ⚠️ 両腕とも numactl で片ノードに固定する. experiments/numa_bind で, 固定すると
#    P2 の標準偏差が 15.69 → 0.71 秒に縮むことが分かっている. 見たい差が
#    数秒なので雑音を落としておく. 腕の扱いは対称なので偏りは入らない.
#    ⚠️ **この帯は「固定した条件での帯」で, 本走 (固定なし) には移せない.**
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?old か new を指定すること}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"

# 両腕とも生バイナリ. 形式は #17 のレバーではないので, 同じフィクスチャを渡せる
# (#16 の門番は腕ごとに形式が違ったので convert_fixture.py が要った. ここは要らない)
FIX="$ROOT/runs/g1_11_fixture_bin/dat"
case "$ARM" in
    old) IMPL="impl/16_raw_binary" ;;
    new) IMPL="impl/17_no_set" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
SRC="$ROOT/$IMPL"
W="$ROOT/runs/exp_gate17_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)

if ! command -v numactl > /dev/null; then
    echo "numactl が無い" >&2
    exit 2
fi
# 組み直しが途中で落ちた不完全な dat/ でも [ -d ] は通る. 完成の印を見る
# (未知 20 + キャッチ 29 + トライ負け 2 = 51 ファイル)
if [ "$(find "$FIX" -maxdepth 1 -name "*.bin" 2>/dev/null | wc -l)" -ne 51 ]; then
    echo "フィクスチャが完成していない (51 ファイルでない): $FIX" >&2
    echo "  tools/rebuild_forward_fixture.py で作り直せる (出力は必ず .bin)" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi

echo "=== 開始 $LABEL ($ARM $IMPL) $(date --iso-8601=seconds) ==="
mkdir -p "$W/kaiseki_log"
cp -r "$FIX" "$W/dat"
cp "$SRC/animal_shogi.py" "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$W/"
(cd "$W" && gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)

# ⚠️ import animal_shogi は .so を拾う (C 拡張が .py より優先される)
cat > "$W/driver.py" <<'PY'
import importlib.util
import time

spec = importlib.util.spec_from_file_location("gatemod", "animal_shogi.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.perf_counter()
mod.retreatAnalysis()
print("後退解析の所要時間：%.2f 秒" % (time.perf_counter() - t))
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
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
grep -E "^P[0-4] |辺の総数|読み込んだ局面" "$W/kaiseki_log/kaizenkaiseki1.txt" || true

if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 174行 ---"
# ⚠️ 止める条件はこれだけ. 速度では止めない
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 検証が済んだら dat/ は捨てる (2 GB × 8本になるため).
# ⚠️ keep を渡した本だけ残す. 並びが実際に動いたことの照合に要る
if [ "$KEEP" = "keep" ]; then
    # ⚠️ 絶対パスを出さない (publish_lint の「ユーザ名を含む絶対パス」)
    echo "dat/ は残した (並びの照合用): ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
