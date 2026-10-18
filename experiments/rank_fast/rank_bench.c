// rankOf だけを, 本物の入力で回すベンチ (実験 rank_fast。記録試行ではない)
//
//   rank_bench <bench.so> <fwd|unmove> <none|thr|chain|small> <呼び出しの数> <局面の列.bin> ...
//
// bench.so は rank_glue.c (腕の animal_shogi.c を取り込んだもの) を impl/38_precheck の Makefile の gcc 行で
// ビルドしたもの (build_bench.sh). dlopen して関数ポインタで呼ぶ (本番の CDLL と同じ RTLD_LOCAL).
// 入力の局面の列を全部読み, fwd なら後続, unmove なら前任の候補を作って1つの列に並べる (並びは本物のまま).
// その列の番号を, 呼び出しの数に届くまで何周も出す:
//   none   列を作るだけで番号は出さない (固定の分. ほかの回し方から引く)
//   thr    列の全部を続けて回す (呼び出しどうしは独立)
//   chain  列の全部を鎖にして回す (前の番号を次の盤に混ぜる. rank_glue.c の rbChain)
//   small  列の真ん中の 64 個だけを続けて回す (表の欄が L1 に残る)
// 出力 (1行): 入力, 回し方, 局面数, 列の長さ, 回した集合の大きさ, 周の数, 呼び出しの数, 検算の和
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long u_long;
typedef int (*one_fn)(u_long, u_long *);
typedef int (*max_fn)(void);
typedef u_long (*thr_fn)(const u_long *, size_t, size_t);
typedef u_long (*chain_fn)(const u_long *, size_t, size_t, u_long);

#define SMALL 64

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: rank_bench <so> <fwd|unmove> <none|thr|chain|small> <calls> <in.bin> ...\n");
        return 2;
    }
    int fwd = strcmp(argv[2], "fwd") == 0;
    if (!fwd && strcmp(argv[2], "unmove") != 0) return 2;
    const char *mode = argv[3];
    if (strcmp(mode, "none") && strcmp(mode, "thr") && strcmp(mode, "chain") && strcmp(mode, "small")) return 2;
    size_t calls = (size_t)strtoull(argv[4], NULL, 10);
    // 鎖の mask. 0 だが, コンパイラに分からないように引数の数から作る (argc は 6 以上)
    u_long mask = (u_long)(argc < 6);
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return 2;
    }
    one_fn one = (one_fn)dlsym(h, fwd ? "rbFwdOne" : "rbUnmoveOne");
    max_fn mx = (max_fn)dlsym(h, fwd ? "rbMaxFwd" : "rbMaxUnmove");
    thr_fn thr = (thr_fn)dlsym(h, "rbThr");
    chain_fn chain = (chain_fn)dlsym(h, "rbChain");
    if (!one || !mx || !thr || !chain) return 2;
    size_t cap = 1 << 20, m = 0, npos = 0;
    int kmax = mx();
    u_long *x = malloc(cap * 8), *buf = malloc((size_t)kmax * 8);
    if (!x || !buf) return 2;
    for (int a = 5; a < argc; a++) {
        FILE *f = fopen(argv[a], "rb");
        if (!f) return 2;
        u_long b;
        while (fread(&b, 8, 1, f) == 1) {
            int k = one(b, buf);
            npos++;
            if (k <= 0) continue;
            if (m + (size_t)k > cap) {
                cap *= 2;
                x = realloc(x, cap * 8);
                if (!x) return 2;
            }
            memcpy(x + m, buf, (size_t)k * 8);
            m += (size_t)k;
        }
        fclose(f);
    }
    if (m < SMALL) return 2;
    const u_long *set = x;
    size_t n = m;
    if (strcmp(mode, "small") == 0) {
        set = x + (m - SMALL) / 2;
        n = SMALL;
    }
    size_t reps = strcmp(mode, "none") == 0 ? 0 : (calls + n - 1) / n;
    u_long s = strcmp(mode, "chain") == 0 ? chain(set, n, reps, mask) : thr(set, n, reps);
    printf("%s\t%s\t%zu\t%zu\t%zu\t%zu\t%zu\t%016lx\n", argv[2], mode, npos, m, n, reps, n * reps, s);
    free(x);
    free(buf);
    return 0;
}
