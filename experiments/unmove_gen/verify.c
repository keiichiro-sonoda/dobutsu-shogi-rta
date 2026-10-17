// 一致の検査 (実験 unmove_gen。記録試行ではない)
//
//   verify <seq|multiset> <base の animal_shogi.so> <腕の animal_shogi.so> <局面の .bin> ...
//
// 2つの .so を dlopen (RTLD_LOCAL) し, 局面 q ごとに unmoveCandidates (逆向きの生成器. 表は中で作られる) を
// 両方で呼んで比べる:
//   seq       候補の数と, 候補の列 (並びまで) が同じ (bb_unmove)
//   multiset  候補の数と, 候補を並べ替えた列 (同じ値の個数まで含めた集まり) が同じ (mirror1).
//             食い違った局面は, q が左右対称か × A (q で Y のライオンに利いている X の駒のマス) の大きさ
//             (0 / 1 / 2 以上) で分けて数え, 片方にだけある候補が左右対称かも数える
// 外れた局面は最初の 20 個まで, 局面と食い違いを出す. 終了コードは 0 一致 / 1 不一致 / 2 準備の失敗.
// 最後の行に, 局面の数・不一致の数.
//
// 戻した数 (正規形でないとして捨てる前) も出す. base の候補の列から式で出す
// (鏡像の q から戻した候補は q から戻した候補の鏡像になる. これは mirror1 の多重集合の検査で確かめる):
//   q から戻した候補の集まりを C(q) とすると, 左右対称でない候補 c は c と鏡像のちょうど片方が正規形,
//   左右対称な c は正規形.
//   - q が左右対称でない: base は q と鏡像の q の両方から戻すので 2|C(q)|. base の出力は
//     対称でない c ごとに1個, 対称な c ごとに2個なので |C(q)| ＝ (対称でない出力) ＋ (対称な出力) / 2
//   - q が左右対称: base は q だけから戻すので |C(q)|. C(q) は鏡像で閉じているので
//     |C(q)| ＝ 2 × (対称でない出力) ＋ (対称な出力)
//   mirror1 は どちらの q でも |C(q)|. bb_unmove は base と同じ
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long u_long;
typedef int (*cand_fn)(u_long, u_long *);

#define CAND_MAX 1024

static cand_fn open_cand(const char *path) {
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen %s: %s\n", path, dlerror());
        return NULL;
    }
    cand_fn f = (cand_fn)dlsym(h, "unmoveCandidates");
    if (!f) fprintf(stderr, "%s: unmoveCandidates が無い\n", path);
    return f;
}

static u_long mirror(u_long b) {
    return ((b >> 48) << 48) | ((b & 0xffff) << 32) | (b & 0xffff0000UL) | ((b >> 32) & 0xffff);
}

static int symmetric(u_long b) {
    return ((b >> 32) & 0xffff) == (b & 0xffff);
}

// A の大きさ (impl/35_bitboard の unmoveTableBuild と unmoveRaw の写し. 食い違いを分けるためだけに使う)
static const int MV[4][8] = {{-16, -4, 4, 16}, {-20, -12, 12, 20}, {-20, -16, -12, -4, 4, 12, 16, 20},
                             {-20, -16, -4, 4, 12, 16}};
static const int MVN[4] = {4, 4, 8, 6};
static const int OWNER[4] = {10, 11, 12, 13};  // GIRAFFE2, ELEPHANT2, LION2, CHICKEN2
static uint16_t xatt[16][12];

static void xatt_build(void) {
    for (int s = 0; s < 48; s += 4) {
        int s16 = s % 16;
        for (int t = 0; t < 4; t++)
            for (int i = 0; i < MVN[t]; i++) {
                int dst = s + MV[t][i];
                if (dst < 0 || 44 < dst) continue;
                if (s16 == 0 && dst % 16 == 12) continue;
                if (s16 == 12 && dst % 16 == 0) continue;
                xatt[OWNER[t]][s / 4] |= (uint16_t)(1u << (dst / 4));
            }
        if (s16 != 0) xatt[9][s / 4] |= (uint16_t)(1u << ((s - 4) / 4));  // CHICK2
    }
}

static int a_size(u_long q) {
    int L = -1;
    for (int sq = 0; sq < 12; sq++)
        if (((q >> (4 * sq)) & 0xf) == 4) L = sq;  // LION1
    if (L < 0) return 3;
    int a = 0;
    for (int sq = 0; sq < 12; sq++) a += (xatt[(q >> (4 * sq)) & 0xf][sq] >> L) & 1;
    return a >= 2 ? 2 : a;
}

