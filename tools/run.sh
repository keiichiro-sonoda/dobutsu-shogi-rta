#!/usr/bin/env bash
# 実装を1つ選んで計測する。
#
#   tools/run.sh [実装ディレクトリ] [ラベル]
#
#   tools/run.sh                      baseline/ を計測 (ラベル: baseline)
#   tools/run.sh baseline             同上
#   tools/run.sh impl/01_wrapper      impl/01_wrapper/ を計測 (ラベル: 01_wrapper)
#   tools/run.sh impl/01_wrapper w1   ラベルだけ変える
#
# 実装ディレクトリは $ROOT からの相対パス。絶対パスも受け付ける。
# runs/<日時>_<ラベル>/ を作り、実装ディレクトリの中身を丸ごとコピーしてから
# その中で完結して走らせる。実装のソースは一切書き換えない
# (./dat/ と ./kaiseki_log/ をカレント相対で使う実装があるので cd する)。
#
# ビルドと実行のコマンドは、実装ディレクトリに impl.env を置けば差し替えられる。
# 無ければベースラインと同じ既定値を使う:
#
#   BUILD_CMD="make animal_shogi.so"
#   RUN_CMD="python3 ./animal_shogi.py"
#   MAIN_LOG="kaiseki_log/kaizenkaiseki1.txt"
#
# impl.env は bash として読み込まれる。C / Rust へ移っても、そこに
# BUILD_CMD="cargo build --release" のように書けば同じ導線に乗る。
# impl.env 自体は作業ディレクトリへコピーしない (実装の一部ではないため)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- 実装の選択 -----------------------------------------------------------
IMPL_ARG="${1:-baseline}"
case "$IMPL_ARG" in
    /*) IMPL_DIR="$IMPL_ARG" ;;
    *)  IMPL_DIR="$ROOT/$IMPL_ARG" ;;
esac
if [ ! -d "$IMPL_DIR" ]; then
    echo "ERROR: 実装ディレクトリが無い: $IMPL_ARG" >&2
    exit 1
fi
IMPL_DIR="$(cd "$IMPL_DIR" && pwd)"
LABEL="${2:-$(basename "$IMPL_DIR")}"

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$ROOT/runs/${STAMP}_${LABEL}"

# 既定値はベースラインの構成。impl.env があれば上書きされる
BUILD_CMD="make animal_shogi.so"
RUN_CMD="python3 ./animal_shogi.py"
MAIN_LOG="kaiseki_log/kaizenkaiseki1.txt"
if [ -f "$IMPL_DIR/impl.env" ]; then
    # shellcheck source=/dev/null
    . "$IMPL_DIR/impl.env"
fi

# --- 事前チェック ---------------------------------------------------------
# ピーク時に十分な空きが要る (最終成果物 + 探索中の中間ファイル)
NEED_GB=40
AVAIL_GB="$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')"
if [ "$AVAIL_GB" -lt "$NEED_GB" ]; then
    echo "ERROR: 空き容量が足りない (${AVAIL_GB}GB < ${NEED_GB}GB)" >&2
    exit 1
fi

mkdir -p "$WORK"/{dat,kaiseki_log}
cp -R "$IMPL_DIR"/. "$WORK/"
rm -f "$WORK/impl.env"

# --- ハードウェアのサンプラ -------------------------------------------------
# 記録 #4 で、同一コードの全探索が 2430 / 2436 / 2503 秒とばらついた (幅 3.0%)。
# 原因は未解明。調査はせず、後から判断材料になる値だけ1分おきに残す。
#
# 1スレッドの負荷なので、意味があるのは全 CPU の「最大」周波数。
# 平均は他コアのアイドルに引きずられるが、比較のために両方出す。
# 読めない環境 (別の計測機、CI) では "-" を書いて先へ進む。

# hw_field <awk プログラム> <ファイル...>  読めなければ "-"
hw_field() {
    local prog="$1"
    shift
    local out=""
    out="$(awk "$prog" "$@" 2>/dev/null)" || out=""
    printf '%s' "${out:--}"
}

# awk の中の $1 はフィールド番号なので、シェルには展開させない
# shellcheck disable=SC2016
sample_hw_row() {
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$(TZ=Asia/Tokyo date +%Y-%m-%dT%H:%M:%S)" \
        "$(hw_field '{if ($1>m) m=$1} END {if (NR) printf "%.0f", m/1000}' \
            /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq)" \
        "$(hw_field '{s+=$1; n++} END {if (n) printf "%.0f", s/n/1000}' \
            /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq)" \
        "$(hw_field '{if ($1>m) m=$1} END {if (NR) printf "%.1f", m/1000}' \
            /sys/class/thermal/thermal_zone*/temp)" \
        "$(hw_field '{print $1}' \
            /sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count)"
}

