// P4 (前任リストの計数ソート) の形を縮小して再現するマイクロベンチ.
//
// 本番 (記録 #19 の本走) の1辺あたり:
//   P4_count   6.7 ns  (門番の採番順では 20.7 ns)
//   P4_scatter 61.8 ns (同 147.9 ns)
// 同じ succ を読み, 同じ pred_off を叩くのに 7〜9 倍違う.
//
// 仮説: scatter は書き込み先 pred[pred_off[q]++] が読み込みの結果で決まるため,
//       DRAM 待ちが直列に並ぶ. count は各辺が独立なので CPU が重ねられる.
//
// 確かめるカーネル:
//   count        pred_off[q+1]++                       (独立な読み書き. 参照)
//   scatter      pred[pred_off[q]++] = src             (本番の形)
//   store_indep  pred[perm(e)] = src                   (依存の無い乱択書き込み. 依存を外すと速いか)
//   pf1_D        scatter + pred_off だけ先読み
//   pf2_D        scatter + pred_off と pred の書き込み先を2段で先読み
//
// 使い方:
//   scatter_bench <uniform|local> <E_BITS> <plain|hp> [周回数] [all|core]
//     E_BITS  辺の本数の2進桁数 (既定 26 = 約 640 MB. 30 で約 10 GB, 本番の 1.14 倍)
//     hp      大きい配列に madvise(MADV_HUGEPAGE) を掛ける. 付いたかは出力の AnonHugePages で見る
//     周回数  既定 5 (最大 9)
//     core    count / scatter / store_indep / pf2_32 の4つだけ回す (本番規模で時間を節約する)
//
// 比率 (辺/行き先 3.8, 辺/出発 9.4) は本番に合わせた.
// 最初に回した機械 (Ryzen 7 8840U) では E_BITS=26 で scatter/count が 2.3 倍しか出ず,
// 本番の 7〜9 倍を再現しなかった. ⚠️ まず比が再現するかを見ること. 再現しない模型で
// 先読みの効き目を読んでも, 本番について何も言えない.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/mman.h>

typedef uint32_t u32;
typedef uint64_t u64;

static int E_BITS = 26;
static size_t E;
static u32 N;   // 行き先の数 (本番の n_all に相当)
static u32 S;   // 出発の数 (本番の n_uk に相当)
static u32 *succ, *succ_off, *pred, *pred_off;
static int hp = 0;  // 1 なら大きい配列に madvise(MADV_HUGEPAGE) を掛ける (THP が madvise モードの機械向け)

static void *xalloc(size_t bytes) {
    if (!hp) return malloc(bytes);
    size_t a = (size_t)1 << 21, sz = (bytes + a - 1) & ~(a - 1);
    void *p = aligned_alloc(a, sz);
    if (p && madvise(p, sz, MADV_HUGEPAGE) != 0) perror("madvise");
    return p;
}

// 実際に巨大ページが付いたかを読む (頼んだことと付いたことは別)
static void showHuge(void) {
    FILE *f = fopen("/proc/self/smaps_rollup", "r");
    char line[256];
    if (!f) return;
    while (fgets(line, sizeof line, f))
        if (strncmp(line, "AnonHugePages:", 14) == 0 || strncmp(line, "Rss:", 4) == 0) fputs(line, stdout);
    fclose(f);
}

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
static u64 rs = 88172645463325252ULL;
static inline u64 rnd(void) { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return rs; }

// 26 ビット上の全単射 (奇数倍と xorshift の合成). 依存の無い乱択位置を作る
static inline size_t perm(size_t x) {
    const size_t M = E - 1;
    x = (x * 0x9E3779B1u) & M;
    x ^= x >> 13;
    x = (x * 0x85EBCA77u) & M;
    x ^= x >> 11;
    return x;
}

static u64 csum(const u32 *a, size_t n) {
    u64 h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) { h ^= (u64)a[i] + i; h *= 1099511628211ULL; }
    return h;
}

// ---- カーネル ----

static double k_count(void) {
    memset(pred_off, 0, ((size_t)N + 1) * sizeof(u32));
    double t0 = now();
    for (size_t e = 0; e < E; e++) {
        u32 q = succ[e];
        if (q >= N) abort();
        pred_off[(size_t)q + 1]++;
    }
    double t = now() - t0;
    u64 tot = 0;
    for (size_t i = 1; i <= N; i++) { tot += pred_off[i]; pred_off[i] = (u32)tot; }
    if (tot != E) abort();
    return t;
}

static void unshift(void) {
    for (size_t i = N; i > 0; i--) pred_off[i] = pred_off[i - 1];
    pred_off[0] = 0;
}

// 本番 predScatter と同じ形 (出発ごとの二重ループ, 範囲検査つき)
static double k_scatter(void) {
    double t0 = now();
    for (u32 s = 0; s < S; s++) {
        u32 lo = succ_off[s], hi = succ_off[s + 1];
        for (u32 e = lo; e < hi; e++) {
            u32 q = succ[e];
            if (q >= N) abort();
            pred[pred_off[q]++] = s;
        }
    }
    double t = now() - t0;
    unshift();
    return t;
}

static double k_store_indep(void) {
    double t0 = now();
    u32 s = 0, next = succ_off[1];
    for (size_t e = 0; e < E; e++) {
        while (e >= next) { s++; next = succ_off[s + 1]; }
        pred[perm(e)] = s;
    }
    return now() - t0;
}

// 1段: pred_off[q] だけ D 本先を先読み
static double k_pf1(size_t D) {
    double t0 = now();
    u32 s = 0, next = succ_off[1];
    for (size_t e = 0; e < E; e++) {
        while (e >= next) { s++; next = succ_off[s + 1]; }
        if (e + D < E) __builtin_prefetch(&pred_off[succ[e + D]], 1, 3);
        u32 q = succ[e];
        if (q >= N) abort();
        pred[pred_off[q]++] = s;
    }
    double t = now() - t0;
    unshift();
    return t;
}

