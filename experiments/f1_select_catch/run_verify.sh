#!/bin/bash
# 一致の検査 (実験 f1_select_catch。記録試行ではない). 計時はしない
#
#   run_verify.sh <base の animal_shogi.so> <腕>=<腕の animal_shogi.so> ...
#
# experiments/bitboard_gen/run_verify.sh の写し. 違いは入力を #37 本走の dat/ にしたことと, 腕を引数で渡すこと.
# 入力は #37 本走の dat/ の全 213 ファイル (到達可能な全 246,803,167 局面. 読むだけで, 中へ cd しない).
# 使う前に, dat/ の md5 一覧の sha256 が results/37_mirror1/bytecompare.txt の #37 の値と同じことを見る.
# verify.c で, 腕ごとに base と (a) 戻り値 (b) 正のときの後続の列 (並びまで) (c) *non_catch を全局面で比べる.
# 結果は logs/verify_<腕>.txt (不一致は最初の 20 局面まで. 最後の行に局面の内訳と不一致の数).
# 1局面でも外れた腕は計時しない (run_all.sh が見る)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="$ROOT/runs/20261017-154518_37_mirror1/dat"
W="$ROOT/runs/f1_select_catch"
NUMA=(numactl --cpunodebind=0 --membind=0)
[ -d "$DAT" ] || { echo "#37 本走の dat/ が無い: $DAT" >&2; exit 2; }
BASE="${1:?base の .so を渡すこと}"
shift
mkdir -p "$W"
# md5 一覧の sha256 は find . -type f | LC_ALL=C sort | xargs md5sum | sha256sum と同じ作り (dat/ の中へ cd しない)
WANT=$(sed -nE 's/^md5 一覧の sha256 \(全桁\): ([0-9a-f]{64})$/\1/p' "$ROOT/results/37_mirror1/bytecompare.txt")
GOT=$(python3 - "$DAT" <<'PY2'
import hashlib, pathlib, sys
d = pathlib.Path(sys.argv[1])
names = sorted((p.name for p in d.iterdir() if p.is_file()), key=lambda s: s.encode())
lines = "".join(f"{hashlib.md5((d / n).read_bytes()).hexdigest()}  ./{n}\n" for n in names)
print(hashlib.sha256(lines.encode()).hexdigest())
PY2
)
echo "入力の dat/ の md5 一覧の sha256: $GOT (#37 本走 ${WANT:-?})"
if [ -z "$WANT" ] || [ "$GOT" != "$WANT" ]; then
    echo "!!! 入力の dat/ が #37 本走と違う" >&2
    exit 2
fi
gcc -O2 -Wall -Wextra "$HERE/verify.c" -o "$W/verify" -ldl
mapfile -t FILES < <(find "$DAT" -name '*.bin' | LC_ALL=C sort)
echo "入力: #37 本走の dat/ の ${#FILES[@]} ファイル"
for spec in "$@"; do
    arm=${spec%%=*}
    so=${spec#*=}
    echo "=== 開始 verify_$arm $(date --iso-8601=seconds) ==="
    set +e
    "${NUMA[@]}" "$W/verify" "$BASE" "$so" "${FILES[@]}" > "$HERE/logs/verify_$arm.txt"
    rc=$?
    set -e
    tail -1 "$HERE/logs/verify_$arm.txt"
    echo "verify_$arm exit=$rc"
    echo "=== 完了 verify_$arm $(date --iso-8601=seconds) ==="
done
