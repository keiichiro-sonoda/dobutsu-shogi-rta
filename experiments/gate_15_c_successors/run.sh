#!/bin/bash
# 記録 #15 の門番: 後退解析だけを走らせて P2 後続生成を複数回測る (記録試行ではない)
#
#   run.sh <実装ディレクトリ> <ラベル>
#   例: run.sh impl/14_c_retreat old1a / run.sh impl/15_c_successors new1a
#
# この門番は後退解析しか呼ばないので, 全探索フィクスチャがそのまま入力に使える.
# 後退解析だけを何本でも回せる.
# ⚠️ 記録 #15 は expandRound (全探索側) にも手を入れているが, 変わるのは
#    空入力のラウンドの挙動だけで, ここでは全探索を1周も回さない.
#
# ⚠️ フィクスチャは完走した dat/ から tools/rebuild_forward_fixture.py で組み直した
#    もの. 集合は復元できるが採番順は復元しない (tests/test_rebuild_forward_fixture.py
#    が固定している) ので, 本走と同じ条件ではない.
#    P2 後続生成は採番順に反応する段なので, 効果量は「この入力での値」として書く.
#    旧版と新版では同じ入力を使うこと (そのぶんの比較は成り立つ).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
IMPL="${1:?実装ディレクトリを指定すること}"
LABEL="${2:?ラベルを指定すること}"
SRC="$ROOT/$IMPL"
W="$ROOT/runs/exp_gate15_$LABEL"
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

# 検証が済んだら dat/ は捨てる (2 GB × 6本になるため)
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
