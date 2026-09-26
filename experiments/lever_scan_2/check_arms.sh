#!/bin/bash
# 6腕を組み, 警告と「効いたこと」を機械的に数える (実験 lever_scan_2。記録試行ではない)
#
#   check_arms.sh > logs/warnings.txt
#
# 数えるもの
#   警告              gcc -O2 -Wall -Wextra (門番のビルドは Makefile の -Wall だけ) の warning の件数
#   先読み命令        objdump -d の retreatStep の中の prefetch 命令 (pf2・pf3・all で 0 から増えるはず)
#   madvise           objdump -d の call madvise@plt (hugeR・all で1つ増えるはず)
#   hugeFill          .so が hugeFill を出しているか (hugeR・all)
#   毎ラウンドの確保  .py の searchNext の中の array("Q", unexp_boards) と array("Q", bytes(8)) * n の行数
#                     (base は 4, reuse・all は 0)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARMS=(base pf2 pf3 hugeR reuse all)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "# 6腕を gcc -O2 -Wall -Wextra でビルドしたときの警告と, 効いたことの確認 (check_arms.sh の出力)"
echo "# $(gcc --version | head -1)"
echo "#"
for arm in "${ARMS[@]}"; do
    "$HERE/make_arm.sh" "$arm" "$WORK/$arm" > /dev/null
    warn=$(cd "$WORK/$arm" && gcc -O2 -Wall -Wextra -fPIC -shared animal_shogi.c -o extra.so 2>&1 \
        | grep -c "warning" || true)
    echo "$arm (gcc -O2 -Wall -Wextra): 警告 $warn 件"
done
echo
echo "# 効いたことの確認"
for arm in "${ARMS[@]}"; do
    so="$WORK/$arm/animal_shogi.so"
    pf=$(objdump -d --no-show-raw-insn "$so" | awk '/<retreatStep>:/,/^$/' | grep -c prefetch || true)
    mad=$(objdump -d "$so" | grep -c "call.*<madvise@plt>" || true)
    hf=$(nm -D "$so" | grep -c " T hugeFill$" || true)
    # searchNext の本体だけを見る (次の def の手前まで)
    alloc=$(awk '/^def searchNext\(/ {f = 1; next} f && /^def / {f = 0} f' "$WORK/$arm/animal_shogi.py" \
        | grep -cE 'array\("Q", unexp_boards\)|array\("Q", bytes\(8\)\) \* n$' || true)
    printf '%-6s 先読み命令(retreatStep) %d / madvise %d / hugeFill %d / 毎ラウンドの確保 %d 行\n' \
        "$arm" "$pf" "$mad" "$hf" "$alloc"
done
echo
echo "# パッチの sha256 (この出力を作ったときのもの)"
(cd "$HERE" && sha256sum patches/*.patch)
echo "# 出発点: impl/22_in_memory ($(git -C "$ROOT" log -1 --format=%h -- impl/22_in_memory))"
