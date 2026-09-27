#!/bin/bash
# 空きメモリの読みをファイルに残す (門番 #24。記録試行ではない)
#
#   free_snapshot.sh <名前>     → logs/free_<名前>.txt
#
# 門番を起動する前に空きを確かめるとき, キャッシュを落とす前と後に使う. 手で読んだだけの値を作らない
# (#23 では, 起動する前に読んだ値と落とした直後の値がどこにも残らなかった).
# 読み方は run_one.sh と同じ (lib.sh の hugefree_gib. /proc/buddyinfo の order 9 以上)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
NAME="${1:?名前を指定すること (例: before_launch / before_drop / after_drop)}"
OUT="$HERE/logs/free_$NAME.txt"
if [ -e "$OUT" ]; then
    echo "$OUT が既にある. 上書きしない" >&2
    exit 2
fi
mkdir -p "$HERE/logs"
{
    echo "# $(date --iso-8601=seconds) の空きメモリ (free_snapshot.sh $NAME)"
    echo "2 MiB 以上の空きブロック: node0 $(hugefree_gib 0) / node1 $(hugefree_gib 1) / 合計 $(hugefree_gib all) GiB" \
        "(門番はノード0で ${HUGEFREE_MIN_GIB:-16} GiB 以上)"
    grep '^Node' /proc/buddyinfo 2>/dev/null || true
    for m in /sys/devices/system/node/node*/meminfo; do
        grep -E 'MemFree|FilePages' "$m" 2>/dev/null || true
    done
} > "$OUT"
cat "$OUT"
