#!/usr/bin/env bash
# ベースライン (baseline/) を計測する。
#
#   tools/run.sh [ラベル]
#
# runs/<日時>_<ラベル>/ を作り、その中で完結して走らせる。
# ベースラインのソースは一切書き換えない (./dat/ と ./kaiseki_log/ を
# カレントディレクトリ相対で使う実装なので、作業ディレクトリを切って cd する)。
set -euo pipefail

LABEL="${1:-baseline}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$ROOT/runs/${STAMP}_${LABEL}"

# --- 事前チェック ---------------------------------------------------------
# ピーク時に十分な空きが要る (最終成果物 約4.5GB + 探索中の中間ファイル)
NEED_GB=40
AVAIL_GB="$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')"
if [ "$AVAIL_GB" -lt "$NEED_GB" ]; then
    echo "ERROR: 空き容量が足りない (${AVAIL_GB}GB < ${NEED_GB}GB)" >&2
    exit 1
fi

mkdir -p "$WORK"/{dat,kaiseki_log}
cp "$ROOT"/baseline/{animal_shogi.py,animal_shogi.c,animal_shogi.h,Makefile} "$WORK/"

# --- 環境の記録 -----------------------------------------------------------
{
    echo "label:       $LABEL"
    echo "started:     $(date --iso-8601=seconds)  (TZ=$(date +%Z))"
    echo "started_jst: $(TZ=Asia/Tokyo date --iso-8601=seconds)"
    echo "host:        $(hostname)"
    echo "kernel:      $(uname -srm)"
    echo "cpu:         $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
    echo "cores:       $(nproc) (論理)"
    echo "mem_total:   $(awk '/MemTotal/{printf "%.1f GB", $2/1048576}' /proc/meminfo)"
    echo "gcc:         $(gcc --version | head -1)"
    echo "python:      $(python3 --version)"
    echo "git_commit:  $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo n/a)"
} | tee "$WORK/env.txt"

cd "$WORK"
make animal_shogi.so 2>&1 | tee build.log

echo "=== 計測開始 $(date --iso-8601=seconds) ==="
set +e
/usr/bin/time -v python3 ./animal_shogi.py > stdout.txt 2> time.txt
RC=$?
set -e
echo "=== 計測終了 $(date --iso-8601=seconds) (exit=$RC) ==="

# ベースラインは LOG_PATH_MAIN = ./kaiseki_log/kaizenkaiseki1.txt に書く
MAIN_LOG="kaiseki_log/kaizenkaiseki1.txt"

echo
grep -E '全探索終了|完全解析にかかった時間' "$MAIN_LOG" || true
echo
grep -E 'Elapsed \(wall clock\)|Maximum resident set size' time.txt || true
echo

python3 "$ROOT/tools/verify_log.py" "$MAIN_LOG"
VERDICT=$?

echo
echo "成果物: $WORK"
echo "  dat/ は約4.5GB ある。不要なら手で消すこと。"
exit $VERDICT
