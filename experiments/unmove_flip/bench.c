// unmove_flip の本体 (記録試行ではない). experiments/unmove_prune/bench.c を土台にした
//
//   bench prep    <flip.so> <dat/> <出力先>                         cls.bin と計時用の抜き出し (unmove_prune と同じ作り方・同じシード)
//   bench verify  <flip.so> <dat/> <出力先>                         一致の検査 (全到達局面. 反転を1回にした版を絞った版と比べる)
//   bench retreat <flip.so> <dat/> <出力先> <版> <ラベル> <書き出し先>  試作の後退解析 (unmove_prune の drop) を1本回し,
//                                                                    成果物の形へ書き出して時間を測り, 全局面で dat/ と比べる
//   bench time    <flip.so> <出力先> <版> <周>                      抜き出した局面で版を1つ計時する (種類ごとに1行の TSV)
//
// 版 (retreat): pruned (絞った版. unmove_prune の pruneStep そのもの) / flip (反転を1回にした版. flipStep)
// 版 (time):    pcand / psieve / pvisit (絞った版の 1〜3 段階. unmove_prune と同じ関数) /
//               fcand / fsieve / fvisit (反転を1回にした版の 1〜3 段階)
//
// .so は本番と同じ gcc 行でビルドしたもの (build_so.sh). dlopen して関数ポインタで呼ぶ.
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
#define UNMOVE_MAX 1024
#define HUGE_ALIGN ((size_t)1 << 21)
#define DRAW 255

enum { T_NONE = 0, T_UNKNOWN = 1, T_CATCH = 2, T_TRY = 3 };
static const char *TYPE_NAME[4] = {"none", "unknown", "catch", "try"};
static const char *KIND_NAME[5] = {"move", "capture", "drop", "promote", "promote_capture"};

typedef struct {
    uint64_t expanded, candidates, kept, drop[4], found;
} CatchStepStats;

typedef int (*StepFn)(const u_long *, size_t, int, uint8_t, const uint8_t *, uint8_t *, uint8_t *, u_long *, size_t,
                      CatchStepStats *);

static int (*f_next)(u_long, u_long *);
static u_long (*f_range)(void);
static u_long (*f_rank_board)(u_long);
static u_long (*f_rank)(u_long);
static int (*f_b2)(u_long, const uint8_t *, int *);
static int (*f_nsieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_pcand)(u_long, u_long *, uint8_t *);
static int (*f_psieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_pvisit)(u_long, const uint8_t *, uint8_t *);
static int (*f_fcand)(u_long, u_long *, uint8_t *);
static int (*f_fsieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_fvisit)(u_long, const uint8_t *, uint8_t *);
static int (*f_pcount)(u_long, u_long *, uint8_t *, uint8_t *, uint8_t *, int *);
static int (*f_fcount)(u_long, u_long *, uint8_t *, uint8_t *, uint8_t *, int *);
static StepFn f_pstep, f_fstep;

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
    f_b2 = sym(h, "countNonCatchB2");
    f_nsieved = sym(h, "unmoveSieved");
    f_pcand = sym(h, "unmovePrunedCandidates");
    f_psieved = sym(h, "unmovePrunedSieved");
    f_pvisit = sym(h, "unmovePrunedVisit");
    f_fcand = sym(h, "unmoveFlipCandidates");
    f_fsieved = sym(h, "unmoveFlipSieved");
    f_fvisit = sym(h, "unmoveFlipVisit");
    f_pcount = sym(h, "unmovePrunedCounted");
    f_fcount = sym(h, "unmoveFlipCounted");
    f_pstep = (StepFn)sym(h, "pruneStep");
    f_fstep = (StepFn)sym(h, "flipStep");
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

