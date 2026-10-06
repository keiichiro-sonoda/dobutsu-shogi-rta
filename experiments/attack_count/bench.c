// attack_count の本体 (記録試行ではない). experiments/unmove_catch/bench.c を土台にした
//
//   bench prep  <attack.so> <dat/> <出力先>      cls.bin と計時用の抜き出し (unmove_catch・unmove_bench と同じ作り方・同じシード)
//   bench count <attack.so> <dat/> <出力先>      一致の検査: 全局面で B1′ の戻り値がいまの生成器と同じか,
//                                                 全未知局面で後続の列が順番まで同じで, キャッチ抜きの数が B2 と同じか
//   bench time  <attack.so> <出力先> <版> <周>   抜き出した局面で版を1つ計時する (種類ごとに1行の TSV)
//
// 版 (time): gen (いまの生成器) / b1 (unmove_catch の B1) / b1x (この実験の B1′. 相手の利きの一覧) / b2 (unmove_catch の B2)
//
// .so は本番と同じ gcc 行でビルドしたもの (build_so.sh). dlopen して関数ポインタで呼ぶ.
// 局面の種類は, いまの生成器の戻り値で決める (0 = キャッチ, -1 = トライ負け, 正 = 未知). ファイル名では決めない.

#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

typedef unsigned long u_long;

#define N_ALL 246803167UL
#define N_UNKNOWN 99485568UL
#define N_CATCH 140298614UL
#define N_TRY 7018985UL
#define SAMPLE_N 10000000UL
#define SEED 20261005UL
#define HUGE_ALIGN ((size_t)1 << 21)
#define DRAW 255

enum { T_NONE = 0, T_UNKNOWN = 1, T_CATCH = 2, T_TRY = 3 };
static const char *TYPE_NAME[4] = {"none", "unknown", "catch", "try"};

static int (*f_next)(u_long, u_long *);
static u_long (*f_range)(void);
static u_long (*f_rank_board)(u_long);
static u_long (*f_rank)(u_long);
static int (*f_b1)(u_long, u_long *, int *);
static int (*f_b2)(u_long, const uint8_t *, int *);
static int (*f_x)(u_long, u_long *, int *);
static int (*f_xflags)(u_long, u_long *, int *, uint8_t *, uint8_t *);

static void die(const char *msg) {
    fprintf(stderr, "!!! %s\n", msg);
    exit(1);
}

static void *sym(void *h, const char *name) {
    void *p = dlsym(h, name);
    if (!p) {
        fprintf(stderr, "!!! %s が .so に無い\n", name);
        exit(1);
    }
    return p;
}

static void load_so(const char *path) {
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) die(dlerror());
    f_next = sym(h, "nextBoardInvNormal");
    f_range = sym(h, "rankRange");
    f_rank_board = sym(h, "rankBoard");
    f_rank = sym(h, "unmoveRank");
    f_b1 = sym(h, "nextBoardCountNonCatch");
    f_b2 = sym(h, "countNonCatchB2");
    f_x = sym(h, "nextBoardCountNonCatchX");
    f_xflags = sym(h, "nextBoardCatchFlagsX");
}

static void *huge_alloc(size_t bytes) {
    size_t sz = (bytes + HUGE_ALIGN - 1) & ~(HUGE_ALIGN - 1);
    void *p = aligned_alloc(HUGE_ALIGN, sz);
    if (!p) die("確保に失敗");
    madvise(p, sz, MADV_HUGEPAGE);
    return p;
}

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static uint64_t splitmix(uint64_t *s) {
    uint64_t z = (*s += 0x9e3779b97f4a7c15UL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9UL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebUL;
    return z ^ (z >> 31);
}

static int cmp_name(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

// ファイル名から正解の手数 (引き分けは DRAW)
static int label_of(const char *name) {
    int d;
    if (sscanf(name, "win%3dte_", &d) == 1 || sscanf(name, "lose%3dte_", &d) == 1) return d;
    if (!strncmp(name, "unknown", 7)) return DRAW;
    die("dat/ に知らない名前のファイルがある");
    return -1;
}

// dat/ の全ファイルを名前の順に読む. labels にはファイル名から決めた正解の手数
static u_long *load_dat(const char *dir, uint8_t **labels) {
    DIR *d = opendir(dir);
    struct dirent *e;
    char *names[512];
    int nn = 0;
    if (!d) die("dat/ が開けない");
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        if (nn == 512) die("ファイルが多すぎる");
        names[nn++] = strdup(e->d_name);
    }
    closedir(d);
    qsort(names, nn, sizeof names[0], cmp_name);
    u_long *all = huge_alloc(N_ALL * sizeof(u_long));
    uint8_t *lab = labels ? malloc(N_ALL) : NULL;
    size_t n = 0;
    for (int i = 0; i < nn; i++) {
        char path[4096];
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        FILE *f = fopen(path, "rb");
        if (!f) die("dat/ のファイルが開けない");
        int lb = label_of(names[i]);
        size_t got, n0 = n;
        while ((got = fread(all + n, sizeof(u_long), 1 << 20, f)) > 0) {
            n += got;
            if (n > N_ALL) die("局面が多すぎる");
        }
        fclose(f);
        if (lab) memset(lab + n0, lb, n - n0);
        free(names[i]);
    }
    printf("dat: %d ファイル / %zu 局面\n", nn, n);
    if (n != N_ALL) die("局面の数が 246,803,167 でない");
    if (labels) *labels = lab;
    return all;
}

static void write_file(const char *dir, const char *name, const void *p, size_t bytes) {
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "wb");
    if (!f || fwrite(p, 1, bytes, f) != bytes || fclose(f) != 0) die("書き出しに失敗");
}

