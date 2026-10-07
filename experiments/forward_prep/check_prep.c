// 書いた配列 (prep.bin) が正しいかを確かめる (実験 forward_prep。記録試行ではない)
//
//   check_prep <impl/33 の animal_shogi.so> <cls.bin> <prep.bin> <dat/>
//
// cls.bin は unmove_catch〜unmove_flip と同じ作り方の「ランクを添字にした種類」(0 到達しない / 1 未知 / 2 キャッチ / 3 トライ負け).
// 正解は cls と, いまの生成器 (impl/33 の nextBoardInvNormal) で数え直したキャッチ抜きの数 (B2 と同じ数え方:
// 後続のランクで cls を引き, 2 でないものを数える). 見るもの:
//   1. 全ランクで, cls が 0 (到達しない) なら prep も 0
//   2. dat/ の全局面 p で, cls[p] が 2 なら prep[p] = 0xFF, 3 なら 0xFE, 1 なら prep[p] = キャッチ抜きの数 + 1
// 食い違いは種類ごとに数える
#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long u_long;

static void die(const char *m) {
    fprintf(stderr, "!!! %s\n", m);
    exit(2);
}

static void *slurp(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) die("ファイルが開けない");
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *p = malloc((size_t)sz ? (size_t)sz : 1);
    if (!p || fread(p, 1, (size_t)sz, f) != (size_t)sz) die("読めない");
    fclose(f);
    *n = (size_t)sz;
    return p;
}

int main(int argc, char **argv) {
    if (argc != 5) die("使い方は check_prep.c の先頭");
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) die(dlerror());
    int (*next)(u_long, u_long *) = (int (*)(u_long, u_long *))dlsym(h, "nextBoardInvNormal");
    u_long (*rank)(u_long) = (u_long(*)(u_long))dlsym(h, "rankBoard");
    u_long (*range)(void) = (u_long(*)(void))dlsym(h, "rankRange");
    if (!next || !rank || !range) die("関数が .so に無い");
    size_t nc, np;
    uint8_t *cls = slurp(argv[2], &nc), *prep = slurp(argv[3], &np);
    if (nc != range() || np != nc) die("cls.bin と prep.bin の大きさがランクの値域と違う");
    size_t bad_none = 0, bad_catch = 0, bad_try = 0, bad_unknown = 0, zero = 0, shown = 0;
    size_t by[4] = {0};
    for (size_t r = 0; r < nc; r++)
        if (cls[r] == 0 && prep[r] != 0) bad_none++;
    DIR *d = opendir(argv[4]);
    struct dirent *e;
    if (!d) die("dat/ が開けない");
    u_long buf[1 << 16], nbs[64];
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char path[4096];
        snprintf(path, sizeof path, "%s/%s", argv[4], e->d_name);
        FILE *f = fopen(path, "rb");
        if (!f) die("dat/ のファイルが開けない");
        size_t got;
        while ((got = fread(buf, sizeof(u_long), 1 << 16, f)) > 0) {
            for (size_t i = 0; i < got; i++) {
                u_long p = buf[i], r = rank(p);
                int t = cls[r], v = prep[r];
                by[t]++;
                if (t == 2) {
                    if (v != 0xFF) bad_catch++;
                } else if (t == 3) {
                    if (v != 0xFE) bad_try++;
                } else if (t == 1) {
                    int n = next(p, nbs), k = 0;
                    for (int j = 0; j < n; j++) k += cls[rank(nbs[j])] != 2;
                    zero += k == 0;
                    if (v != k + 1) {
                        bad_unknown++;
                        if (shown++ < 20) printf("食い違い: p=%#lx 正解 %d / 配列 %d\n", p, k + 1, v);
                    }
                } else {
                    die("dat/ の局面が cls で到達しない");
                }
            }
        }
        fclose(f);
    }
    closedir(d);
    printf("dat/ の局面: 未知 %zu / キャッチ %zu / トライ負け %zu\n", by[1], by[2], by[3]);
    printf("未知局面のうち, キャッチ抜きの数が 0 の局面: %zu\n", zero);
    printf("食い違い: 到達しないランク %zu / キャッチ局面 %zu / トライ負け局面 %zu / 未知局面 %zu\n", bad_none, bad_catch,
           bad_try, bad_unknown);
    int pass = !bad_none && !bad_catch && !bad_try && !bad_unknown;
    printf("配列の検査: %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}
