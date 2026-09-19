#!/bin/bash
# 全探索の内訳を計装して測る (記録試行ではない)
# 空の dat/ から searchAll() だけを完走させ, 後退解析は走らせない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$ROOT/experiments/forward_profile"
W="$ROOT/runs/exp_forward_profile"
# 記録 #8 の全探索直後の状態 (tools/rebuild_forward_fixture.py で組み直したもの)
REF="$ROOT/runs/g1_08_fixture/dat"

if [ ! -d "$REF" ]; then
    echo "照合先が無い: $REF" >&2
    echo "  python3 tools/rebuild_forward_fixture.py <#8 の dat> <#8 の main.log> $REF" >&2
    exit 2
fi
# 組み直しが途中で落ちた不完全な dat/ でも [ -d ] は通る. 完成の印を見る
# (未知 20 + キャッチ 29 + トライ負け 2 = 51 ファイル. 5,000,000 件刻み)
if [ "$(find "$REF" -maxdepth 1 -name '*.pickle' | wc -l)" -ne 51 ]; then
    echo "照合先が完成していない (51 ファイルでない): $REF" >&2
    exit 2
fi
# 前回の作業ディレクトリが残っていたら消さずに止める (失敗時に残した dat/ が調査用の証拠)
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi

echo "=== 開始 $(date --iso-8601=seconds) ==="
mkdir -p "$W/dat" "$W/kaiseki_log"
cp "$SRC/animal_shogi.py" "$W/"
# C は impl/08 のもの (前向き探索が使う nextBoardInvNormal は baseline と同一.
# 索引の関数は import 時に ctypes が引くので, impl/08 の .so が要る)
cp "$ROOT/impl/08_c_index/animal_shogi.c" "$ROOT/impl/08_c_index/animal_shogi.h" "$W/"
(cd "$W" && gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)

# ⚠️ import animal_shogi は .so を拾う (C 拡張が .py より優先される)
cat > "$W/driver.py" <<'PY'
import importlib.util
import time

spec = importlib.util.spec_from_file_location("expmod", "animal_shogi.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.perf_counter()
mod.searchAll()
print("全探索の所要時間：%.2f 秒" % (time.perf_counter() - t))
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
# 途中で止められてもサンプラを孤児にしない (tools/run.sh の stop_sampler と同じ手当て)
trap 'kill "$SPID" 2>/dev/null || true' EXIT

set +e
(cd "$W" && /usr/bin/time -v python3 driver.py > stdout.txt 2> time.txt)
RC=$?
set -e
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $(date --iso-8601=seconds) (exit=$RC) ==="
cat "$W/stdout.txt"
grep -E "Elapsed|Maximum resident|Percent of CPU|File system outputs" "$W/time.txt" || true
cat "$W/kaiseki_log/forward_profile_summary.tsv" || true

if [ "$RC" -ne 0 ]; then
    echo "!!! 全探索が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- 記録 #8 の全探索直後の状態と指紋照合 ---"
# 計装で答えが変わっていないことの確認. FAIL なら止めて dat/ を残す
# 結果は $W/fingerprint.txt にも残す (dat/ を消したあとの唯一の証拠になる)
if ! python3 "$ROOT/tools/fingerprint_dat.py" "$W/dat" "$REF" | tee "$W/fingerprint.txt"; then
    echo "!!! 指紋が一致しない. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 照合が済んだら dat/ は捨てる (2 GB)
rm -rf "$W/dat"
echo "=== 完了 $(date --iso-8601=seconds) ==="
