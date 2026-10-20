#!/bin/bash
# 実験 dtm_ahead: 一致の検査の完走 1本 → 完走の比較 12本 → perf 6本 ＝ 計 19本 (記録試行ではない).
# 進行は logs/console.log に残す (どの本も「=== 開始 <ラベル> (…) <時刻> ===」の行を出す)
#
#   1. 一致の検査 (計時に使わない): ahead1 を1本. 答えの検査に加えて dat/ 全213ファイルを #39 本走と diff -rq.
#      ラベル v_ahead1, 生ログは logs/verify/. 外れたら先に進まない (止める条件 1)
#   2. 完走の比較: base ahead1 ahead1 base を3ブロック (各腕6本). ラベル c<ブロック><a〜d>_<腕>, 生ログは logs/compare/
#   3. perf: 2腕 × (stat:T1, stat:M1, record:cyc). 順は base T1 → ahead1 T1 → ahead1 M1 → base M1 → base cyc → ahead1 cyc.
#      ラベル p_<腕>_<T1|M1|cyc>, 生ログは logs/perf/
# どの本も numactl でノード0に固定し, 走る前にノード0の空きを確かめる (run_one.sh / run_perf_one.sh. 8 GiB).
# 回す前の確かめ (preflight.sh): kernel.perf_event_paranoid が 1, CPU 使用率 3% 以下. 負荷は load average と
# CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
# ⚠️ 1本あたり完走 1.5 分 + 検査とビルド 約 0.5 分で, 19本で約 40〜60 分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/39_rank_lean" -name __pycache__)" ]; then
    echo "impl/39_rank_lean に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== dtm_ahead 開始 $(date --iso-8601=seconds) ==="
"$HERE/preflight.sh"

echo "### 1. 一致の検査の完走 (計時に使わない)"
LOGS="$HERE/logs/verify" DIFF_DAT=1 "$HERE/run_one.sh" ahead1 v_ahead1

echo "### 2. 完走の比較 (base ahead1 ahead1 base × 3)"
for b in 1 2 3; do
    LOGS="$HERE/logs/compare" "$HERE/run_one.sh" base "c${b}a_base"
    LOGS="$HERE/logs/compare" "$HERE/run_one.sh" ahead1 "c${b}b_ahead1"
    LOGS="$HERE/logs/compare" "$HERE/run_one.sh" ahead1 "c${b}c_ahead1"
    LOGS="$HERE/logs/compare" "$HERE/run_one.sh" base "c${b}d_base"
done

echo "### 3. perf (2腕 × T1・M1・cycles)"
for job in base:stat:T1 ahead1:stat:T1 ahead1:stat:M1 base:stat:M1 base:record:cyc ahead1:record:cyc; do
    arm=${job%%:*}
    kind=${job#*:}
    s=${kind#*:}
    LOGS="$HERE/logs/perf" "$HERE/run_perf_one.sh" "$arm" "$kind" "p_${arm}_${s}"
done
echo "=== 全19本 完了 $(date --iso-8601=seconds) ==="
