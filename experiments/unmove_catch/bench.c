// unmove_catch の本体 (記録試行ではない)
//
//   bench prep    <catch.so> <dat/> <出力先>              cls.bin と計時用の抜き出し (unmove_bench と同じ作り方・同じシード)
//   bench count   <catch.so> <dat/> <出力先>              全未知局面で B1 と B2 のキャッチ抜きの数を突き合わせる
//   bench retreat <catch.so> <dat/> <出力先> <版> <ラベル>  試作の後退解析を1本回し, 全局面で dat/ と比べる
//   bench time    <catch.so> <出力先> <版> <周>           抜き出した局面で B の版を1つ計時する (種類ごとに1行の TSV)
//
// 版 (retreat): keep = 外さない (残りの数は重複込みの出次数. キャッチ局面からも前任をたどる)
//              drop = 外す (残りの数はキャッチ抜き. キャッチ局面からはたどらない. 0 の局面は最初に手数 2 の負け)
// 版 (time):    gen (いまの前向きの生成器) / b1 (後続を作るその場でキャッチを見分ける) / b2 (生成器 ＋ cls で数え直す)
//
// .so は本番と同じ gcc 行でビルドしたもの (build_so.sh). dlopen して関数ポインタで呼ぶ (gen_bench・unmove_bench と同じ).
// 局面の種類は, いまの生成器の戻り値で決める (0 = キャッチ, -1 = トライ負け, 正 = 未知). ファイル名では決めない.
// 正解の (勝敗, 手数) は dat/ のファイル名で決める: win<手数>te_* / lose<手数>te_* / unknown* (引き分け = 255).

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

typedef struct {
    uint64_t expanded, candidates, kept, drop[4], found;
} CatchStepStats;

static int (*f_next)(u_long, u_long *);
static u_long (*f_range)(void);
static u_long (*f_rank_board)(u_long);
static u_long (*f_rank)(u_long);
static int (*f_b1)(u_long, u_long *, int *);
static int (*f_b2)(u_long, const uint8_t *, int *);
static int (*f_step)(const u_long *, size_t, int, uint8_t, const uint8_t *, uint8_t *, uint8_t *, u_long *, size_t,
                     CatchStepStats *);

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
    f_step = sym(h, "catchStep");
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

// ---- count: B1 と B2 の突き合わせ, キャッチ抜きの数が 0 の局面 -------------------------------------
static int count(const char *dat, const char *out) {
    uint8_t *lab;
    u_long *all = load_dat(dat, &lab);
    uint8_t *cls = load_cls(out);
    size_t unknown = 0, bad_b1 = 0, bad_list = 0, zero = 0, shown = 0;
    size_t zero_dtm[256] = {0}, hist[49] = {0};
    uint64_t succ = 0, non_catch = 0;
    for (size_t i = 0; i < N_ALL; i++) {
        u_long a[64], b[64];
        int n1, n2, ret_b1, ret_gen, ret_b2;
        if (cls[f_rank(all[i])] != T_UNKNOWN) continue;
        unknown++;
        ret_gen = f_next(all[i], a);
        ret_b1 = f_b1(all[i], b, &n1);
        ret_b2 = f_b2(all[i], cls, &n2);
        // B1 は, いまの生成器と同じ後続を同じ順で作ること (足したのは数えるところだけ)
        if (ret_b1 != ret_gen || ret_b2 != ret_gen || memcmp(a, b, (size_t)ret_gen * sizeof(u_long))) bad_list++;
        if (n1 != n2) {
            bad_b1++;
            if (shown++ < 20) printf("食い違い: p=%#lx B1 %d / B2 %d (後続 %d)\n", all[i], n1, n2, ret_gen);
        }
        succ += (uint64_t)ret_gen;
        non_catch += (uint64_t)n2;
        hist[n2 < 48 ? n2 : 48]++;
        if (n2 == 0) {
            zero++;
            zero_dtm[lab[i]]++;
        }
    }
    printf("未知局面 %zu / 後続 (重複込み) %lu / うちキャッチ局面でない後続 %lu / キャッチ局面への手 %lu\n", unknown, succ,
           non_catch, succ - non_catch);
    printf("キャッチ抜きの数が 0 の未知局面: %zu\n", zero);
    printf("その正解の手数 (dat/ のファイル名):");
    for (int d = 0; d < 256; d++)
        if (zero_dtm[d] && d == DRAW) printf(" 引き分け=%zu", zero_dtm[d]);
        else if (zero_dtm[d]) printf(" %d=%zu", d, zero_dtm[d]);
    printf("\nキャッチ抜きの数の分布 (0〜47, 48 以上):");
    for (int k = 0; k <= 48; k++) printf(" %zu", hist[k]);
    printf("\n後続の列が, いまの生成器と違った局面 (B1 / B2 の戻り値と後続): %zu\n", bad_list);
    printf("B1 の数え: %zu 局面のうち, B2 と食い違い %zu 局面 => %s\n", unknown, bad_b1,
           bad_b1 || bad_list ? "FAIL" : "PASS");
    return bad_b1 || bad_list ? 1 : 0;
}

