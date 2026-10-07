#!/bin/bash
# run_time.sh と run_retreat.sh が, 回す前に見る止める条件 (source して使う)
#   1. 一致の検査が PASS (logs/verify.txt)
#   2. A が2マス以上の盤が 0 (q も鏡像も). 出たら計時の前に報告する
check_verify() {
    local v="$1/logs/verify.txt"
    if ! grep -q '^一致の検査: .* => PASS$' "$v"; then
        echo "!!! 一致の検査が PASS でないので測らない (止める条件)" >&2
        return 1
    fi
    if ! grep -q '^A が2マス以上の盤: q 0 / 鏡像 0$' "$v"; then
        echo "!!! A が2マス以上の盤があったので測らない (計時の前に報告する)" >&2
        return 1
    fi
}