static int cmp_u64(const void *x, const void *y) {
    u_long a = *(const u_long *)x, b = *(const u_long *)y;
    return a < b ? -1 : a > b;
}

int main(int argc, char **argv) {
    if (argc < 5 || (strcmp(argv[1], "seq") != 0 && strcmp(argv[1], "multiset") != 0)) {
        fprintf(stderr, "usage: verify <seq|multiset> <base.so> <arm.so> <in.bin> ...\n");
        return 2;
    }
    int ms = strcmp(argv[1], "multiset") == 0;
    cand_fn f0 = open_cand(argv[2]), f1 = open_cand(argv[3]);
    if (!f0 || !f1) return 2;
    xatt_build();
    u_long n = 0, n_symq = 0, c0 = 0, c1 = 0, raw_base = 0, raw_one = 0, bad = 0;
    u_long bad_by[2][4] = {{0}}, only_sym = 0, only_asym = 0;
    static u_long a[CAND_MAX], b[CAND_MAX];
    u_long *buf = malloc((size_t)8 << 20);
    if (!buf) return 2;
    for (int f = 4; f < argc; f++) {
        FILE *fp = fopen(argv[f], "rb");
        if (!fp) {
            fprintf(stderr, "開けない: %s\n", argv[f]);
            return 2;
        }
        size_t m;
        while ((m = fread(buf, 8, (size_t)1 << 20, fp)) > 0) {
            for (size_t i = 0; i < m; i++) {
                u_long q = buf[i];
                int r0 = f0(q, a);
                int r1 = f1(q, b);
                int sq = mirror(q) == q;
                n++;
                n_symq += (u_long)sq;
                c0 += (u_long)r0;
                c1 += (u_long)r1;
                u_long ns = 0;
                for (int k = 0; k < r0; k++) ns += (u_long)symmetric(a[k]);
                u_long na = (u_long)r0 - ns;
                u_long cq = sq ? 2 * na + ns : na + ns / 2;
                raw_base += sq ? cq : 2 * cq;
                raw_one += cq;
                int ok = r0 == r1;
                if (ok && ms) {
                    qsort(a, (size_t)r0, sizeof(u_long), cmp_u64);
                    qsort(b, (size_t)r1, sizeof(u_long), cmp_u64);
                }
                if (ok) ok = memcmp(a, b, (size_t)r0 * sizeof(u_long)) == 0;
                if (ok) continue;
                int as = a_size(q);
                bad_by[sq][as]++;
                if (ms) {
                    if (!(r0 == r1)) {
                        qsort(a, (size_t)r0, sizeof(u_long), cmp_u64);
                        qsort(b, (size_t)r1, sizeof(u_long), cmp_u64);
                    }
                    int x = 0, y = 0;
                    while (x < r0 || y < r1) {
                        if (y >= r1 || (x < r0 && a[x] < b[y])) {
                            if (symmetric(a[x])) only_sym++;
                            else only_asym++;
                            x++;
                        } else if (x >= r0 || b[y] < a[x]) {
                            if (symmetric(b[y])) only_sym++;
                            else only_asym++;
                            y++;
                        } else {
                            x++;
                            y++;
                        }
                    }
                }
                if (bad < 20) {
                    printf("不一致 %016lx: 候補の数 %d / %d, q が左右対称 %d, A の大きさ %d", q, r0, r1, sq, as);
                    int lim = r0 < r1 ? r0 : r1;
                    for (int k = 0; k < lim; k++)
                        if (a[k] != b[k]) {
                            printf(", %d 番目 %016lx / %016lx", k, a[k], b[k]);
                            break;
                        }
                    printf("\n");
                }
                bad++;
            }
        }
        fclose(fp);
    }
    printf("q が左右対称な局面 %lu / 候補 base %lu・腕 %lu / 戻した数 (式) q と鏡像の両方から %lu・q だけから %lu\n",
           n_symq, c0, c1, raw_base, raw_one);
    if (bad) {
        printf("不一致の内訳 (q が左右対称か × A の大きさ 0 / 1 / 2 以上 / ライオンなし):\n");
        for (int s = 0; s < 2; s++)
            printf("  q 対称 %d: %lu / %lu / %lu / %lu\n", s, bad_by[s][0], bad_by[s][1], bad_by[s][2], bad_by[s][3]);
        if (ms) printf("片方にだけある候補: 左右対称 %lu / 対称でない %lu\n", only_sym, only_asym);
    }
    printf("局面 %lu / 不一致 %lu\n", n, bad);
    return bad ? 1 : 0;
}
