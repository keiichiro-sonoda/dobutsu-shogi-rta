#!/bin/bash
# 実験 retreat_profile: 後退解析を1本走らせ, 段ごとのページフォルトを取る (記録試行ではない)
#
#   run.sh <実装ディレクトリ> <ラベル> [keep]
#   例: run.sh experiments/retreat_profile p1 keep / run.sh impl/15_c_successors base keep
#
# gate_15 の16本で, minor page fault の多い走行と P2 の遅い走行が完全に一致した.
# 遅れが乗るのは P1 と P2 だけで, 増分の最小は索引のページ数 2,097,152 に近い.
# /usr/bin/time -v は走行全体の合計しか出さないので, どの段かが分からない.
#
# ⚠️ フィクスチャは完走した dat/ から tools/rebuild_forward_fixture.py で組み直した
#    もの. 集合は復元できるが採番順は復元しない. ここでは旧新の比較をしないので
#    効果量の話には使わないが, 本走と同じ条件ではないことは同じ.
#
# 第3引数に keep を渡すと dat/ を消さない (計装ありとなしのバイト比較に要る).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
IMPL="${1:?実装ディレクトリを指定すること}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"
SRC="$ROOT/$IMPL"
W="$ROOT/runs/exp_retreat_profile_$LABEL"
FIX="$ROOT/runs/g1_11_fixture/dat"

if [ ! -d "$SRC" ]; then
    echo "実装が無い: $SRC" >&2
    exit 2
fi
# 組み直しが途中で落ちた不完全な dat/ でも [ -d ] は通る. 完成の印を見る
# (未知 20 + キャッチ 29 + トライ負け 2 = 51 ファイル)
if [ "$(find "$FIX" -maxdepth 1 -name '*.pickle' 2>/dev/null | wc -l)" -ne 51 ]; then
    echo "フィクスチャが完成していない (51 ファイルでない): $FIX" >&2
    echo "  python3 tools/rebuild_forward_fixture.py <#11 の dat> results/11_c_seen/main.log $FIX" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi

echo "=== 開始 $LABEL ($IMPL) $(date --iso-8601=seconds) ==="
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
# ⚠️ 前半5列は tools/run.sh と同じ名前・同じ順番. 足すのは末尾の3列だけ
#    (gate_15 の run.sh は freq_mean_mhz が無い4列だった. ここでは本走に揃える)
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
(cd "$W" && /usr/bin/time -v python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Percent of CPU" "$W/time.txt" || true
grep -E "^P[0-4] |辺の総数|読み込んだ局面" "$W/kaiseki_log/kaizenkaiseki1.txt" || true
if [ -f "$W/kaiseki_log/retreat_summary.tsv" ]; then
    echo "--- 段ごとの要約 ---"
    cat "$W/kaiseki_log/retreat_summary.tsv"
fi

if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 174行 ---"
# ⚠️ 止める条件はこれだけ. 速度では止めない (遅くても本走は走らせる)
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 検証が済んだら dat/ は捨てる (2 GB × 9本になるため).
# ⚠️ keep を渡した本だけ残す. 計装ありとなしのバイト比較に要る
if [ "$KEEP" = "keep" ]; then
    # ⚠️ 絶対パスを出さない. ユーザ名が入るとログが publish_lint の
    #    「ユーザ名を含む絶対パス」に引っかかる (CLAUDE.md「記録に残さないもの」)
    echo "dat/ は残した (バイト比較用): ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
