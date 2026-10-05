// unmove_bench の本体 (記録試行ではない)
//
//   bench prep   <unmove.so> <dat/> <出力先>          全局面を分類し, cls.bin と計時用の抜き出しを書く
//   bench verify <unmove.so> <dat/> <出力先>          全局面で, 前任の多重集合を前向きと逆向きで突き合わせる
//   bench time   <unmove.so> <出力先> <版> <周>       抜き出した局面で版を1つ計時する (種類ごとに1行の TSV)
//
// .so は本番と同じ gcc 行でビルドしたもの (build_so.sh). dlopen して関数ポインタで呼ぶ
// (1つの実行ファイルにすると, 本番では call になっている呼び出しが展開されて速く出る. gen_bench と同じ理由).
// 局面の種類は, いまの生成器の戻り値で決める (0 = キャッチ, -1 = トライ負け, 正 = 未知). ファイル名では決めない.

#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
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
#define N_EDGES 938671869UL
#define SAMPLE_N 10000000UL
#define SEED 20261005UL
#define UNMOVE_MAX 1024
#define HUGE_ALIGN ((size_t)1 << 21)

enum { T_NONE = 0, T_UNKNOWN = 1, T_CATCH = 2, T_TRY = 3 };
static const char *TYPE_NAME[4] = {"none", "unknown", "catch", "try"};
static const char *KIND_NAME[5] = {"move", "capture", "drop", "promote", "promote_capture"};

static int (*f_next)(u_long, u_long *);
static u_long (*f_range)(void);
static u_long (*f_rank_board)(u_long);
static u_long (*f_rank)(u_long);
static int (*f_cand)(u_long, u_long *, uint8_t *);
static int (*f_sieved)(u_long, u_long *, uint8_t *, const uint8_t *);
static int (*f_visit)(u_long, const uint8_t *, uint8_t *);
static void (*f_degw)(const u_long *, const int *, size_t, uint8_t *);

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
    // 本番の CDLL と同じ RTLD_LOCAL
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) die(dlerror());
    f_next = sym(h, "nextBoardInvNormal");
    f_range = sym(h, "rankRange");
    f_rank_board = sym(h, "rankBoard");
    f_rank = sym(h, "unmoveRank");
    f_cand = sym(h, "unmoveCandidates");
    f_sieved = sym(h, "unmoveSieved");
    f_visit = sym(h, "unmoveVisit");
    f_degw = sym(h, "unmoveDegWrite");
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

// dat/ の全ファイルを名前の順に読む (213 ファイル, 8 バイトの値の並び)
static u_long *load_dat(const char *dir, size_t *count) {
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
    size_t n = 0;
    for (int i = 0; i < nn; i++) {
        char path[4096];
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        FILE *f = fopen(path, "rb");
        if (!f) die("dat/ のファイルが開けない");
        size_t got;
        while ((got = fread(all + n, sizeof(u_long), 1 << 20, f)) > 0) {
            n += got;
            if (n > N_ALL) die("局面が多すぎる");
        }
        fclose(f);
        free(names[i]);
    }
    printf("dat: %d ファイル / %zu 局面\n", nn, n);
    if (n != N_ALL) die("局面の数が 246,803,167 でない");
    *count = n;
    return all;
}

