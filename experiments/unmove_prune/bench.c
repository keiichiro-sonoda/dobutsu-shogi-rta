// unmove_prune の本体 (記録試行ではない). experiments/unmove_catch/bench.c を土台にした
//
//   bench prep    <prune.so> <dat/> <出力先>              cls.bin と計時用の抜き出し (unmove_catch と同じ作り方・同じシード
//                                                         ＋ 未知とトライ負けから抜き出した sample_expand.bin)
//   bench verify  <prune.so> <dat/> <出力先>              一致の検査と, ついでに数えるもの (全到達局面)
//   bench retreat <prune.so> <dat/> <出力先> <版> <ラベル>  試作の後退解析 (unmove_catch の drop) を1本回し, 全局面で dat/ と比べる
//   bench time    <prune.so> <出力先> <版> <周>           抜き出した局面で版を1つ計時する (種類ごとに1行の TSV)
//
// 版 (retreat): naive (素朴な版の逆向きの生成器. unmove_catch の catchStep そのもの) / pruned (絞った版. pruneStep)
// 版 (time):    ncand / nsieve / nvisit (素朴な版の 1〜3 段階. unmove_bench と同じ関数) /
//               pcand / psieve / pvisit (絞った版の 1〜3 段階)
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
static int (*f_ncand)(u_long, u_long *, uint8_t *);
static int (*f_nsieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_nvisit)(u_long, const uint8_t *, uint8_t *);
static int (*f_pcand)(u_long, u_long *, uint8_t *);
static int (*f_psieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_pvisit)(u_long, const uint8_t *, uint8_t *);
static int (*f_classify)(u_long, u_long *, uint8_t *, uint8_t *, uint8_t *, int *, int *);
static StepFn f_nstep, f_pstep;

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
    f_ncand = sym(h, "unmoveCandidates");
    f_nsieved = sym(h, "unmoveSieved");
    f_nvisit = sym(h, "unmoveVisit");
    f_pcand = sym(h, "unmovePrunedCandidates");
    f_psieved = sym(h, "unmovePrunedSieved");
    f_pvisit = sym(h, "unmovePrunedVisit");
    f_classify = sym(h, "unmoveClassify");
    f_nstep = (StepFn)sym(h, "catchStep");
    f_pstep = (StepFn)sym(h, "pruneStep");
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
// 全到達局面 q で:
//   (a) 分類する版 (unmoveClassify) の候補の列が, 素朴な版 (unmoveCandidates) と種類まで同じ
//   (b) 絞った版 (unmovePrunedCandidates) の候補の列が, 分類する版の「捨てない」候補の列と順番まで同じ
//   (c) 絞った版の前任の多重集合 (unmovePrunedSieved) が素朴な版 (unmoveSieved) と同じ (q ごとに件数とハッシュ2つ)
//   (d) 絞った版の候補をふるうと, キャッチ局面を理由に捨てる候補が 0
//   (e) 素朴な版の候補の数 − 絞った版の候補の数 ＝ 素朴な版でキャッチ局面を理由に捨てていた候補の数
//   (f) 候補ごとの判定 (捨てる・捨てない) が, cls を引いた正解 (キャッチ局面か) と一致する
// ついでに数えるもの: A の大きさの分布 (q と鏡像), キャッチ局面を理由に捨てていた候補の, 捨てる理由ごとの内訳.
// 「展開する局面」は試作の後退解析 (drop) で展開する局面: 勝敗が決まっていて (dat/ が unknown* でない), キャッチ局面でないもの
typedef struct {
    uint32_t n;
    uint64_t sum, x;
} Agg;

#define XKEY 0x5bd1e9955bd1e995UL

// prune.c の候補ごとの判定 (unmoveClassify の codes) の値: 下位2ビットが捨てる理由 (0 捨てない / 1 A が2マス以上 /
// 2 A が1マスでほかの駒 / 3 戻した先から利く), 4 のビットは「捨てる理由が 1・2 で, 戻した先からも利く」
enum { PR_OTHER_CODE = 2, PR_DEST_FLAG_CODE = 4 };

