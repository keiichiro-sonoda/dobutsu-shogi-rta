#!/bin/bash
# -march=native が何に解決されるかを出す (門番 #32。記録試行ではない)
#
#   march.sh
#
# 2腕とも -march=native でビルドする (#28 から). 別の CPU では別のバイナリになるので, 門番のログに残す.
# gcc -Q --help=target の -march= と -mtune= の行と, -march=native で新しく定義される
# 命令セットのマクロ (x86-64 のベースラインとの差) を出す
set -euo pipefail
echo "# gcc: $(gcc --version | head -1)"
echo "# gcc -march=native -Q --help=target の -march= / -mtune="
gcc -march=native -Q --help=target | grep -E '^\s+-m(arch|tune)=\s' | tr -s ' \t' ' '
echo "# -march=native で増える事前定義マクロ (__AVX2__ など, 命令セットのものだけ)"
comm -13 <(gcc -dM -E - < /dev/null | awk '{print $2}' | sort) \
         <(gcc -march=native -dM -E - < /dev/null | awk '{print $2}' | sort) \
    | grep -E '^__(AVX|BMI|LZCNT|MOVBE|POPCNT|SSE|FMA|F16C|ADX|RDRND|RDSEED|PCLMUL|AES|FSGSBASE|PRFCHW|XSAVE|RTM|HLE|CX16|LAHF|SAHF|ABM)[A-Z0-9_]*__$' \
    | tr '\n' ' '
echo
