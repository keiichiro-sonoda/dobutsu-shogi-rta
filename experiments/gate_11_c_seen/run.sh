#!/bin/bash
# 記録 #11 の門番: impl/11_c_seen の全探索だけを空の dat/ から完走させる
# ⚠️ 記録試行ではない (後退解析を走らせないのでレギュレーションを満たさない)
#
# 止める条件は「答えが違ったとき」だけ. 速度 (F4) は読むだけで, 遅くても本走は走らせる
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$ROOT/impl/11_c_seen"
W="$ROOT/runs/exp_gate_11_c_seen"
# 全探索直後の状態 (tools/rebuild_forward_fixture.py で #8 の完走から組み直したもの)
# 全探索の答え自体は #8 以降変わっていないので, #10 の照合先にもそのまま使える
# (チャンクの分かれ方は変わるが, 指紋は深さごとの集合の要約なので順序に依存しない)
REF="$ROOT/runs/g1_08_fixture/dat"

if [ ! -d "$REF" ]; then
    echo "照合先が無い: $REF" >&2
    echo "  python3 tools/rebuild_forward_fixture.py <#9 の dat> <#9 の main.log> $REF" >&2
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
cat "$W/kaiseki_log/forward_summary.tsv" || true

if [ "$RC" -ne 0 ]; then
    echo "!!! 全探索が失敗 (exit=$RC). 調査用に dat/ を残して打ち切る" >&2
    exit "$RC"
fi

echo "--- 記録 #10 の全探索直後の状態と指紋照合 ---"
# ⚠️ バイト比較は使えない (発見済み集合が C の表になり, 返る順序もチャンクの中身も変わる).
# 指紋は深さごとの (件数, 総和, XOR) なので順序に依存しない
# 結果は $W/fingerprint.txt にも残す (dat/ を消したあとの唯一の証拠になる)
if ! python3 "$ROOT/tools/fingerprint_dat.py" "$W/dat" "$REF" | tee "$W/fingerprint.txt"; then
    echo "!!! 指紋が一致しない. 調査用に dat/ を残して打ち切る" >&2
    exit 1
fi

# 照合が済んだら dat/ は捨てる (2 GB)
rm -rf "$W/dat"
echo "=== 完了 $(date --iso-8601=seconds) ==="
