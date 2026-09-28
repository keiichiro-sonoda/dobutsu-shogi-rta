// 指し手生成器だけを取り出して測る (実験 gen_bench。記録試行ではない)
//
// 生成器は, 本番と同じビルド (gcc -O2 ... -fPIC -shared) の .so を dlopen して呼ぶ.
// .c ごと1つの実行ファイルにすると, 同じ .so の中の呼び出し (normalBoard / invBoard) が
// インライン展開されるようになり, 本番より速く出る (記録 #18 で確かめた条件).
//
//   bench verify-inv <dat> <base.so> <cand.so>
//       全局面で invBoard の出力が1ビットも違わないことを見る
//   bench verify-gen <dat> <base.so> <cand.so> <cand の関数名>
//       全局面で, 戻り値が一致し, 正のときは後続の列が順番まで一致することを見る
//   bench sample <dat> <base.so> <出力先> <件数> <シード>
//       いまの生成器の戻り値で種類 (0=キャッチ / -1=トライ負け / 正=未知) を決め,
//       種類の比率が全体と同じになるように固定シードで抜き出す.
//       catch.bin / try.bin / unknown.bin と, 3つを混ぜて並べ替えた mixed.bin を書く
//   bench time-gen <so> <関数名> <抜き出し先> <ラベル>
//       種類ごとと mixed で, 生成器の呼び出しだけを計時して ns/局面 を TSV で出す
//   bench time-inv <so> <抜き出し先> <ラベル>
//       mixed で invBoard だけを計時する
//
// 計時は各入力を1周温めてから1周測る. 入力の読み込みと一致の検査は計時の外.
#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef unsigned long u_long;
typedef int (*gen_fn)(u_long, u_long *);
typedef u_long (*inv_fn)(u_long);

#define MAX_ACTION_NUM 48
// 本番の件数 (#25 本走の dat/). 読んだ数が違えば止める
#define N_ALL 246803167UL

enum { CATCH, TRY, UNKNOWN, N_KIND };
static const char *KIND_NAME[N_KIND] = {"catch", "try", "unknown"};

static void die(const char *msg) {
    fprintf(stderr, "bench: %s\n", msg);
    exit(2);
}

static void *open_so(const char *path, int deep) {
    // 検査は2つの .so を同時に開くので RTLD_DEEPBIND で自分の中の関数を優先させる.
    // 計時は1つだけ開く (本番の Python の CDLL と同じ RTLD_LOCAL)
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL | (deep ? RTLD_DEEPBIND : 0));
    if (!h) die(dlerror());
    return h;
}

static void *sym(void *h, const char *name) {
    void *f = dlsym(h, name);
    if (!f) die(dlerror());
    return f;
}