// 2段: 2D 本先で pred_off[q] を, D 本先で (もう届いているはずの) pred_off から
//      pred の書き込み先を先読みする. 先読みはヒントなので書く値は変わらない
static double k_pf2(size_t D) {
    double t0 = now();
    u32 s = 0, next = succ_off[1];
    for (size_t e = 0; e < E; e++) {
        while (e >= next) { s++; next = succ_off[s + 1]; }
        if (e + 2 * D < E) __builtin_prefetch(&pred_off[succ[e + 2 * D]], 1, 3);
        if (e + D < E) __builtin_prefetch(&pred[pred_off[succ[e + D]]], 1, 3);
        u32 q = succ[e];
        if (q >= N) abort();
        pred[pred_off[q]++] = s;
    }
    double t = now() - t0;
    unshift();
    return t;
}

// ---- 本体 ----

#define MAX_REPS 9
enum { K_COUNT, K_SCATTER, K_INDEP, K_PF1_16, K_PF2_8, K_PF2_16, K_PF2_32, K_PF2_64, NK };
static const char *kname[NK] = {"count", "scatter", "store_indep", "pf1_16",
                                "pf2_8", "pf2_16", "pf2_32", "pf2_64"};

static int cmpd(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    int local = (argc > 1 && strcmp(argv[1], "local") == 0);
    if (argc > 2) E_BITS = atoi(argv[2]);
    hp = (argc > 3 && strcmp(argv[3], "hp") == 0);
    int reps = (argc > 4) ? atoi(argv[4]) : 5;
    int core = (argc > 5 && strcmp(argv[5], "core") == 0);
    if (E_BITS < 16 || E_BITS > 30) { puts("E_BITS は 16..30"); return 1; }
    if (reps < 1 || reps > MAX_REPS) { printf("周回数は 1..%d\n", MAX_REPS); return 1; }
    E = (size_t)1 << E_BITS;
    N = (u32)(E * 10 / 38);   // 辺/行き先 = 3.8
    S = (u32)(E * 100 / 943); // 辺/出発 = 9.43
    succ = xalloc(E * sizeof(u32));
    pred = xalloc(E * sizeof(u32));
    pred_off = xalloc(((size_t)N + 1) * sizeof(u32));
    succ_off = xalloc(((size_t)S + 1) * sizeof(u32));
    if (!succ || !pred || !pred_off || !succ_off) { puts("確保できず"); return 1; }
    printf("辺 %zu / 行き先 %u / 出発 %u / 合計 %.0f MB / 行き先の分布 %s\n", E, N, S,
           (E * 8.0 + (N + 1) * 4.0 + (S + 1) * 4.0) / 1e6, local ? "局所" : "一様");

    for (u32 s = 0; s <= S; s++) succ_off[s] = (u32)((u64)s * E / S);
    for (u32 s = 0; s < S; s++) {
        // 局所: 出発の番号に比例した位置の ±1/128 (幅 1/64) の窓に落とす (採番順が効いている状態の粗い模型)
        u64 center = (u64)s * N / S, w = N / 64;
        for (u32 e = succ_off[s]; e < succ_off[s + 1]; e++)
            succ[e] = local ? (u32)((center + N - w / 2 + rnd() % w) % N) : (u32)(rnd() % N);
    }
    memset(pred, 0, E * sizeof(u32));
    memset(pred_off, 0, ((size_t)N + 1) * sizeof(u32));
    printf("巨大ページ %s\n", hp ? "頼んだ" : "頼んでいない");
    showHuge();

    double t[NK][MAX_REPS];
    int ran[NK] = {0};
    u64 ref = 0;
    static const size_t Ds[] = {8, 16, 32, 64};
    for (int r = 0; r < reps; r++) {
        // 1周ごとに全カーネルを回す (他の作業による揺れを各カーネルに均等に配る)
        t[K_COUNT][r] = k_count(); ran[K_COUNT] = 1;
        t[K_SCATTER][r] = k_scatter(); ran[K_SCATTER] = 1;
        u64 c = csum(pred, E);
        if (r == 0) ref = c; else if (c != ref) { puts("NG scatter"); return 1; }
        t[K_INDEP][r] = k_store_indep(); ran[K_INDEP] = 1;
        if (!core) {
            t[K_PF1_16][r] = k_pf1(16); ran[K_PF1_16] = 1;
            if (csum(pred, E) != ref) { puts("NG pf1_16"); return 1; }
        }
        for (int i = 0; i < 4; i++) {
            // core では pf2_32 だけ. store_indep が pred を壊しているので, 少なくとも1本は必ず書き直す
            if (core && Ds[i] != 32) continue;
            t[K_PF2_8 + i][r] = k_pf2(Ds[i]); ran[K_PF2_8 + i] = 1;
            if (csum(pred, E) != ref) { printf("NG pf2_%zu\n", Ds[i]); return 1; }
        }
    }
    puts("先読みした版の pred は全周で scatter とチェックサム一致");
    printf("%-12s %9s %9s %9s  (ns/辺, %d 周)\n", "kernel", "min", "median", "max", reps);
    for (int k = 0; k < NK; k++) {
        if (!ran[k]) continue;
        qsort(t[k], reps, sizeof(double), cmpd);
        printf("%-12s %9.2f %9.2f %9.2f\n", kname[k], t[k][0] / E * 1e9,
               t[k][reps / 2] / E * 1e9, t[k][reps - 1] / E * 1e9);
    }
    return 0;
}