static uint64_t mix(uint64_t x) {
    uint64_t s = x;
    return splitmix(&s);
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

// ---- prep -------------------------------------------------------------------------------------------
// unmove_prune の prep の写し. cls.bin と sample_*.bin は unmove_prune と同じ中身になる (sha256 を logs/prep.txt に残す).
// cls.bin と sample_{unknown,catch,try,mixed}.bin は unmove_catch の prep と同じ作り方・同じシード (同じ中身になる).
// sample_expand.bin は, 試作の後退解析 (drop) で展開する種類 (未知とトライ負け) から 1,000万局面を,
// 同じシードから始めた別の乱数の列で抜き出したもの (重複なし. 並びは抜き出した順)
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
    // 展開する種類 (未知とトライ負け) から 1,000万
    {
        uint64_t s2 = SEED;
        size_t m = 0, nu = 0;
        uint32_t *idx = malloc((N_UNKNOWN + N_TRY) * sizeof(uint32_t));
        for (size_t i = 0; i < n; i++)
            if (type[i] == T_UNKNOWN || type[i] == T_TRY) idx[m++] = (uint32_t)i;
        for (size_t i = 0; i < SAMPLE_N; i++) {
            size_t j = i + splitmix(&s2) % (m - i);
            uint32_t x = idx[i];
            idx[i] = idx[j];
            idx[j] = x;
        }
        u_long *smp = malloc(SAMPLE_N * sizeof(u_long));
        for (size_t i = 0; i < SAMPLE_N; i++) {
            smp[i] = all[idx[i]];
            nu += type[idx[i]] == T_UNKNOWN;
        }
        write_file(out, "sample_expand.bin", smp, SAMPLE_N * sizeof(u_long));
        printf("抜き出し expand: %lu 局面 (未知 %zu / トライ負け %zu. シード %lu)\n", SAMPLE_N, nu, SAMPLE_N - nu, SEED);
        free(smp);
        free(idx);
    }
    return 0;
}

// ---- verify -----------------------------------------------------------------------------------------
// 全到達局面 q で, 反転を1回にした版を絞った版と比べる. 正解は「絞った版が作ったもの」そのもの (値で比べる).
//   (0) 写しの確かめ: 絞った版を数えながら作る写し (unmovePrunedCounted) の候補の列が unmovePrunedCandidates と順番まで同じ.
//       反転を1回にした版の数える口 (unmoveFlipCounted) の候補の列が unmoveFlipCandidates と順番まで同じ
//   (a) 候補の多重集合が同じ (件数とハッシュ2つ). 戻した手の種類 × A の大きさ × nb が q か鏡像か の区分ごとにも比べる
//   (b) 前任の多重集合が同じ (unmoveFlipSieved と unmovePrunedSieved と unmoveSieved (素朴な版))
//   (c) 正規形でないとして捨てた候補の数, 到達しない (cls が 0) として捨てる候補の数が同じ
typedef struct {
    uint32_t n;
    uint64_t sum, x;
} Agg;

#define XKEY 0x5bd1e9955bd1e995UL
#define NCAT 20  // 戻した手の種類 5 × A の大きさ 2 × q か鏡像か 2

static Agg agg_of(const u_long *p, int n) {
    Agg a = {0, 0, 0};
    for (int j = 0; j < n; j++) {
        a.n++;
        a.sum += mix(p[j]);
        a.x ^= mix(p[j] ^ XKEY);
    }
    return a;
}

static int agg_eq(Agg a, Agg b) {
    return a.n == b.n && a.sum == b.sum && a.x == b.x;
}

static void agg_cat(const u_long *p, const uint8_t *k, const uint8_t *a, const uint8_t *s, int n, Agg *c) {
    memset(c, 0, NCAT * sizeof(Agg));
    for (int j = 0; j < n; j++) {
        Agg *g = &c[k[j] * 4 + (a[j] ? 2 : 0) + s[j]];
        g->n++;
        g->sum += mix(p[j]);
        g->x ^= mix(p[j] ^ XKEY);
    }
}

