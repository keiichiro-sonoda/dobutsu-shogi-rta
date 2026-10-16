// 一致の検査 (実験 bitboard_gen。記録試行ではない)
//
//   verify <base の animal_shogi.so> <腕の animal_shogi.so> <局面の .bin> ...
//
// 2つの .so を dlopen (RTLD_LOCAL) し, どちらも prepInit() を呼んで利きの表 (キャッチ抜きの数の判定に使う) を作る.
// 局面ごとに nextBoardInvNormalNC を両方で呼び, 次の3つが同じかを見る:
//   (a) 戻り値 (0 キャッチ / -1 トライ負け / 正 後続の数)
//   (b) 戻り値が正のとき, 後続の列 (並びまで)
//   (c) *non_catch (戻り値が 0 と -1 のときに 0 のままであることも含む)
// 外れた局面は最初の 20 個まで, 局面と食い違いを出す. 終了コードは 0 一致 / 1 不一致 / 2 準備の失敗
// 最後の行に, 局面の数・種類ごとの数・不一致の数.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long u_long;
typedef int (*gen_fn)(u_long, u_long *, int *);
typedef int (*init_fn)(void);

static gen_fn open_gen(const char *path) {
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen %s: %s\n", path, dlerror());
        return NULL;
    }
    init_fn init = (init_fn)dlsym(h, "prepInit");
    gen_fn gen = (gen_fn)dlsym(h, "nextBoardInvNormalNC");
    if (!init || !gen || init() != 0) {
        fprintf(stderr, "%s: prepInit か nextBoardInvNormalNC が使えない\n", path);
        return NULL;
    }
    return gen;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: verify <base.so> <arm.so> <in.bin> ...\n");
        return 2;
    }
    gen_fn g0 = open_gen(argv[1]), g1 = open_gen(argv[2]);
    if (!g0 || !g1) return 2;
    u_long n = 0, n_catch = 0, n_try = 0, n_uk = 0, bad = 0;
    u_long a[64], c[64];
    u_long *buf = malloc((size_t)8 << 20);
    if (!buf) return 2;
    for (int f = 3; f < argc; f++) {
        FILE *fp = fopen(argv[f], "rb");
        if (!fp) {
            fprintf(stderr, "開けない: %s\n", argv[f]);
            return 2;
        }
        size_t m;
        while ((m = fread(buf, 8, (size_t)1 << 20, fp)) > 0) {
            for (size_t i = 0; i < m; i++) {
                int nc0 = -7, nc1 = -7;
                int r0 = g0(buf[i], a, &nc0);
                int r1 = g1(buf[i], c, &nc1);
                n++;
                if (r0 == 0) n_catch++;
                else if (r0 < 0) n_try++;
                else n_uk++;
                int ok = r0 == r1 && nc0 == nc1;
                if (ok && r0 > 0) ok = memcmp(a, c, (size_t)r0 * sizeof(u_long)) == 0;
                if (!ok) {
                    if (bad < 20) {
                        printf("不一致 %016lx: 戻り値 %d / %d, non_catch %d / %d", buf[i], r0, r1, nc0, nc1);
                        if (r0 > 0 && r0 == r1)
                            for (int k = 0; k < r0; k++)
                                if (a[k] != c[k]) {
                                    printf(", 後続 %d 番目 %016lx / %016lx", k, a[k], c[k]);
                                    break;
                                }
                        printf("\n");
                    }
                    bad++;
                }
            }
        }
        fclose(fp);
    }
    printf("局面 %lu (キャッチ %lu / トライ負け %lu / 未知 %lu) / 不一致 %lu\n", n, n_catch, n_try, n_uk, bad);
    return bad ? 1 : 0;
}