// dat/ の *.bin をファイル名の順に連結して読む (並びは結果に関係しない)
static int by_name(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static u_long *load_dat(const char *dir, size_t *n_out) {
    DIR *d = opendir(dir);
    struct dirent *e;
    char **names = NULL;
    size_t n_names = 0, cap = 0, n = 0;
    u_long *all;
    if (!d) die("dat/ を開けない");
    while ((e = readdir(d))) {
        size_t len = strlen(e->d_name);
        if (len < 5 || strcmp(e->d_name + len - 4, ".bin")) continue;
        if (n_names == cap) {
            cap = cap ? cap * 2 : 256;
            names = realloc(names, cap * sizeof *names);
        }
        names[n_names++] = strdup(e->d_name);
    }
    closedir(d);
    qsort(names, n_names, sizeof *names, by_name);
    all = malloc(N_ALL * sizeof *all);
    if (!all) die("確保できない");
    for (size_t i = 0; i < n_names; i++) {
        char path[4096];
        FILE *f;
        long sz;
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        f = fopen(path, "rb");
        if (!f) die("ファイルを開けない");
        fseek(f, 0, SEEK_END);
        sz = ftell(f);
        fseek(f, 0, SEEK_SET);
        if (sz % 8 || n + (size_t)sz / 8 > N_ALL) die("大きさが合わない");
        if (fread(all + n, 8, (size_t)sz / 8, f) != (size_t)sz / 8) die("読めない");
        n += (size_t)sz / 8;
        fclose(f);
        free(names[i]);
    }
    free(names);
    if (n != N_ALL) die("局面数が 246,803,167 でない");
    fprintf(stderr, "dat/: %zu ファイル, %zu 局面\n", n_names, n);
    *n_out = n;
    return all;
}

static int kind_of(int rc) {
    if (rc == 0) return CATCH;
    if (rc == -1) return TRY;
    if (rc > 0) return UNKNOWN;
    die("知らない戻り値");
    return -1;
}

static int verify_inv(const char *dat, const char *base_so, const char *cand_so) {
    size_t n;
    u_long *all = load_dat(dat, &n);
    inv_fn f0 = (inv_fn)sym(open_so(base_so, 1), "invBoard");
    inv_fn f1 = (inv_fn)sym(open_so(cand_so, 1), "invBoard");
    size_t bad = 0;
    for (size_t i = 0; i < n; i++) {
        u_long a = f0(all[i]), b = f1(all[i]);
        if (a != b) {
            if (bad < 5) printf("不一致\t0x%lx\t0x%lx\t0x%lx\n", all[i], a, b);
            bad++;
        }
    }
    printf("verify-inv\t%zu 局面\t不一致 %zu\n", n, bad);
    return bad ? 1 : 0;
}

static int verify_gen(const char *dat, const char *base_so, const char *cand_so, const char *name) {
    size_t n, count[N_KIND] = {0}, bad_rc = 0, bad_seq = 0;
    u_long *all = load_dat(dat, &n);
    gen_fn g0 = (gen_fn)sym(open_so(base_so, 1), "nextBoardInvNormal");
    gen_fn g1 = (gen_fn)sym(open_so(cand_so, 1), name);
    u_long nb0[MAX_ACTION_NUM], nb1[MAX_ACTION_NUM];
    for (size_t i = 0; i < n; i++) {
        int r0 = g0(all[i], nb0), r1 = g1(all[i], nb1);
        count[kind_of(r0)]++;
        if (r0 != r1) {
            if (bad_rc < 5) printf("戻り値の不一致\t0x%lx\t%d\t%d\n", all[i], r0, r1);
            bad_rc++;
        } else if (r0 > 0 && memcmp(nb0, nb1, (size_t)r0 * sizeof *nb0)) {
            if (bad_seq < 5) printf("後続の不一致\t0x%lx\t%d\n", all[i], r0);
            bad_seq++;
        }
    }
    printf("verify-gen\t%s\t%zu 局面 (キャッチ %zu / トライ負け %zu / 未知 %zu)\t"
           "戻り値の不一致 %zu\t後続の不一致 %zu\n",
           name, n, count[CATCH], count[TRY], count[UNKNOWN], bad_rc, bad_seq);
    return (bad_rc || bad_seq) ? 1 : 0;
}

// splitmix64 (固定シードで再現できる乱数)
static u_long rng_state;
static u_long rng(void) {
    u_long z = (rng_state += 0x9e3779b97f4a7c15UL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9UL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebUL;
    return z ^ (z >> 31);
}

// 先頭 k 個を一様に選んで並べ替える (Fisher-Yates を k 手で止める)
static void pick(u_long *a, size_t n, size_t k) {
    for (size_t i = 0; i < k; i++) {
        size_t j = i + (size_t)(rng() % (n - i));
        u_long t = a[i];
        a[i] = a[j];
        a[j] = t;
    }
}

static void write_bin(const char *dir, const char *name, const u_long *a, size_t n) {
    char path[4096];
    FILE *f;
    snprintf(path, sizeof path, "%s/%s", dir, name);
    f = fopen(path, "wb");
    if (!f || fwrite(a, 8, n, f) != n) die("書けない");
    fclose(f);
}

static int sample(const char *dat, const char *base_so, const char *out, size_t k_total, u_long seed) {
    size_t n, count[N_KIND] = {0}, pos[N_KIND] = {0}, k[N_KIND], k_sum = 0;
    u_long *all = load_dat(dat, &n);
    gen_fn g0 = (gen_fn)sym(open_so(base_so, 0), "nextBoardInvNormal");
    u_long nb[MAX_ACTION_NUM];
    unsigned char *kind = malloc(n);
    u_long *by_kind[N_KIND], *mixed;
    for (size_t i = 0; i < n; i++) {
        kind[i] = (unsigned char)kind_of(g0(all[i], nb));
        count[kind[i]]++;
    }
    for (int c = 0; c < N_KIND; c++) {
        // 種類ごとの件数は全体の比率に合わせて丸める
        k[c] = (size_t)((double)k_total * (double)count[c] / (double)n + 0.5);
        by_kind[c] = malloc(count[c] * sizeof(u_long));
        k_sum += k[c];
    }
    for (size_t i = 0; i < n; i++) by_kind[kind[i]][pos[kind[i]]++] = all[i];
    rng_state = seed;
    mixed = malloc(k_sum * sizeof *mixed);
    k_sum = 0;
    for (int c = 0; c < N_KIND; c++) {
        char name[64];
        pick(by_kind[c], count[c], k[c]);
        snprintf(name, sizeof name, "%s.bin", KIND_NAME[c]);
        write_bin(out, name, by_kind[c], k[c]);
        memcpy(mixed + k_sum, by_kind[c], k[c] * sizeof *mixed);
        k_sum += k[c];
    }
    pick(mixed, k_sum, k_sum);  // 3種類を混ぜて並べ替える
    write_bin(out, "mixed.bin", mixed, k_sum);
    printf("sample\tseed %lu\t全体 キャッチ %zu / トライ負け %zu / 未知 %zu\t"
           "抜き出し キャッチ %zu / トライ負け %zu / 未知 %zu (計 %zu)\n",
           seed, count[CATCH], count[TRY], count[UNKNOWN], k[CATCH], k[TRY], k[UNKNOWN], k_sum);
    return 0;
}

static u_long *load_bin(const char *dir, const char *name, size_t *n_out) {
    char path[4096];
    FILE *f;
    long sz;
    u_long *a;
    snprintf(path, sizeof path, "%s/%s", dir, name);
    f = fopen(path, "rb");
    if (!f) die("抜き出した局面を開けない");
    fseek(f, 0, SEEK_END);
    sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    a = malloc((size_t)sz);
    if (!a || fread(a, 1, (size_t)sz, f) != (size_t)sz) die("読めない");
    fclose(f);
    *n_out = (size_t)sz / 8;
    return a;
}

static double now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
}

// 結果を捨てられないように, 戻り値と後続の先頭を足し込む
static volatile u_long g_sink;

static double run_gen(gen_fn g, const u_long *a, size_t n) {
    u_long nb[MAX_ACTION_NUM], acc = 0;
    double t0 = now_ns();
    for (size_t i = 0; i < n; i++) {
        int r = g(a[i], nb);
        acc += (u_long)r + (r > 0 ? nb[0] : 0);
    }
    double t1 = now_ns();
    g_sink += acc;
    return t1 - t0;
}

static int time_gen(const char *so, const char *name, const char *dir, const char *label) {
    gen_fn g = (gen_fn)sym(open_so(so, 0), name);
    const char *files[4] = {"catch.bin", "try.bin", "unknown.bin", "mixed.bin"};
    const char *kinds[4] = {"catch", "try", "unknown", "mixed"};
    for (int c = 0; c < 4; c++) {
        size_t n;
        u_long *a = load_bin(dir, files[c], &n);
        run_gen(g, a, n);  // 温める
        double ns = run_gen(g, a, n);
        printf("%s\tgen\t%s\t%s\t%zu\t%.0f\t%.3f\n", label, name, kinds[c], n, ns, ns / (double)n);
        fflush(stdout);
        free(a);
    }
    return 0;
}

static int time_inv(const char *so, const char *dir, const char *label) {
    inv_fn f = (inv_fn)sym(open_so(so, 0), "invBoard");
    size_t n;
    u_long *a = load_bin(dir, "mixed.bin", &n), acc = 0;
    for (size_t i = 0; i < n; i++) acc += f(a[i]);  // 温める
    double t0 = now_ns();
    for (size_t i = 0; i < n; i++) acc += f(a[i]);
    double ns = now_ns() - t0;
    g_sink += acc;
    printf("%s\tinv\tinvBoard\tmixed\t%zu\t%.0f\t%.3f\n", label, n, ns, ns / (double)n);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 5 && !strcmp(argv[1], "verify-inv")) return verify_inv(argv[2], argv[3], argv[4]);
    if (argc == 6 && !strcmp(argv[1], "verify-gen"))
        return verify_gen(argv[2], argv[3], argv[4], argv[5]);
    if (argc == 7 && !strcmp(argv[1], "sample"))
        return sample(argv[2], argv[3], argv[4], strtoul(argv[5], NULL, 10), strtoul(argv[6], NULL, 10));
    if (argc == 6 && !strcmp(argv[1], "time-gen")) return time_gen(argv[2], argv[3], argv[4], argv[5]);
    if (argc == 5 && !strcmp(argv[1], "time-inv")) return time_inv(argv[2], argv[3], argv[4]);
    fprintf(stderr, "使い方は bench.c の冒頭を見ること\n");
    return 2;
}