static int classify(u_long b) {
    u_long nbs[64];
    int r = f_next(b, nbs);
    return r == 0 ? T_CATCH : r < 0 ? T_TRY : T_UNKNOWN;
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

// ---- prep ------------------------------------------------------------------------------
// cls.bin: ランクを添字にした種類 (0 到達しない / 1 未知 / 2 キャッチ / 3 トライ負け)
// sample_<種類>.bin: 計時用に抜き出した局面. 種類ごとに全体の比率で, 合わせて 1,000万.
//   抜き出しは種類ごとに, 局面の並び (dat/ の名前順) の上の部分的な Fisher-Yates (splitmix64, シード SEED).
//   sample_mixed.bin は3種類を合わせて同じ乱数で並べ替えたもの
static int prep(const char *dat, const char *out) {
    size_t n;
    u_long *all = load_dat(dat, &n);
    u_long range = f_range();
    uint8_t *cls = huge_alloc(range);
    memset(cls, 0, range);
    size_t cnt[4] = {0, 0, 0, 0};
    uint8_t *type = malloc(n);
    double t0 = now();
    for (size_t i = 0; i < n; i++) {
        int t = classify(all[i]);
        u_long r = f_rank_board(all[i]);
        if (r >= range) die("ランクが出せない局面がある");
        if (cls[r]) die("ランクが重なった (正規形の局面どうしで単射でない)");
        cls[r] = (uint8_t)t;
        type[i] = (uint8_t)t;
        cnt[t]++;
    }
    printf("分類: 未知 %zu / キャッチ %zu / トライ負け %zu (%.1f 秒)\n", cnt[1], cnt[2], cnt[3], now() - t0);
    printf("ランクの値域: %lu (表 %.1f MB)\n", range, range / 1e6);
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
        printf("抜き出し %s: %zu 局面 (全体の %zu 局面から)\n", TYPE_NAME[t], k, m);
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
    printf("抜き出し mixed: %zu 局面 (3種類を合わせて並べ替え. シード %lu)\n", total, SEED);
    return 0;
}

// ---- verify ----------------------------------------------------------------------------
// 正解は, いまの後退解析が作る前任の多重集合: pred(q) = { 未知局面 p : p の後続の列に q が現れる } (重複込み).
// q ごとに (件数, mix(p) の和, mix(p ^ 定数) の XOR) を, 前向き (未知局面 p の後続) と
// 逆向き (q から作った前任) の両方で集めて比べる. oracle/fingerprint.tsv と同じ考え方.
typedef struct {
    uint32_t n;
    uint32_t pad;
    uint64_t sum;
    uint64_t x;
} Agg;

#define XKEY 0x5bd1e9955bd1e995UL

static int verify(const char *dat, const char *out) {
    size_t n;
    u_long *all = load_dat(dat, &n);
    u_long range = f_range();
    size_t bytes;
    uint8_t *cls = read_file(out, "cls.bin", &bytes, 1);
    if (bytes != range) die("cls.bin の大きさがランクの値域と違う");
    // ランク -> dat/ の並びの番号
    uint32_t *r2i = huge_alloc(range * sizeof(uint32_t));
    memset(r2i, 0xff, range * sizeof(uint32_t));
    uint8_t *type = malloc(n);
    for (size_t i = 0; i < n; i++) {
        r2i[f_rank(all[i])] = (uint32_t)i;
        type[i] = cls[f_rank(all[i])];
    }
    Agg *fw = huge_alloc(n * sizeof(Agg));
    memset(fw, 0, n * sizeof(Agg));
    // 前向き: 未知局面 p の後続 q ごとに, p を q の前任として数える (重複込み)
    double t0 = now();
    size_t edges = 0;
    for (size_t i = 0; i < n; i++) {
        if (type[i] != 1) continue;
        u_long nbs[64];
        int k = f_next(all[i], nbs);
        if (k <= 0) die("未知局面の戻り値が正でない");
        uint64_t h1 = mix(all[i]), h2 = mix(all[i] ^ XKEY);
        for (int j = 0; j < k; j++) {
            uint32_t qi = r2i[f_rank(nbs[j])];
            if (qi == 0xffffffffu) die("後続が到達局面に無い");
            fw[qi].n++;
            fw[qi].sum += h1;
            fw[qi].x ^= h2;
        }
        edges += (size_t)k;
    }
    printf("前向き: 辺 %zu 本 (%.1f 秒)\n", edges, now() - t0);
    if (edges != N_EDGES) die("辺の数が 938,671,869 でない");
    // 逆向き: 全局面 q から前任を作り, 前向きの集計と比べる
    t0 = now();
    size_t bad = 0, shown = 0, cand_by[4] = {0}, kept_by[4] = {0}, q_by[4] = {0};
    size_t kind_cand[5] = {0}, kind_kept[5] = {0}, max_cand = 0, max_kept = 0, zero_pred = 0, sym_q = 0;
    size_t hist[17] = {0};
    for (size_t i = 0; i < n; i++) {
        u_long q = all[i], cand[UNMOVE_MAX], kept[UNMOVE_MAX];
        uint8_t ck[UNMOVE_MAX], kk[UNMOVE_MAX];
        int t = type[i];
        int nc = f_cand(q, cand, ck);
        int nk = f_sieved(q, kept, kk, cls);
        if (nc >= UNMOVE_MAX || nk > nc) die("候補の数がおかしい");
        Agg a = {0, 0, 0, 0};
        for (int j = 0; j < nk; j++) {
            a.n++;
            a.sum += mix(kept[j]);
            a.x ^= mix(kept[j] ^ XKEY);
            kind_kept[kk[j]]++;
        }
        for (int j = 0; j < nc; j++) kind_cand[ck[j]]++;
        q_by[t]++;
        cand_by[t] += (size_t)nc;
        kept_by[t] += (size_t)nk;
        if ((size_t)nc > max_cand) max_cand = (size_t)nc;
        if ((size_t)nk > max_kept) max_kept = (size_t)nk;
        if (nk == 0) zero_pred++;
        hist[nk < 16 ? nk : 16]++;
        if ((q & 0xffff) == ((q >> 32) & 0xffff)) sym_q++;
        if (a.n != fw[i].n || a.sum != fw[i].sum || a.x != fw[i].x) {
            bad++;
            if (shown < 20) {
                shown++;
                printf("食い違い: q=%#lx (%s, 左右対称 %d) 前向き %u 本 / 逆向き %u 本\n", q, TYPE_NAME[t],
                       (q & 0xffff) == ((q >> 32) & 0xffff), fw[i].n, a.n);
                for (int j = 0; j < nk; j++) printf("    逆向き p=%#lx (%s)\n", kept[j], KIND_NAME[kk[j]]);
            }
        }
    }
    printf("逆向き: %.1f 秒\n", now() - t0);
    printf("\n| q の種類 | 局面 | 候補（正規形・ふるう前） | 1局面あたり | ふるいに残った前任 | 1局面あたり |\n");
    printf("|---|---|---|---|---|---|\n");
    size_t tq = 0, tc = 0, tk = 0;
    for (int t = 1; t <= 3; t++) {
        printf("| %s | %zu | %zu | %.3f | %zu | %.3f |\n", TYPE_NAME[t], q_by[t], cand_by[t],
               (double)cand_by[t] / q_by[t], kept_by[t], (double)kept_by[t] / q_by[t]);
        tq += q_by[t];
        tc += cand_by[t];
        tk += kept_by[t];
    }
    printf("| 計 | %zu | %zu | %.3f | %zu | %.3f |\n", tq, tc, (double)tc / tq, tk, (double)tk / tq);
    printf("\n| 戻した手の種類 | 候補 | 残った前任 |\n|---|---|---|\n");
    for (int k = 0; k < 5; k++) printf("| %s | %zu | %zu |\n", KIND_NAME[k], kind_cand[k], kind_kept[k]);
    printf("\n前任の数の分布 (0〜15, 16 以上):");
    for (int k = 0; k <= 16; k++) printf(" %zu", hist[k]);
    printf("\n候補の最大 %zu / 前任の最大 %zu / 前任が 0 の局面 %zu / 左右対称な q %zu\n", max_cand, max_kept,
           zero_pred, sym_q);
    printf("前任の総数 (逆向き) %zu / 辺の総数 (前向き) %zu\n", tk, edges);
    printf("\n一致の検査: %zu 局面のうち, 食い違い %zu 局面 => %s\n", n, bad, bad || tk != edges ? "FAIL" : "PASS");
    return bad || tk != edges ? 1 : 0;
}

// ---- time ------------------------------------------------------------------------------
// 版: cand (1. 候補を作って正規化するまで) / sieve (2. 1 ＋ ふるい) / visit (3. 2 ＋ 状態の配列の読み書き) /
//     degw (換算用: 局面ごとにランクを出して 1 バイト書く) / gen (比べる相手: いまの前向きの生成器)
// 種類ごとの抜き出しの列を, 1周温めてから1周測る. 計時するのは呼び出しのループだけ
static int timing(const char *out, const char *ver, int round) {
    const char *types[4] = {"unknown", "catch", "try", "mixed"};
    u_long range = f_range();
    size_t bytes;
    uint8_t *cls = NULL, *st = NULL;
    if (strcmp(ver, "cand") && strcmp(ver, "gen")) {
        cls = read_file(out, "cls.bin", &bytes, 1);
        if (bytes != range) die("cls.bin の大きさがランクの値域と違う");
    }
    if (!strcmp(ver, "visit") || !strcmp(ver, "degw")) {
        st = huge_alloc(range);
        memset(st, 0x7f, range);
    }
    for (int ti = 0; ti < 4; ti++) {
        char name[64];
        snprintf(name, sizeof name, "sample_%s.bin", types[ti]);
        u_long *smp = read_file(out, name, &bytes, 0);
        size_t m = bytes / sizeof(u_long);
        int *deg = NULL;
        if (!strcmp(ver, "degw")) {
            deg = malloc(m * sizeof(int));
            for (size_t i = 0; i < m; i++) {
                u_long nbs[64];
                deg[i] = f_next(smp[i], nbs);
            }
        }
        double ns = 0;
        size_t total = 0;
        for (int pass = 0; pass < 2; pass++) {
            u_long buf[UNMOVE_MAX];
            size_t sum = 0;
            double t0 = now();
            if (!strcmp(ver, "cand")) {
                for (size_t i = 0; i < m; i++) sum += (size_t)f_cand(smp[i], buf, NULL);
            } else if (!strcmp(ver, "sieve")) {
                for (size_t i = 0; i < m; i++) sum += (size_t)f_sieved(smp[i], buf, NULL, cls);
            } else if (!strcmp(ver, "visit")) {
                for (size_t i = 0; i < m; i++) sum += (size_t)f_visit(smp[i], cls, st);
            } else if (!strcmp(ver, "degw")) {
                f_degw(smp, deg, m, st);
                sum = m;
            } else if (!strcmp(ver, "gen")) {
                for (size_t i = 0; i < m; i++) {
                    int k = f_next(smp[i], buf);
                    sum += k > 0 ? (size_t)k : 0;
                }
            } else {
                die("版は cand / sieve / visit / degw / gen");
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
        free(deg);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) die("使い方は bench.c の先頭");
    load_so(argv[2]);
    f_range();  // ランクの表を作る
    if (!strcmp(argv[1], "prep") && argc == 5) return prep(argv[3], argv[4]);
    if (!strcmp(argv[1], "verify") && argc == 5) return verify(argv[3], argv[4]);
    if (!strcmp(argv[1], "time") && argc == 6) return timing(argv[3], argv[4], atoi(argv[5]));
    die("使い方は bench.c の先頭");
    return 2;
}
