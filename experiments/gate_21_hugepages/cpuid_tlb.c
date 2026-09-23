// この計測機の TLB の件数を CPU 自身に聞く (記録 #21 の記録ノートの出典)
//
//   gcc -O2 -o cpuid_tlb cpuid_tlb.c && ./cpuid_tlb
//
// cpuid 命令の leaf 0x2 が返す記述子を並べる. 記述子の意味は
// Intel 64 and IA-32 Architectures Software Developer's Manual, Vol. 2A の
// CPUID leaf 02H の記述子の表にある. 特権は要らない
#include <stdio.h>
#include <cpuid.h>

int main(void) {
    unsigned a, b, c, d;
    __cpuid(2, a, b, c, d);
    unsigned r[4] = {a, b, c, d};
    printf("leaf 0x2 の記述子:");
    for (int i = 0; i < 4; i++) {
        if (r[i] & 0x80000000u) continue;          // bit31 が立っていればそのレジスタは無効
        for (int k = (i == 0 ? 1 : 0); k < 4; k++) { // EAX の最下位バイトは呼ぶ回数
            unsigned char v = (r[i] >> (8 * k)) & 0xff;
            if (v) printf(" %02X", v);
        }
    }
    printf("\n");
    return 0;
}
