#!/bin/bash
# 採番順が P2 / P4 にどれだけ効くかを測る (記録試行ではない)
# 使い方: experiments/numbering_order/run.sh [並び...]   既定は A B C D E F
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
FIX="$ROOT/runs/g1_07_batch_forward_write/dat"
BASE="$ROOT/runs/exp_numbering_order"
ORDERS=("$@"); [ ${#ORDERS[@]} -eq 0 ] && ORDERS=(A B C D E F)

# 引数はそのまま rm -rf の対象パスになる. ../../baseline のような値を渡されると
# リポジトリごと消せてしまうので, ディレクトリを1つでも作る前に A〜F に限定する
for ORDER in "${ORDERS[@]}"; do
    case "$ORDER" in
        A | B | C | D | E | F) ;;
        *)
            echo "不正な並び: '$ORDER' (A〜F のみ)" >&2
            exit 2
            ;;
    esac
done

mkdir -p "$BASE"
# 1分おきに CPU 周波数・温度・スロットル回数を残す (run.sh と同じ項目)
sample_hw() {
    while :; do
        printf '%s\t%s\t%s\t%s\t%s\n' \
            "$(TZ=Asia/Tokyo date +%Y-%m-%dT%H:%M:%S)" "$CUR_ORDER" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.0f", m/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.1f", m/1000}' \
                /sys/class/thermal/thermal_zone*/temp 2>/dev/null || echo -)" \
            "$(cat /sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count 2>/dev/null || echo -)"
        sleep 60
    done
}

for ORDER in "${ORDERS[@]}"; do
    W="$BASE/$ORDER"
    rm -rf "$W"; mkdir -p "$W/kaiseki_log"
    echo "=================================================================="
    echo "=== ORDER=$ORDER 開始 $(date --iso-8601=seconds) ==="
    cp -r "$FIX" "$W/dat"
    cp "$ROOT/experiments/numbering_order/animal_shogi.py" "$W/"
    cp "$ROOT/baseline/animal_shogi.c" "$ROOT/baseline/animal_shogi.h" "$W/"
    (cd "$W" && gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)
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
    CUR_ORDER="$ORDER"
    printf 'time_jst\torder\tfreq_max_mhz\tpkg_temp_c\tthrottle\n' > "$W/freq.log"
    sample_hw >> "$W/freq.log" 2>/dev/null &
    SPID=$!
    set +e
    (cd "$W" && ORDER="$ORDER" /usr/bin/time -v python3 driver.py > stdout.txt 2> time.txt)
    RC=$?
    set -e
    kill "$SPID" 2>/dev/null || true
    echo "=== ORDER=$ORDER 終了 $(date --iso-8601=seconds) (exit=$RC) ==="
    cat "$W/stdout.txt"
    grep -E "Elapsed|Maximum resident|Swaps|File system outputs|Percent of CPU" "$W/time.txt" || true
    grep -E "^P[0-4] |並べ替え|辺の総数|読み込んだ局面" "$W/kaiseki_log/kaizenkaiseki1.txt" || true
    if [ "$RC" -ne 0 ]; then
        echo "!!! ORDER=$ORDER 解析が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
        exit "$RC"
    fi
    echo "--- オラクル 174行 ---"
    # 答えが変わっていたらタイムに意味がない. FAIL なら止めて dat/ を残す
    if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
        echo "!!! ORDER=$ORDER オラクル検証 FAIL. 調査用に dat/ を残して打ち切る" >&2
        exit 1
    fi
    # 検証が済んだら dat/ は捨てる (1本 2GB)
    rm -rf "$W/dat"
done
echo "=== 実験完了 $(date --iso-8601=seconds) ==="
