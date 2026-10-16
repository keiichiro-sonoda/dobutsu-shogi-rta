// 標本の帰属を確かめる (実験 perf_branch_34。記録試行ではない)
//
// 乱数で転ぶ条件分岐を1つだけ持つループ. 分岐はインラインアセンブリで置き, 番地を objdump で特定できるようにする:
//   test $1, v ; jz 1f (← 外れるのはここ) ; add $1, s (← 次の命令) ; 1: (← 飛び先. ループの続き)
// 予測が外れるのはほぼこの jz だけ (ループの戻りは当たる). 外れの標本がどの番地に付くかで,
// PEBS の番地が「分岐そのもの」か「次の命令・飛び先」かが分かる.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

__attribute__((noinline)) uint64_t work(const uint8_t *a, size_t n, int reps) {
    uint64_t s = 0;
    for (int r = 0; r < reps; r++) {
        for (size_t i = 0; i < n; i++) {
            uint64_t v = a[i];
            __asm__ volatile(
                "test $1, %1\n\t"
                ".globl probe_jz\n"
                "probe_jz:\n\t"
                "jz 1f\n\t"
                ".globl probe_next\n"
                "probe_next:\n\t"
                "add $1, %0\n"
                ".globl probe_target\n"
                "probe_target:\n"
                "1:\n"
                : "+r"(s)
                : "r"(v));
        }
    }
    return s;
}

int main(void) {
    size_t n = 1 << 16;
    uint8_t *a = malloc(n);
    uint64_t x = 88172645463325252ULL;
    for (size_t i = 0; i < n; i++) {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        a[i] = (uint8_t)(x >> 32);
    }
    printf("%llu\n", (unsigned long long)work(a, n, 3000));
    return 0;
}