static int verify(const char *dat, const char *out) {
    u_long *all = load_dat(dat, NULL);
    uint8_t *cls = load_cls(out);
    size_t bad_copy = 0, bad_cand = 0, bad_pred = 0, bad_nonnormal = 0, bad_none = 0, shown = 0;
    size_t bad_cat[NCAT] = {0};
    uint64_t cand = 0, kept = 0, nonnormal = 0, none = 0;
    double t0 = now();
    for (size_t i = 0; i < N_ALL; i++) {
        u_long q = all[i];
        u_long pc[UNMOVE_MAX], fc[UNMOVE_MAX], p2[UNMOVE_MAX], f2[UNMOVE_MAX], ks[UNMOVE_MAX];
        uint8_t pk[UNMOVE_MAX], pa[UNMOVE_MAX], ps[UNMOVE_MAX], fk[UNMOVE_MAX], fa[UNMOVE_MAX], fs[UNMOVE_MAX];
        int pnn, fnn;
        int np = f_pcount(q, pc, pk, pa, ps, &pnn);
        int nf = f_fcount(q, fc, fk, fa, fs, &fnn);
        // (0)
        int np2 = f_pcand(q, p2, NULL), nf2 = f_fcand(q, f2, NULL);
        if (np2 != np || memcmp(p2, pc, (size_t)np * sizeof(u_long)) || nf2 != nf ||
            memcmp(f2, fc, (size_t)nf * sizeof(u_long)))
            bad_copy++;
        // (a)
        Agg cp[NCAT], cf[NCAT];
        agg_cat(pc, pk, pa, ps, np, cp);
        agg_cat(fc, fk, fa, fs, nf, cf);
        int bad = !agg_eq(agg_of(pc, np), agg_of(fc, nf));
        for (int c = 0; c < NCAT; c++)
            if (!agg_eq(cp[c], cf[c])) {
                bad_cat[c]++;
                bad = 1;
            }
        if (bad) {
            bad_cand++;
            if (shown++ < 20) printf("食い違い: q=%#lx 絞った版 %d 個 / 反転を1回にした版 %d 個\n", q, np, nf);
        }
        // (b)
        int kp = f_psieved(q, ks, NULL, cls);
        Agg ap = agg_of(ks, kp);
        int kf = f_fsieved(q, ks, NULL, cls);
        Agg af = agg_of(ks, kf);
        int kn = f_nsieved(q, ks, NULL, cls);
        Agg an = agg_of(ks, kn);
        if (!agg_eq(ap, af) || !agg_eq(an, af)) bad_pred++;
        // (c)
        if (pnn != fnn) bad_nonnormal++;
        int zp = 0, zf = 0;
        for (int j = 0; j < np; j++) zp += cls[f_rank(pc[j])] == 0;
        for (int j = 0; j < nf; j++) zf += cls[f_rank(fc[j])] == 0;
        if (zp != zf) bad_none++;
        cand += (uint64_t)nf;
        kept += (uint64_t)kf;
        nonnormal += (uint64_t)fnn;
        none += (uint64_t)zf;
        if (i % 50000000 == 0 && i) {
            printf("... %zu 局面 (%.0f 秒)\n", i, now() - t0);
            fflush(stdout);
        }
    }
    printf("検査: %.1f 秒\n", now() - t0);
    printf("\n反転を1回にした版 (全到達局面の合計): 候補 %lu / 残った前任 %lu / 正規形でないとして捨てた %lu / "
           "到達しないとして捨てる候補 %lu\n", cand, kept, nonnormal, none);
    printf("\n(0) 写しの候補の列が元の関数と違った q: %zu\n", bad_copy);
    printf("(a) 候補の多重集合が違った q: %zu\n", bad_cand);
    for (int c = 0; c < NCAT; c++)
        if (bad_cat[c])
            printf("    %s, A=%d, %s: %zu\n", KIND_NAME[c / 4], (c / 2) % 2, c % 2 ? "鏡像" : "q", bad_cat[c]);
    printf("(b) 前任の多重集合が違った q: %zu\n", bad_pred);
    printf("(c) 正規形でないとして捨てた数が違った q: %zu / 到達しないとして捨てる数が違った q: %zu\n", bad_nonnormal, bad_none);
    int pass = !bad_copy && !bad_cand && !bad_pred && !bad_nonnormal && !bad_none;
    printf("\n一致の検査: %lu 局面 => %s\n", N_ALL, pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}

// ---- 成果物の形へ書き出す ------------------------------------------------------------------------------
// いまの実装 (impl/33_hot_layout/animal_shogi.py の writeWLFilesForDepth / writeUnknownChunks) と同じ分け方:
// 手数と勝敗ごとに, 空いている副番号から 5,000,000 局面ずつのファイル. 0 件でも副番号 0 が無ければ空のファイルを作る.
// 引き分けは unknown<番号>.bin に 5,000,000 局面ずつ (0 件なら空の unknown000.bin). 中身は 8 バイトのパック値の並び.
// fsync はしない (いまの実装も Python の write だけ). ファイルの中の並びは揃えない (集合と件数を揃える)
#define BOARD_NUM_MAX 5000000UL

static int g_sub[2][256];  // [勝ち 1 / 負け 0][手数] 次に使う副番号

static void write_one(const char *wdir, const char *name, const u_long *p, size_t n) {
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", wdir, name);
    FILE *f = fopen(path, "wb");
    if (!f || (n && fwrite(p, sizeof(u_long), n, f) != n) || fclose(f) != 0) die("書き出しに失敗");
}

static void write_depth(const char *wdir, int depth, const u_long *p, size_t n) {
    int win = depth % 2 == 1;
    char name[64];
    if (!n) {
        if (g_sub[win][depth] == 0) {
            snprintf(name, sizeof name, "%s%03dte_%03d.bin", win ? "win" : "lose", depth, 0);
            write_one(wdir, name, p, 0);
            g_sub[win][depth] = 1;
        }
        return;
    }
    for (size_t s = 0; s < n; s += BOARD_NUM_MAX) {
        size_t k = n - s < BOARD_NUM_MAX ? n - s : BOARD_NUM_MAX;
        snprintf(name, sizeof name, "%s%03dte_%03d.bin", win ? "win" : "lose", depth, g_sub[win][depth]++);
        write_one(wdir, name, p + s, k);
    }
}

// ---- retreat: 試作の後退解析 (unmove_prune の drop) を1本回し, 書き出し, dat/ と比べる ---------------------------
// 初期化と段の進め方は unmove_prune の bench.c の retreat と同じ. 違いは1段の関数 (pruneStep / flipStep) だけ.
// ループのあとで成果物の形へ書き出す (ループの秒には入れない). 書き出しは4つに分けて測る:
//   w_fwd:  全探索の側で書くもの (キャッチ局面 win001te_000〜, トライ負け lose000te_000〜). 換算には入れない
//   w_ret:  後退解析で決まった局面を, 手数ごとに書く (いまの実装では 174段ループの中で書いている)
//   draw:   引き分けを拾う: 未知局面の列 U (全探索が作る) を順に見て, dtm が未定のものを集める (ランクで dtm を引く)
//   w_uk:   引き分けを書く
static int retreat(const char *dat, const char *out, const char *ver, const char *label, const char *wdir) {
    StepFn step;
    if (!strcmp(ver, "pruned")) step = f_pstep;
    else if (!strcmp(ver, "flip")) step = f_fstep;
    else die("版は pruned / flip");
    uint8_t *lab;
    u_long *all = load_dat(dat, &lab);
    uint8_t *cls = load_cls(out);
    u_long range = f_range();
    uint8_t *dtm = huge_alloc(range), *cnt = huge_alloc(range);
    memset(dtm, DRAW, range);
    memset(cnt, 0, range);
    u_long *catches = malloc(N_CATCH * sizeof(u_long)), *tries = malloc(N_TRY * sizeof(u_long));
    u_long *uks = malloc(N_UNKNOWN * sizeof(u_long));
    u_long *zeros = malloc(N_UNKNOWN * sizeof(u_long));
    u_long *found = huge_alloc(N_ALL * sizeof(u_long));
    size_t nc = 0, nt = 0, nz = 0, nu = 0;
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
            uks[nu++] = all[i];
            if (f_b2(all[i], cls, &k) <= 0) die("未知局面の戻り値が正でない");
            if (k == 0) {
                dtm[r] = 2;
                zeros[nz++] = all[i];
            }
            cnt[r] = (uint8_t)k;
        } else {
            die("dat/ の局面のランクが cls で到達しない");
        }
    }
    double t_init = now() - t0;
    if (nc != N_CATCH || nt != N_TRY || nu != N_UNKNOWN) die("キャッチ・トライ負け・未知の数が合わない");
    printf("初期化: %.2f 秒 (キャッチ %zu / トライ負け %zu / キャッチ抜きの数が 0 で先に決めた %zu)\n", t_init, nc, nt, nz);

    printf("nd\tfrontier\tcandidates\tkept\tfound\tsec\n");
    CatchStepStats tot;
    memset(&tot, 0, sizeof tot);
    size_t nd_lo[256], nd_hi[256];
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
        int rc = step(fr, fr_n, odd, (uint8_t)nd, cls, dtm, cnt, found + pos, N_ALL - pos, &st);
        if (rc < 0) {
            fprintf(stderr, "rc=%d nd=%d\n", rc, nd);
            die("後退解析の1段を進められない");
        }
        pos += (size_t)rc;
        if (nd == 2) {
            if (pos + nz > N_ALL) die("found があふれた");
            memcpy(found + pos, zeros, nz * sizeof(u_long));
            pos += nz;
        }
        nd_lo[nd] = start;
        nd_hi[nd] = pos;
        double sec = now() - ts;
        printf("%d\t%zu\t%lu\t%lu\t%zu\t%.3f\n", nd, fr_n, st.candidates, st.kept, pos - start, sec);
        tot.expanded += st.expanded;
        tot.candidates += st.candidates;
        tot.kept += st.kept;
        for (int k = 0; k < 4; k++) tot.drop[k] += st.drop[k];
        if (pos == start) break;
        fr = found + start;
        fr_n = pos - start;
    }
    double t_loop = now() - t_loop0;

    // 成果物の形へ書き出す
    memset(g_sub, 0, sizeof g_sub);
    double tw = now();
    write_depth(wdir, 1, catches, nc);
    write_depth(wdir, 0, tries, nt);
    double t_wfwd = now() - tw;
    tw = now();
    for (int d = 1; d <= nd; d++) write_depth(wdir, d, found + nd_lo[d], nd_hi[d] - nd_lo[d]);
    double t_wret = now() - tw;
    tw = now();
    u_long *draws = malloc(N_UNKNOWN * sizeof(u_long));
    size_t ndraw = 0;
    {
        uint64_t rk[16];
        for (size_t i = 0; i < nu && i < 16; i++) {
            rk[i] = f_rank(uks[i]);
            __builtin_prefetch(&dtm[rk[i]], 0, 3);
        }
        for (size_t i = 0; i < nu; i++) {
            uint64_t r = rk[i % 16];
            if (i + 16 < nu) {
                rk[i % 16] = f_rank(uks[i + 16]);
                __builtin_prefetch(&dtm[rk[i % 16]], 0, 3);
            }
            if (dtm[r] == DRAW) draws[ndraw++] = uks[i];
        }
    }
    double t_draw = now() - tw;
    tw = now();
    if (!ndraw) write_one(wdir, "unknown000.bin", draws, 0);
    for (size_t s = 0, k = 0; s < ndraw; s += BOARD_NUM_MAX, k++) {
        char name[64];
        snprintf(name, sizeof name, "unknown%03zu.bin", k);
        write_one(wdir, name, draws + s, ndraw - s < BOARD_NUM_MAX ? ndraw - s : BOARD_NUM_MAX);
    }
    double t_wuk = now() - tw;
    printf("書き出し: 全探索の側 %.3f 秒 / 手数ごと %.3f 秒 / 引き分けを拾う %.3f 秒 (%zu 局面) / 引き分けを書く %.3f 秒\n",
           t_wfwd, t_wret, t_draw, ndraw, t_wuk);

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
           "zero_first\tmismatch\tw_fwd_sec\tw_ret_sec\tdraw_sec\tw_uk_sec\tdraws\n");
    printf("RESULT\t%s\t%s\t%.3f\t%.3f\t%d\t%lu\t%lu\t%lu\t%lu\t%lu\t%lu\t%zu\t%zu\t%.3f\t%.3f\t%.3f\t%.3f\t%zu\n", ver,
           label, t_init, t_loop, nd, tot.expanded, tot.candidates, tot.kept, tot.drop[0], tot.drop[2], tot.drop[3], nz,
           bad, t_wfwd, t_wret, t_draw, t_wuk, ndraw);
    return bad ? 1 : 0;
}