static void *read_file(const char *dir, const char *name, size_t *bytes, int huge) {
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) die("読み込むファイルが無い (prep を先に)");
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *p = huge ? huge_alloc((size_t)sz) : malloc((size_t)sz);
    if (fread(p, 1, (size_t)sz, f) != (size_t)sz) die("読み込みに失敗");
    fclose(f);
    *bytes = (size_t)sz;
    return p;
}

static uint8_t *load_cls(const char *out) {
    size_t bytes;
    uint8_t *cls = read_file(out, "cls.bin", &bytes, 1);
    if (bytes != f_range()) die("cls.bin の大きさがランクの値域と違う");
    return cls;
}

// ---- prep (unmove_bench の prep と同じ作り方・同じシード) ------------------------------------------
static int prep(const char *dat, const char *out) {
    u_long *all = load_dat(dat, NULL);
    size_t n = N_ALL;
    u_long range = f_range();
    uint8_t *cls = huge_alloc(range);
    memset(cls, 0, range);
    size_t cnt[4] = {0, 0, 0, 0};
    uint8_t *type = malloc(n);
    for (size_t i = 0; i < n; i++) {
        u_long nbs[64];
        int r0 = f_next(all[i], nbs);
        int t = r0 == 0 ? T_CATCH : r0 < 0 ? T_TRY : T_UNKNOWN;
        u_long r = f_rank_board(all[i]);
        if (r >= range) die("ランクが出せない局面がある");
        if (cls[r]) die("ランクが重なった");
        cls[r] = (uint8_t)t;
        type[i] = (uint8_t)t;
        cnt[t]++;
    }
    printf("分類: 未知 %zu / キャッチ %zu / トライ負け %zu\n", cnt[1], cnt[2], cnt[3]);
    if (cnt[1] != N_UNKNOWN || cnt[2] != N_CATCH || cnt[3] != N_TRY) die("種類ごとの数が合わない");
    write_file(out, "cls.bin", cls, range);
    uint64_t s = SEED;
    size_t total = 0;
    u_long *mixed = malloc(SAMPLE_N * sizeof(u_long));
    for (int t = 1; t <= 3; t++) {
        size_t m = 0;
        uint32_t *idx = malloc(cnt[t] * sizeof(uint32_t));
        for (size_t i = 0; i < n; i++)
            if (type[i] == t) idx[m++] = (uint32_t)i;
        size_t k = (size_t)((double)SAMPLE_N * (double)cnt[t] / (double)n + 0.5);
        if (t == 3) k = SAMPLE_N - total;
        for (size_t i = 0; i < k; i++) {
            size_t j = i + splitmix(&s) % (m - i);
            uint32_t x = idx[i];
            idx[i] = idx[j];
            idx[j] = x;
        }
        u_long *smp = malloc(k * sizeof(u_long));
        for (size_t i = 0; i < k; i++) smp[i] = mixed[total + i] = all[idx[i]];
        char name[64];
        snprintf(name, sizeof name, "sample_%s.bin", TYPE_NAME[t]);
        write_file(out, name, smp, k * sizeof(u_long));
        printf("抜き出し %s: %zu 局面\n", TYPE_NAME[t], k);
        total += k;
        free(smp);
        free(idx);
    }
    for (size_t i = total - 1; i > 0; i--) {
        size_t j = splitmix(&s) % (i + 1);
        u_long x = mixed[i];
        mixed[i] = mixed[j];
        mixed[j] = x;
    }
    write_file(out, "sample_mixed.bin", mixed, total * sizeof(u_long));
    printf("抜き出し mixed: %zu 局面 (シード %lu)\n", total, SEED);
    return 0;
}

// ---- count: 一致の検査 -------------------------------------------------------------------------
// 正解は, 後続 q のランクで cls を引いて 2 (キャッチ局面) かどうか (unmove_catch の B2 と同じ数え方)
static const char *KIND_NAME[7] = {"ライオンの手", "ライオンで取る手", "ライオンが奥の段に入る手", "ほかの駒の手",
                                   "ほかの駒で取る手", "ひよこが成る手", "打つ手"};