static Agg agg_of(const u_long *p, int n) {
    Agg a = {0, 0, 0};
    for (int j = 0; j < n; j++) {
        a.n++;
        a.sum += mix(p[j]);
        a.x ^= mix(p[j] ^ XKEY);
    }
    return a;
}

// 集計の単位: 全到達局面 (0) と展開する局面 (1)
typedef struct {
    size_t q, asz_q[3], asz_m[3], sym, asz_qm_diff;
    uint64_t ncand, pcand, ncatch, pcatch, nkept;
    uint64_t reason[4], other_and_dest;
    uint64_t kind_catch[5][2], kind_cand[5][2];
} Tally;

static int verify(const char *dat, const char *out) {
    uint8_t *lab;
    u_long *all = load_dat(dat, &lab);
    uint8_t *cls = load_cls(out);
    Tally tal[2];
    memset(tal, 0, sizeof tal);
    size_t bad_list = 0, bad_prune = 0, bad_multiset = 0, shown = 0;
    // 候補ごとの判定の食い違い: [戻した手の種類][A の大きさ 0/1/2以上][0 = 捨てたが未知などだった / 1 = 残したがキャッチ局面だった]
    uint64_t miss[5][3][2];
    memset(miss, 0, sizeof miss);
    double t0 = now();
    for (size_t i = 0; i < N_ALL; i++) {
        u_long q = all[i];
        u_long nc_[UNMOVE_MAX], cc[UNMOVE_MAX], pc[UNMOVE_MAX], nk[UNMOVE_MAX], pk[UNMOVE_MAX];
        uint8_t nkind[UNMOVE_MAX], ckind[UNMOVE_MAX], pkind[UNMOVE_MAX], code[UNMOVE_MAX], asz[UNMOVE_MAX];
        int aq, am;
        int t = cls[f_rank(q)];
        int nn = f_ncand(q, nc_, nkind);
        int nc = f_classify(q, cc, ckind, code, asz, &aq, &am);
        int np = f_pcand(q, pc, pkind);
        if (nn >= UNMOVE_MAX || nc >= UNMOVE_MAX) die("候補の数がおかしい");
        // (a)
        if (nc != nn || memcmp(nc_, cc, (size_t)nn * sizeof(u_long)) || memcmp(nkind, ckind, (size_t)nn)) bad_list++;
        // (b)
        int m = 0, okb = 1;
        for (int j = 0; j < nc; j++) {
            if (code[j]) continue;
            if (m >= np || pc[m] != cc[j] || pkind[m] != ckind[j]) okb = 0;
            m++;
        }
        if (!okb || m != np) bad_prune++;
        // (c)
        int nkn = f_nsieved(q, nk, NULL, cls);
        int pkn = f_psieved(q, pk, NULL, cls);
        Agg an = agg_of(nk, nkn), ap = agg_of(pk, pkn);
        if (an.n != ap.n || an.sum != ap.sum || an.x != ap.x) {
            bad_multiset++;
            if (shown++ < 20) printf("食い違い: q=%#lx (%s) 素朴な版 %d 本 / 絞った版 %d 本\n", q, TYPE_NAME[t], nkn, pkn);
        }
        int expand = lab[i] != DRAW && t != T_CATCH;
        uint64_t ncatch = 0, pcatch = 0;
        for (int j = 0; j < nc; j++) {
            int c = cls[f_rank(cc[j])] == T_CATCH;
            int skip = code[j] != 0;
            int a = asz[j] < 2 ? asz[j] : 2;
            ncatch += (uint64_t)c;
            if (skip != c) miss[ckind[j]][a][c]++;
            for (int u = 0; u <= expand; u++) {
                Tally *T = &tal[u];
                T->kind_cand[ckind[j]][a ? 1 : 0]++;
                if (c) T->kind_catch[ckind[j]][a ? 1 : 0]++;
                if (!skip) continue;
                T->reason[code[j] & 3]++;
                if (code[j] == (PR_OTHER_CODE | PR_DEST_FLAG_CODE)) T->other_and_dest++;
            }
        }
        for (int j = 0; j < np; j++) pcatch += cls[f_rank(pc[j])] == T_CATCH;
        for (int u = 0; u <= expand; u++) {
            Tally *T = &tal[u];
            T->q++;
            T->asz_q[aq < 2 ? aq : 2]++;
            if (am < 0) T->sym++;
            else {
                T->asz_m[am < 2 ? am : 2]++;
                if (am != aq) T->asz_qm_diff++;
            }
            T->ncand += (uint64_t)nn;
            T->pcand += (uint64_t)np;
            T->ncatch += ncatch;
            T->pcatch += pcatch;
            T->nkept += (uint64_t)nkn;
        }
        if (i % 50000000 == 0 && i) {
            printf("... %zu 局面 (%.0f 秒)\n", i, now() - t0);
            fflush(stdout);
        }
    }
    printf("検査: %.1f 秒\n", now() - t0);
    uint64_t miss_total = 0;
    for (int k = 0; k < 5; k++)
        for (int a = 0; a < 3; a++) miss_total += miss[k][a][0] + miss[k][a][1];
    const char *unit[2] = {"全到達局面", "展開する局面 (試作の drop)"};
    for (int u = 0; u < 2; u++) {
        Tally *T = &tal[u];
        printf("\n## %s: %zu 局面\n\n", unit[u], T->q);
        printf("A の大きさ (q): 0 = %zu / 1 = %zu / 2以上 = %zu\n", T->asz_q[0], T->asz_q[1], T->asz_q[2]);
        printf("A の大きさ (鏡像): 0 = %zu / 1 = %zu / 2以上 = %zu (左右対称で鏡像を作らない q %zu. q と鏡像で大きさが違う %zu)\n",
               T->asz_m[0], T->asz_m[1], T->asz_m[2], T->sym, T->asz_qm_diff);
        printf("候補: 素朴な版 %lu / 絞った版 %lu / 作らなかった候補 %lu\n", T->ncand, T->pcand, T->ncand - T->pcand);
        printf("素朴な版でキャッチ局面を理由に捨てていた候補 %lu / 絞った版で同じ理由で捨てた候補 %lu / 残った前任 %lu\n",
               T->ncatch, T->pcatch, T->nkept);
        printf("作らなかった候補の理由 (判定の順に帰属): A が2マス以上 %lu / A が1マスで, ほかの駒を戻した %lu / "
               "戻した先から利く %lu (A が1マスでほかの駒を戻し, 戻した先からも利いた %lu は2つめに数えた)\n",
               T->reason[1], T->reason[2], T->reason[3], T->other_and_dest);
        printf("\n| 戻した手の種類 | 候補 (A=0) | うちキャッチ局面 | 候補 (A=1) | うちキャッチ局面 |\n|---|---|---|---|---|\n");
        for (int k = 0; k < 5; k++)
            printf("| %s | %lu | %lu | %lu | %lu |\n", KIND_NAME[k], T->kind_cand[k][0], T->kind_catch[k][0],
                   T->kind_cand[k][1], T->kind_catch[k][1]);
    }
    printf("\n候補ごとの判定の食い違い (戻した手の種類 × A の大きさ。捨てたが未知などだった / 残したがキャッチ局面だった):");
    if (!miss_total) printf(" なし");
    printf("\n");
    for (int k = 0; k < 5; k++)
        for (int a = 0; a < 3; a++)
            if (miss[k][a][0] || miss[k][a][1])
                printf("  %s, A=%d%s: %lu / %lu\n", KIND_NAME[k], a, a == 2 ? "以上" : "", miss[k][a][0], miss[k][a][1]);
    Tally *E = &tal[0];
    int pass = !bad_list && !bad_prune && !bad_multiset && !miss_total && E->pcatch == 0 &&
               E->ncand - E->pcand == E->ncatch && tal[1].ncand - tal[1].pcand == tal[1].ncatch;
    printf("\n(a) 分類する版の候補の列が素朴な版と違った q: %zu\n", bad_list);
    printf("(b) 絞った版の候補の列が, 捨てない候補の列と違った q: %zu\n", bad_prune);
    printf("(c) 前任の多重集合が素朴な版と違った q: %zu\n", bad_multiset);
    printf("(d) 絞った版の候補でキャッチ局面を理由に捨てた候補: %lu\n", E->pcatch);
    printf("(e) 作らなかった候補 %lu / 素朴な版でキャッチ局面を理由に捨てていた候補 %lu (展開する局面では %lu / %lu)\n",
           E->ncand - E->pcand, E->ncatch, tal[1].ncand - tal[1].pcand, tal[1].ncatch);
    printf("(f) 候補ごとの判定の食い違い: %lu\n", miss_total);
    printf("A が2マス以上の盤: q %zu / 鏡像 %zu\n", E->asz_q[2], E->asz_m[2]);
    printf("\n一致の検査: %lu 局面 => %s\n", N_ALL, pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}

// ---- retreat: 試作の後退解析 (unmove_catch の drop) を1本回し, dat/ と比べる -------------------------------
// 初期化と段の進め方は unmove_catch の bench.c の retreat (drop) と同じ. 違いは1段の関数 (catchStep / pruneStep) だけ
static int retreat(const char *dat, const char *out, const char *ver, const char *label) {
    StepFn step;
    if (!strcmp(ver, "naive")) step = f_nstep;
    else if (!strcmp(ver, "pruned")) step = f_pstep;
    else die("版は naive / pruned");
    uint8_t *lab;
    u_long *all = load_dat(dat, &lab);
    uint8_t *cls = load_cls(out);
    u_long range = f_range();
    uint8_t *dtm = huge_alloc(range), *cnt = huge_alloc(range);
    memset(dtm, DRAW, range);
    memset(cnt, 0, range);
    u_long *tries = malloc(N_TRY * sizeof(u_long));
    u_long *zeros = malloc(N_UNKNOWN * sizeof(u_long));
    u_long *found = huge_alloc(N_ALL * sizeof(u_long));
    size_t nc = 0, nt = 0, nz = 0;
    double t0 = now();
    for (size_t i = 0; i < N_ALL; i++) {
        u_long r = f_rank(all[i]);
        int t = cls[r];
        if (t == T_CATCH) {
            dtm[r] = 1;
            nc++;
        } else if (t == T_TRY) {
            dtm[r] = 0;
            tries[nt++] = all[i];
        } else if (t == T_UNKNOWN) {
            int k;
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
    if (nc != N_CATCH || nt != N_TRY) die("キャッチ・トライ負けの数が合わない");
    printf("初期化: %.2f 秒 (キャッチ %zu / トライ負け %zu / キャッチ抜きの数が 0 で先に決めた %zu)\n", t_init, nc, nt, nz);

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

// ---- time: 生成器だけ (unmove_bench の timing と同じ形) -------------------------------------------------
// 種類ごとの抜き出しの列を, 1周温めてから1周測る. 計時するのは呼び出しのループだけ
static int timing(const char *out, const char *ver, int round) {
    const char *types[3] = {"unknown", "try", "expand"};
    u_long range = f_range();
    uint8_t *cls = NULL, *st = NULL;
    int pruned = ver[0] == 'p';
    const char *stage = ver + 1;
    if ((ver[0] != 'n' && ver[0] != 'p') || (strcmp(stage, "cand") && strcmp(stage, "sieve") && strcmp(stage, "visit")))
        die("版は ncand / nsieve / nvisit / pcand / psieve / pvisit");
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
                if (pruned)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_pcand(smp[i], buf, NULL);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_ncand(smp[i], buf, NULL);
            } else if (!strcmp(stage, "sieve")) {
                if (pruned)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_psieved(smp[i], buf, NULL, cls);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_nsieved(smp[i], buf, NULL, cls);
            } else {
                if (pruned)
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_pvisit(smp[i], cls, st);
                else
                    for (size_t i = 0; i < m; i++) sum += (size_t)f_nvisit(smp[i], cls, st);
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
    if (!strcmp(argv[1], "retreat") && argc == 7) return retreat(argv[3], argv[4], argv[5], argv[6]);
    if (!strcmp(argv[1], "time") && argc == 6) return timing(argv[3], argv[4], atoi(argv[5]));
    die("使い方は bench.c の先頭");
    return 2;
}
