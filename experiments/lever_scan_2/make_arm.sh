#!/bin/bash
# 腕のソースを組んで .so までビルドする (実験 lever_scan_2。記録試行ではない)
#
#   make_arm.sh <腕> <出力先ディレクトリ>
#
# 出発点は6腕とも impl/22_in_memory (記録 #22)。impl/22_in_memory 自体は凍結物なので触らず,
# 写しにパッチを当てる。パッチは patches/ にあり, 当てる順に並べたときの前の状態に対する unified diff。
#
#   base    instr
#   pf2     instr → pf2     (retreatStep に2段の先読み。距離 32 / 16)
#   pf3     instr → pf3     (pf2 ＋ 3段目。8 個先の q の前任を最大4本読み, dtm / cnt を先読み)
#   hugeR   instr → hugeR   (pred / pred_off / cnt / dtm を hugeAlloc で確保。先読みは入れない)
#   reuse   instr → reuse   (F1 の受け皿を使い回し, 入力の写しをやめる。待ち行列の区切りは変えない)
#   all     instr → pf3 → hugeR → reuse
#
# instr は全腕に同じ計装 (段ごとの minor fault と, 174段ループの配列が生きているうちの巨大ページ)。
# 計装が腕で違うと, 計装の費用がレバーの効果に混ざるため。
# ビルドは impl/22 の Makefile のまま (gcc -O2 -Wall)。-Wextra の検査は check_arms.sh が別にやる
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (base|pf2|pf3|hugeR|reuse|all)}"
DST="${2:?出力先を指定すること}"
SRC="$ROOT/impl/22_in_memory"

case "$ARM" in
    base)  PATCHES=(instr) ;;
    pf2)   PATCHES=(instr pf2) ;;
    pf3)   PATCHES=(instr pf3) ;;
    hugeR) PATCHES=(instr hugeR) ;;
    reuse) PATCHES=(instr reuse) ;;
    all)   PATCHES=(instr pf3 hugeR reuse) ;;
    *)     echo "腕は base pf2 pf3 hugeR reuse all のどれか: $ARM" >&2; exit 2 ;;
esac

mkdir -p "$DST"
cp "$SRC/animal_shogi.py" "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/Makefile" "$DST/"
for p in "${PATCHES[@]}"; do
    # 衝突したら (fuzz で黙って当てずに) 止める
    patch --quiet --forward --fuzz=0 --no-backup-if-mismatch -p1 -d "$DST" < "$HERE/patches/$p.patch"
done
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: impl/22_in_memory + パッチ「${PATCHES[*]}」"