// ---- time: 生成器だけ (unmove_prune の timing と同じ形) -------------------------------------------------
// 種類ごとの抜き出しの列を, 1周温めてから1周測る. 計時するのは呼び出しのループだけ
static int timing(const char *out, const char *ver, int round) {
    const char *types[3] = {"unknown", "try", "expand"};
    u_long range = f_range();
    uint8_t *cls = NULL, *st = NULL;
    int flip = ver[0] == 'f';
    const char *stage = ver + 1;
    if ((ver[0] != 'p' && ver[0] != 'f') || (strcmp(stage, "cand") && strcmp(stage, "sieve") && strcmp(stage, "visit")))
        die("版は pcand / psieve / pvisit / fcand / fsieve / fvisit");
    if (strcmp(stage, "cand")) cls = load_cls(out);
    if (!strcmp(stage, "visit")) {
        st = huge_alloc(range);
        memset(st, 0x7f, range);
    }
    for (int ti = 0; ti < 3; ti++) {
        char name[64];
        size_t bytes;
        snprintf(name, sizeof name, "sample_%s.bin", types[ti]);
        u_long *smp = read_file(out, name, &bytes, 0);
        size_t m = bytes / sizeof(u_long);
        double ns = 0;
        size_t total = 0;
        for (int pass = 0; pass < 2; pass++) {
            u_long buf[UNMOVE_MAX];
            size_t sum = 0;
            double t0 = now();
            if (!strcmp(stage, "cand")) {
                if (flip)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_fcand(smp[i], buf, NULL);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_pcand(smp[i], buf, NULL);
            } else if (!strcmp(stage, "sieve")) {
                if (flip)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_fsieved(smp[i], buf, NULL, cls);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_psieved(smp[i], buf, NULL, cls);
            } else {
                if (flip)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_fvisit(smp[i], cls, st);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_pvisit(smp[i], cls, st);
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
    if (!strcmp(argv[1], "verify") && argc == 5) return verify(argv[3], argv[4]);
    if (!strcmp(argv[1], "retreat") && argc == 8) return retreat(argv[3], argv[4], argv[5], argv[6], argv[7]);
    if (!strcmp(argv[1], "time") && argc == 6) return timing(argv[3], argv[4], atoi(argv[5]));
    die("使い方は bench.c の先頭");
    return 2;
}