sample_hw_header() {
    printf 'time_jst\tfreq_max_mhz\tfreq_mean_mhz\tpkg_temp_c\tthrottle\n'
}

sample_hw_loop() {
    while :; do
        sleep 60
        sample_hw_row
    done
}

SAMPLER_PID=""
stop_sampler() {
    if [ -n "$SAMPLER_PID" ]; then
        kill "$SAMPLER_PID" 2>/dev/null || true
        SAMPLER_PID=""
    fi
}
trap stop_sampler EXIT

# --- 環境の記録 -----------------------------------------------------------
# 何を計測したのかが後から辿れるように、実装の素性もここに残す。
# ホスト名は記録しない。計測機の同一性は cpu / cores / mem_total で足りる
IMPL_SHA="$(cd "$IMPL_DIR" && find . -type f ! -name impl.env -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
{
    echo "label:       $LABEL"
    echo "impl:        $(basename "$IMPL_DIR")"
    echo "impl_sha256: $IMPL_SHA"
    echo "build_cmd:   $BUILD_CMD"
    echo "run_cmd:     $RUN_CMD"
    echo "started:     $(date --iso-8601=seconds)  (TZ=$(date +%Z))"
    echo "started_jst: $(TZ=Asia/Tokyo date --iso-8601=seconds)"
    echo "kernel:      $(uname -srm)"
    echo "cpu:         $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
    echo "cores:       $(nproc) (論理)"
    echo "mem_total:   $(awk '/MemTotal/{printf "%.1f GB", $2/1048576}' /proc/meminfo)"
    echo "gcc:         $(gcc --version | head -1)"
    echo "python:      $(python3 --version)"
    echo "git_commit:  $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo n/a)"
} | tee "$WORK/env.txt"

cd "$WORK"
eval "$BUILD_CMD" 2>&1 | tee build.log

echo "=== 計測開始 $(date --iso-8601=seconds) ==="
# ビルドは含めず、計測している区間だけを見る
# 1本目は同期で書く。短い実行でもヘッダだけにならないようにするため
{ sample_hw_header; sample_hw_row; } > freq.log 2>/dev/null
sample_hw_loop >> freq.log 2>/dev/null &
SAMPLER_PID=$!
set +e
/usr/bin/time -v bash -c "$RUN_CMD" > stdout.txt 2> time.txt
RC=$?
set -e
stop_sampler
echo "=== 計測終了 $(date --iso-8601=seconds) (exit=$RC) ==="

echo
if [ ! -f "$MAIN_LOG" ]; then
    echo "ERROR: メインログが無い: $MAIN_LOG" >&2
    echo "  実装がログを別の場所へ書くなら impl.env の MAIN_LOG を直すこと。" >&2
    echo "成果物: $WORK" >&2
    exit 1
fi

grep -E '全探索終了|完全解析にかかった時間' "$MAIN_LOG" || true
echo
grep -E 'Elapsed \(wall clock\)|Maximum resident set size' time.txt || true
echo

# set -e の下で直接呼ぶと、検証が落ちた瞬間にここで打ち切られて
# 下の「成果物」が出なくなる。終了コードは自前で拾う
VERDICT=0
python3 "$ROOT/tools/verify_log.py" "$MAIN_LOG" || VERDICT=$?

echo
if [ "$RC" -ne 0 ]; then
    echo "⚠ 解析プロセスが exit=$RC で終わっている。検証が PASS でも記録にはできない。"
fi
echo "成果物: $WORK"
echo "  dat/ は数GBある。不要なら手で消すこと。"

# 解析の終了コードと検証結果の両方が通って初めて成功
if [ "$RC" -ne 0 ]; then
    exit "$RC"
fi
exit "$VERDICT"
