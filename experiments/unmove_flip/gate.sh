#!/bin/bash
# run_time.sh と run_retreat.sh が, 回す前に見る止める条件 (source して使う)
#   一致の検査 (logs/verify.txt) が PASS. (0) 写しの確かめ, (a) 候補の多重集合, (b) 前任の多重集合,
#   (c) 正規形でない・到達しないとして捨てる数 の全部
check_verify() {
    if ! grep -qxF '一致の検査: 246803167 局面 => PASS' "$1/logs/verify.txt"; then
        echo "!!! 一致の検査が PASS でないので測らない (止める条件)" >&2
        return 1
    fi
}