// ---- retreat: 試作の後退解析を1本回し, dat/ と比べる -----------------------------------------------
static int retreat(const char *dat, const char *out, const char *ver, const char *label) {
    int drop_catch;
    if (!strcmp(ver, "keep")) drop_catch = 0;
    else if (!strcmp(ver, "drop")) drop_catch = 1;
    else die("版は keep / drop");
    uint8_t *lab;
    u_long *all = load_dat(dat, &lab);
    uint8_t *cls = load_cls(out);
    u_long range = f_range();
    uint8_t *dtm = huge_alloc(range), *cnt = huge_alloc(range);
    memset(dtm, DRAW, range);
    memset(cnt, 0, range);
    u_long *catches = malloc(N_CATCH * sizeof(u_long)), *tries = malloc(N_TRY * sizeof(u_long));
    u_long *zeros = malloc(N_UNKNOWN * sizeof(u_long));
    u_long *found = huge_alloc(N_ALL * sizeof(u_long));
    size_t nc = 0, nt = 0, nz = 0;
    // 初期化: キャッチ局面は手数 1 の勝ち, トライ負け局面は手数 0 の負け. 未知局面の残りの後続の数.
    // 外す版は, キャッチ抜きの数が 0 の未知局面を手数 2 の負けとして先に決める
    double t0 = now();
    for (size_t i = 0; i < N_ALL; i++) {
        u_long r = f_rank(all[i]);
        int t = cls[r];
        if (t == T_CATCH) {
            dtm[r] = 1;
            catches[nc++] = all[i];
        } else if (t == T_TRY) {
            dtm[r] = 0;
            tries[nt++] = all[i];
        } else if (t == T_UNKNOWN) {
            int k;
            if (drop_catch) {
                if (f_b2(all[i], cls, &k) <= 0) die("未知局面の戻り値が正でない");
                if (k == 0) {
                    dtm[r] = 2;
                    zeros[nz++] = all[i];
                }
            } else {
                u_long nbs[64];
                k = f_next(all[i], nbs);
                if (k <= 0) die("未知局面の戻り値が正でない");
            }
            cnt[r] = (uint8_t)k;
        } else {
            die("dat/ の局面のランクが cls で到達しない");
        }
    }
    double t_init = now() - t0;
    if (nc != N_CATCH || nt != N_TRY) die("キャッチ・トライ負けの数が合わない");
    printf("初期化: %.2f 秒 (キャッチ %zu / トライ負け %zu / キャッチ抜きの数が 0 で先に決めた %zu)\n", t_init, nc, nt, nz);

    // 手数ごとのループ. 手数 nd の段は, 手数 nd − 1 で決まった局面 (フロンティア) から前任をたどる
    printf("nd\tfrontier\tcandidates\tkept\tfound\tsec\n");
    CatchStepStats tot;
    memset(&tot, 0, sizeof tot);
    const u_long *fr = tries;
    size_t fr_n = nt, pos = 0;
    double t_loop0 = now();
    int nd;
    for (nd = 1; nd < 255; nd++) {
        CatchStepStats st;
        memset(&st, 0, sizeof st);
        double ts = now();
        size_t start = pos;
        int odd = (nd - 1) % 2;
        size_t front = fr_n;
        // 手数 2 の段: 外さない版はキャッチ局面 (手数 1 の勝ち) もフロンティアに入れる
        if (nd == 2 && !drop_catch) {
            int rc = f_step(catches, nc, odd, (uint8_t)nd, cls, dtm, cnt, found + pos, N_ALL - pos, &st);
            if (rc < 0) die("後退解析の1段を進められない");
            pos += (size_t)rc;
            front += nc;
        }
        int rc = f_step(fr, fr_n, odd, (uint8_t)nd, cls, dtm, cnt, found + pos, N_ALL - pos, &st);
        if (rc < 0) {
            fprintf(stderr, "rc=%d nd=%d\n", rc, nd);
            die("後退解析の1段を進められない");
        }
        pos += (size_t)rc;
        // 外す版: キャッチ抜きの数が 0 の局面 (先に手数 2 の負けに決めた) を, 手数 2 で決まった局面に足す
        if (nd == 2 && drop_catch) {
            if (pos + nz > N_ALL) die("found があふれた");
            memcpy(found + pos, zeros, nz * sizeof(u_long));
            pos += nz;
        }
        double sec = now() - ts;
        printf("%d\t%zu\t%lu\t%lu\t%zu\t%.3f\n", nd, front, st.candidates, st.kept, pos - start, sec);
        tot.expanded += st.expanded;
        tot.candidates += st.candidates;
        tot.kept += st.kept;
        for (int k = 0; k < 4; k++) tot.drop[k] += st.drop[k];
        if (pos == start) break;
        fr = found + start;
        fr_n = pos - start;
    }
    double t_loop = now() - t_loop0;

    // 全局面で, (勝敗, 手数) を dat/ のファイル名と比べる
    size_t bad = 0, shown = 0, by[3][3] = {{0}};
    for (size_t i = 0; i < N_ALL; i++) {
        int got = dtm[f_rank(all[i])], want = lab[i];
        if (got == want) continue;
        bad++;
        int gw = got == DRAW ? 2 : got % 2, ww = want == DRAW ? 2 : want % 2;
        by[ww][gw]++;
        if (shown++ < 20) printf("食い違い: p=%#lx 正解 %d / 試作 %d\n", all[i], want, got);
    }
    const char *wl[3] = {"負け", "勝ち", "引き分け"};
    if (bad) {
        printf("食い違いの内訳 (正解 → 試作):");
        for (int a = 0; a < 3; a++)
            for (int b = 0; b < 3; b++)
                if (by[a][b]) printf(" %s→%s %zu", wl[a], wl[b], by[a][b]);
        printf("\n");
    }
    printf("一致の検査 (%s): %lu 局面のうち, 食い違い %zu 局面 => %s\n", ver, N_ALL, bad, bad ? "FAIL" : "PASS");
    printf("version\tlabel\tinit_sec\tloop_sec\tsteps\texpanded\tcandidates\tkept\tdrop_none\tdrop_catch\tdrop_try\t"
           "zero_first\tmismatch\n");
    printf("RESULT\t%s\t%s\t%.3f\t%.3f\t%d\t%lu\t%lu\t%lu\t%lu\t%lu\t%lu\t%zu\t%zu\n", ver, label, t_init, t_loop, nd,
           tot.expanded, tot.candidates, tot.kept, tot.drop[0], tot.drop[2], tot.drop[3], nz, bad);
    return bad ? 1 : 0;
}

// ---- time: B1 / B2 の計時 (unmove_bench の timing と同じ形) ------------------------------------------
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
            } else if (!strcmp(ver, "b2")) {
                for (size_t i = 0; i < m; i++) {
                    f_b2(smp[i], cls, &k);
                    sum += (size_t)k;
                }
            } else {
                die("版は gen / b1 / b2");
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
    if (!strcmp(argv[1], "retreat") && argc == 7) return retreat(argv[3], argv[4], argv[5], argv[6]);
    if (!strcmp(argv[1], "time") && argc == 6) return timing(argv[3], argv[4], atoi(argv[5]));
    die("使い方は bench.c の先頭");
    return 2;
}
