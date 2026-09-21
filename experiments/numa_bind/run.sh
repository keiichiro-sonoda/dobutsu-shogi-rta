#!/bin/bash
# 実験 numa_bind: 後退解析を1本走らせる. 片ノードに固定するかどうかだけを変える
# (記録試行ではない)
#
#   run.sh <plain|numa> <ラベル> [keep]
#   例: run.sh plain n1a / run.sh numa n1b keep
#
# experiments/retreat_profile で, P0→P1 の minor fault が索引のページ数
# 2,097,152 とちょうど 1 対 1 になり, p1 だけが 2.41 倍踏んで P1 が
# 20.7 → 34.3 秒に伸びた. 機序の候補に自動 NUMA バランシングが挙がっているが
# 確かめていない. numactl はプロセス単位なので root も sysctl も要らない.
#
# ⚠️ numa 側は --cpunodebind と --membind を同時に付けるので, この実験は
#    「CPU の置き場所」と「メモリの置き場所」を分けられない. 片ノードに
#    固定すると変わるかどうかは言えるが, どちらが効いたかは言えない.
#
# 実装は experiments/numa_bind 固定 (retreat_profile の計装込みの写し). 腕は
# numactl の有無だけで, コードは16本とも同じものを使う.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
MODE="${1:?plain か numa を指定すること}"
LABEL="${2:?ラベルを指定すること}"
KEEP="${3:-}"
SRC="$ROOT/experiments/numa_bind"
W="$ROOT/runs/exp_numa_bind_$LABEL"
FIX="$ROOT/runs/g1_11_fixture/dat"

case "$MODE" in
    plain) NUMA=() ;;
    # --membind は厳密で, node0 で足りなくなるとフォールバックせずに落ちる.
    # ピーク RSS 13.9 GiB に対し node0 は 31.3 GiB あるので通る見込み
    numa)  NUMA=(numactl --cpunodebind=0 --membind=0) ;;
    *)     echo "腕は plain か numa: $MODE" >&2; exit 2 ;;
esac
if [ "$MODE" = numa ] && ! command -v numactl > /dev/null; then
    echo "numactl が無い" >&2
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

echo "=== 開始 $LABEL ($MODE) $(date --iso-8601=seconds) ==="
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

# /proc/vmstat の NUMA と移動のカウンタ. 解析の直前と直後の2行だけ残し,
# 差分は読む側で引く.
# ⚠️ これはマシン全体の累積値. 他のプロセスのぶんも入るので,
#    「このプロセスの値」とは書けない. 走行中に他の計算を回していなければ
#    差分はほぼこの走行のもの, と書けるだけ.
VMSTAT_KEYS=(
    numa_hint_faults numa_hint_faults_local numa_pages_migrated
    numa_local numa_other pgmigrate_success pgmigrate_fail
    compact_stall compact_success compact_fail
)
vmstat_row() {
    printf '%s' "$1"
    for k in "${VMSTAT_KEYS[@]}"; do
        printf '\t%s' \
            "$(awk -v k="$k" '$1==k {v=$2} END {print (v == "" ? "-" : v)}' /proc/vmstat)"
    done
    printf '\n'
}
{
    printf 'when'
    printf '\t%s' "${VMSTAT_KEYS[@]}"
    printf '\n'
} > "$W/vmstat.tsv"

# 1分おきに CPU 周波数・温度・スロットル回数と, メモリの状態
# ⚠️ 列は experiments/retreat_profile と同じ8列. 前半5列は tools/run.sh と
#    同じ名前・同じ順番で, 足してあるのは末尾の3列だけ
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

# ⚠️ numactl は execvp で python に化けるので, time -v が測る rusage は
#    plain のときと同じもの. time.txt の列は変わらない.
#    ビルドと採取ループは包まない (包むとこの実験の腕が増える)
vmstat_row before >> "$W/vmstat.tsv"
set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Percent of CPU" "$W/time.txt" || true
grep -E "^P[0-4] |辺の総数|読み込んだ局面" "$W/kaiseki_log/kaizenkaiseki1.txt" || true
if [ -f "$W/kaiseki_log/retreat_summary.tsv" ]; then
    echo "--- 段ごとの要約 ---"
    cat "$W/kaiseki_log/retreat_summary.tsv"
fi
echo "--- vmstat (前後) ---"
cat "$W/vmstat.tsv"

if [ "$RC" -ne 0 ]; then
    # ⚠️ numa 側は --membind が厳密なので, node0 で足りなければここに落ちる.
    #    落ちた本のタイムは無効 (CLAUDE.md). 再開ではなく再走すること
    echo "!!! 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- オラクル 174行 ---"
# ⚠️ 止める条件はこれだけ. 速度では止めない
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 検証が済んだら dat/ は捨てる (2 GB × 16本になるため).
# ⚠️ keep を渡した本だけ残す. oracle/fingerprint.tsv との照合に要る
if [ "$KEEP" = "keep" ]; then
    # ⚠️ 絶対パスを出さない. ユーザ名が入るとログが publish_lint の
    #    「ユーザ名を含む絶対パス」に引っかかる (CLAUDE.md「記録に残さないもの」)
    echo "dat/ は残した (指紋の照合用): ${W#"$ROOT"/}/dat"
else
    rm -rf "$W/dat"
fi
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
