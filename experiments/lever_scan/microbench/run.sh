#!/bin/bash
# マイクロベンチ 1条件ぶん (実験 lever_scan). 出力は logs/ に置く
#
#   run.sh <uniform|local> <E_BITS> <plain|hp>
#
# 3周・core (count / scatter / store_indep / pf2_32 の4カーネル) で回す.
# 実際に回したときは, 同じ中身のスクリプトを runs/ に置き, バイナリも runs/scatter_bench に
# 置いて絶対パスで呼んだ. そのため logs/*_time.txt の「Command being timed」には
# ユーザ名を含む絶対パスが入っていて, 公開前にその部分を <ROOT>/ に置き換えた.
# ここではバイナリを一時ディレクトリに作り, 相対パスで呼ぶ (絶対パスが残らない).
#
# ⚠️ 辺 2^30 で約 10 GB. numactl で片ノードに固定するので, ノード0 の空きを確かめてから回す.
#    その間このマシンで他の計算を回さないこと
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT="$HERE/logs"
name="$1_$2_$3"
BIN_DIR=$(mktemp -d)
trap 'rm -rf "$BIN_DIR"' EXIT
gcc -O2 -Wall -o "$BIN_DIR/scatter_bench" "$HERE/scatter_bench.c"
{
    echo "=== 開始 $name $(date --iso-8601=seconds) ==="
    echo "gcc -O2 -Wall -o scatter_bench scatter_bench.c ($(gcc --version | head -1))"
    echo "numactl --cpunodebind=0 --membind=0 ./scatter_bench $1 $2 $3 3 core"
    (cd "$BIN_DIR" && /usr/bin/time -v numactl --cpunodebind=0 --membind=0 \
        ./scatter_bench "$1" "$2" "$3" 3 core 2> "$OUT/${name}_time.txt")
    echo "=== 終了 $name $(date --iso-8601=seconds) ==="
} > "$OUT/$name.txt" 2>&1