static int count(const char *dat, const char *out) {
    u_long *all = load_dat(dat, NULL);
    uint8_t *cls = load_cls(out);
    size_t by_type[4] = {0}, bad_ret = 0, bad_list = 0, bad_nc = 0, shown = 0;
    uint64_t kind_n[7] = {0}, kind_catch[7] = {0}, kind_bad[7] = {0};
    for (size_t i = 0; i < N_ALL; i++) {
        u_long a[64], b[64];
        uint8_t fl[64], kd[64];
        int nx, nb2, ret_gen, ret_x, ret_b2;
        int t = cls[f_rank(all[i])];
        by_type[t]++;
        ret_gen = f_next(all[i], a);
        ret_x = f_xflags(all[i], b, &nx, fl, kd);
        if (ret_x != ret_gen) {
            bad_ret++;
            if (shown++ < 20) printf("戻り値の食い違い: p=%#lx いま %d / B1′ %d\n", all[i], ret_gen, ret_x);
            continue;
        }
        if (ret_gen <= 0) continue;
        if (memcmp(a, b, (size_t)ret_gen * sizeof(u_long))) bad_list++;
        ret_b2 = f_b2(all[i], cls, &nb2);
        if (ret_b2 != ret_gen) bad_list++;
        if (nx != nb2) bad_nc++;
        for (int j = 0; j < ret_gen; j++) {
            int truth = cls[f_rank(b[j])] == T_CATCH;
            kind_n[kd[j]]++;
            kind_catch[kd[j]] += (uint64_t)truth;
            if (fl[j] != truth) {
                kind_bad[kd[j]]++;
                if (shown++ < 20)
                    printf("判定の食い違い: p=%#lx 後続 %d (%s) 正解 %d / B1′ %d\n", all[i], j, KIND_NAME[kd[j]], truth,
                           fl[j]);
            }
        }
    }
    printf("局面: 未知 %zu / キャッチ %zu / トライ負け %zu\n", by_type[1], by_type[2], by_type[3]);
    printf("\n| 後続の手の種類 | 後続 | うちキャッチ局面 | 判定の食い違い |\n|---|---|---|---|\n");
    uint64_t sn = 0, sc = 0, sb = 0;
    for (int k = 0; k < 7; k++) {
        printf("| %s | %lu | %lu | %lu |\n", KIND_NAME[k], kind_n[k], kind_catch[k], kind_bad[k]);
        sn += kind_n[k];
        sc += kind_catch[k];
        sb += kind_bad[k];
    }
    printf("| 計 | %lu | %lu | %lu |\n", sn, sc, sb);
    printf("\n戻り値がいまの生成器と違った局面 (全局面): %zu\n", bad_ret);
    printf("後続の列がいまの生成器と違った局面 (未知局面): %zu\n", bad_list);
    int fail = bad_ret || bad_list || bad_nc || sb;
    printf("一致の検査: B1′ のキャッチ抜きの数が B2 と食い違った未知局面 %zu => %s\n", bad_nc, fail ? "FAIL" : "PASS");
    return fail ? 1 : 0;
}

// ---- time: 計時 (unmove_catch の timing と同じ形. 版に b1x を足した) ---------------------------------
static int timing(const char *out, const char *ver, int round) {
    const char *types[4] = {"unknown", "catch", "try", "mixed"};
    uint8_t *cls = NULL;
    if (!strcmp(ver, "b2")) cls = load_cls(out);
    for (int ti = 0; ti < 4; ti++) {
        char name[64];
        size_t bytes;
        snprintf(name, sizeof name, "sample_%s.bin", types[ti]);
        u_long *smp = read_file(out, name, &bytes, 0);
        size_t m = bytes / sizeof(u_long);
        double ns = 0;
        size_t total = 0;
        for (int pass = 0; pass < 2; pass++) {
            u_long buf[64];
            size_t sum = 0;
            int k;
            double t0 = now();
            if (!strcmp(ver, "gen")) {
                for (size_t i = 0; i < m; i++) {
                    int r = f_next(smp[i], buf);
                    sum += r > 0 ? (size_t)r : 0;
                }
            } else if (!strcmp(ver, "b1")) {
                for (size_t i = 0; i < m; i++) {
                    f_b1(smp[i], buf, &k);
                    sum += (size_t)k;
                }
            } else if (!strcmp(ver, "b1x")) {
                for (size_t i = 0; i < m; i++) {
                    f_x(smp[i], buf, &k);
                    sum += (size_t)k;
                }
            } else if (!strcmp(ver, "b2")) {
                for (size_t i = 0; i < m; i++) {
                    f_b2(smp[i], cls, &k);
                    sum += (size_t)k;
                }
            } else {
                die("版は gen / b1 / b1x / b2");
            }
            double dt = now() - t0;
            if (pass == 1) {
                ns = dt * 1e9 / (double)m;
                total = sum;
            }
        }
        printf("%s\t%d\t%s\t%zu\t%.2f\t%.4f\n", ver, round, types[ti], m, ns, (double)total / (double)m);
        fflush(stdout);
        free(smp);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) die("使い方は bench.c の先頭");
    load_so(argv[2]);
    f_range();
    if (!strcmp(argv[1], "prep") && argc == 5) return prep(argv[3], argv[4]);
    if (!strcmp(argv[1], "count") && argc == 5) return count(argv[3], argv[4]);
    if (!strcmp(argv[1], "time") && argc == 6) return timing(argv[3], argv[4], atoi(argv[5]));
    die("使い方は bench.c の先頭");
    return 2;
}
