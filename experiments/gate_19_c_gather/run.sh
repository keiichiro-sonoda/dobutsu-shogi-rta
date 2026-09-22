#!/bin/bash
# 門番 #19: 連番→パック値の翻訳を C 側へ移す前後を, 後退解析だけで比べる
# (記録試行ではない)
#
#   run.sh <old|new> <ラベル> [keep]
#
# ⚠️ **old 腕は「計装だけ」を入れた impl/18.** 今回は計装とレバーが同じ実装に入る
#    ので, 新しい区間 (R_loop→R_draw = 引き分けの抽出) には「前の値」が存在しない.
#    old 腕にも同じ計装を載せておくと, その区間の before / after が両方出る.
#
#   old : impl/18_optimized の C・ヘッダ・Makefile ＋ old/animal_shogi.py (計装だけ)
#   new : impl/19_c_gather をそのまま
#
# ビルドは実装の Makefile をそのまま使う (両腕とも -O2. 記録 #18 のまま).
# フラグをここに書かないので, Makefile が動いたら門番も一緒に動く.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (old|new)}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"

FIX="$ROOT/runs/g1_11_fixture_bin/dat"
case "$ARM" in
    old) SRC="$ROOT/impl/18_optimized"; PY="$HERE/old/animal_shogi.py" ;;
    new) SRC="$ROOT/impl/19_c_gather";  PY="$SRC/animal_shogi.py" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
W="$ROOT/runs/exp_gate19_$LABEL"
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

echo "=== 開始 $LABEL ($ARM / ${SRC#"$ROOT"/}) $(date --iso-8601=seconds) ==="
mkdir -p "$W/kaiseki_log"
cp -r "$FIX" "$W/dat"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/Makefile" "$W/"
cp "$PY" "$W/animal_shogi.py"
(cd "$W" && make animal_shogi.so)

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

# 生ログを門番の下に引き取る (runs/ は git 管理外なので, 置いたままだと根拠が消える)
cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"

# 検証が済んだら dat/ は捨てる (2 GB × 8本になるため).
# ⚠️ keep を渡した本だけ残す. 翻訳を C に移しても並びは1ビットも動かないはずなので,
#    腕どうしがバイト同一になることを確かめるのに要る
if [ "$KEEP" = "keep" ]; then
    # ⚠️ 絶対パスを出さない (publish_lint の「ユーザ名を含む絶対パス」)
    echo "dat/ は残した (腕どうしのバイト比較用): ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
