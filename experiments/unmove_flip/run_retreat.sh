#!/bin/bash
# 試作の後退解析 (unmove_prune の drop) を, 絞った版 (pruned) と反転を1回にした版 (flip) の逆向きの生成器で交互に3本ずつ回し,
# 毎回ループのあとで成果物の形へ書き出す (実験 unmove_flip。記録試行ではない). run_verify.sh のあとに回す
#
#   run_retreat.sh [dat/]
#
#   並び: pruned flip flip pruned pruned flip
#
# どの本も numactl でノード0に固定する. 1本ごとに:
#   1. 前の本の書き出し先 (runs/unmove_flip/out/) を消し, sync で書き戻しを済ませる
#   2. 巨大ページに使える空きを logs/free.txt に残す. ノード0 が 12 GiB に満たなければ止める
#   3. 回す. 終わったら全局面の (勝敗, 手数) を dat/ と比べる (bench retreat)
#   4. 書き出した成果物を check_out.py で確かめる (ファイルの名前と件数を #33 の dat/ と, 手数ごとの件数を
#      oracle/distribution.tsv と, 指紋を oracle/fingerprint.tsv と). 出力は logs/out_<ラベル>.txt
# 止める条件: 一致の検査が PASS でなければ回さない (gate.sh). どちらかの版が dat/ と一致しなかったら, そこで止める.
#             成果物の確かめが外れたら止めずに続け, 書き出しの費用を換算に使わない (summary.py が見る)
# 進行は logs/console_retreat.log, 本ごとの段の内訳は logs/retreat_<ラベル>.txt
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (CLAUDE.md「記録に残さないもの」)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
# shellcheck source-path=SCRIPTDIR source=gate.sh
source "$HERE/gate.sh"
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
W="$ROOT/runs/unmove_flip"
OUTD="$W/out"
NUMA=(numactl --cpunodebind=0 --membind=0)
ORDER=(pruned flip flip pruned pruned flip)
if [ -e "$HERE/logs/console_retreat.log" ]; then
    echo "logs/console_retreat.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
check_verify "$HERE"
exec > >(tee "$HERE/logs/console_retreat.log") 2>&1
echo "=== unmove_flip 試作の後退解析 開始 $(date --iso-8601=seconds) ==="
echo "flip.so sha256 $(sha256sum "$W/build/flip.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "先読み: どちらの版も, 候補のランクで cls の行を, 残った前任で dtm (と cnt) の行を取り寄せる (unmove_prune と同じ)"
echo "書き出し先: runs/unmove_flip/out/ ($(df --output=fstype "$W" | tail -1 | tr -d " "). 読む dat/ と同じファイルシステム). fsync はしない. 各本の前に消して sync する"
echo "THP enabled: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
FB0=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
freq_header > "$HERE/logs/retreat_freq.log"
sample_hw >> "$HERE/logs/retreat_freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
i=0
for v in "${ORDER[@]}"; do
    i=$((i + 1))
    label="a${i}_$v"
    rm -rf "$OUTD"
    mkdir -p "$OUTD"
    sync
    if ! free_snapshot "$HERE/logs/free.txt" "$label の前" 12; then
        echo "!!! ノード0の巨大ページに使える空きが足りない. ここで止める (logs/free.txt)"
        exit 1
    fi
    echo "--- $label 開始 $(date --iso-8601=seconds) ---"
    set +e
    "${NUMA[@]}" "$W/build/bench" retreat "$W/build/flip.so" "$DAT" "$W" "$v" "$label" "$OUTD" > "$HERE/logs/retreat_$label.txt" 2>&1
    RC=$?
    set -e
    grep -E '^(初期化|書き出し|一致の検査|RESULT|食い違いの内訳)' "$HERE/logs/retreat_$label.txt" || true
    if [ "$RC" -ne 0 ]; then
        echo "!!! $label が一致しなかった (または落ちた. exit=$RC). ここで止める"
        exit 1
    fi
    set +e
    python3 "$HERE/check_out.py" "$OUTD" "$DAT" > "$HERE/logs/out_$label.txt" 2>&1
    set -e
    tail -1 "$HERE/logs/out_$label.txt"
done
rm -rf "$OUTD"
FB1=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
echo "thp_fault_fallback の前後差: $((FB1 - FB0))"
echo "=== unmove_flip 試作の後退解析 全6本 完了 $(date --iso-8601=seconds) ==="
