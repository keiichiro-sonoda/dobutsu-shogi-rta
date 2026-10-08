// 生成器だけを, キャッシュに乗る小さい集合の局面で回す (実験 perf_34。記録試行ではない)
//
//   bench <bench.so> <fwd|unmove> <ブロック> <局面の列.bin> ...
//
// bench.so は glue.c (impl/34_unmove/animal_shogi.c を取り込んで benchFwd / benchUnmove を足したもの) を
// impl/34_unmove の Makefile の gcc 行でビルドしたもの (build_bench.sh). dlopen して関数ポインタで呼ぶ
// (本番の CDLL と同じ RTLD_LOCAL. experiments/gen_bench と同じ条件). 中身は glue.c の注記.
//
// ファイルごとに, 入力をブロック (4,096 局面 = 32 KiB なら L1 に乗る) に分け, ブロックごとに1周温めてから
// 1周測る. 温めた周で入力と生成器の表はキャッシュに乗る. 測るのは呼び出しの周だけ (clock_gettime をブロックの前後に).
// 出力 (ファイルごとに1行): ファイル名, 局面数, 秒, ns/局面, 1局面あたりの後続 (候補) の数, 検算の和
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef unsigned long u_long;
typedef u_long (*bench_fn)(const u_long *, size_t, uint64_t *);

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static int one(bench_fn fn, const char *path, size_t block, const char *mode) {
    FILE *f = fopen(path, "rb");
    if (!f) return 2;
    fseek(f, 0, SEEK_END);
    size_t n = (size_t)ftell(f) / 8;
    fseek(f, 0, SEEK_SET);
    u_long *in = malloc((n ? n : 1) * 8);
    if (!in || fread(in, 8, n, f) != n) return 2;
    fclose(f);
    uint64_t sum = 0, outs = 0;
    double t = 0;
    for (size_t b0 = 0; b0 < n; b0 += block) {
        size_t b1 = b0 + block < n ? b0 + block : n;
        for (int pass = 0; pass < 2; pass++) {
            uint64_t o = 0;
            double t0 = now();
            u_long s = fn(in + b0, b1 - b0, &o);
            double t1 = now();
            if (pass == 1) {
                t += t1 - t0;
                sum += s;
                outs += o;
            }
        }
    }
    const char *base = strrchr(path, '/');
    printf("%s\t%s\t%zu\t%.6f\t%.2f\t%.4f\t%016llx\n", mode, base ? base + 1 : path, n, t,
           n ? t * 1e9 / (double)n : 0.0, n ? (double)outs / (double)n : 0.0, (unsigned long long)sum);
    free(in);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: bench <so> <fwd|unmove> <block> <in.bin> ...\n");
        return 2;
    }
    int fwd = strcmp(argv[2], "fwd") == 0;
    if (!fwd && strcmp(argv[2], "unmove") != 0) return 2;
    size_t block = (size_t)strtoul(argv[3], NULL, 10);
    if (!block) return 2;
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return 2;
    }
    bench_fn fn = (bench_fn)dlsym(h, fwd ? "benchFwd" : "benchUnmove");
    if (!fn) return 2;
    for (int i = 4; i < argc; i++)
        if (one(fn, argv[i], block, argv[2]) != 0) return 2;
    return 0;
}
