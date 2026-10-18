// 一致の検査 (実験 rank_fast の段2。記録試行ではない). 計時はしない
//
//   verify <base の animal_shogi.so> <腕の animal_shogi.so> <乱数の盤の数> <局面の .bin> ...
//
// 2つの .so を dlopen (RTLD_LOCAL) し, 公開の rankBoard (rankValid が真なら rankOf, 偽なら INDEX_EMPTY) を比べる.
// rankBoard の中の rankOf は, その .so の rankOf がそのまま展開されたもの (呼び出し側と同じ static inline).
// 比べる盤は3種類:
//   (a) 局面の .bin の全局面 (#38 本走の dat/. 到達可能な全局面. F1 で rankOf に渡る盤)
//   (b) (a) の各局面を q にした base の unmoveCandidates() の全候補 (U_loop で rankOf に渡る盤. 到達しない局面も含む)
//   (c) rankValid が真になる盤を乱数で作ったもの (固定の種. 到達しないものを含めて番号の範囲の全体を突く)
// (a) と (c) は base の rankBoard が INDEX_EMPTY でないこと (正しい盤であること) も見る.
// 外れた盤は最初の 20 個まで, 種類・盤・2つの値を出す. 終了コードは 0 一致 / 1 不一致 / 2 準備の失敗.
// 最後の行に, 種類ごとの盤の数・正しくない盤の数・不一致の数.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long u_long;
typedef u_long (*rank_fn)(u_long);
typedef int (*cand_fn)(u_long, u_long *);

#define INDEX_EMPTY (~(u_long)0)
#define UNMOVE_CAP 1024  // animal_shogi.c の UNMOVE_MAX と同じ

// animal_shogi.h の enum PEACES と同じ値
enum { EMPTY, CHICK1, GIRAFFE1, ELEPHANT1, LION1, CHICKEN1, CHICK2 = 9, GIRAFFE2, ELEPHANT2, LION2, CHICKEN2 };

static rank_fn r0, r1;
static u_long bad = 0;

static void *open_so(const char *path) {
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) fprintf(stderr, "dlopen %s: %s\n", path, dlerror());
    return h;
}

static int check(const char *kind, u_long b) {
    u_long a = r0(b), c = r1(b);
    if (a != c) {
        if (bad < 20) printf("不一致 %s %016lx: base %lu / 腕 %lu\n", kind, b, a, c);
        bad++;
    }
    return a == INDEX_EMPTY;
}

static uint64_t rng = 0x9e3779b97f4a7c15ULL;
static uint64_t next(void) {  // xorshift64*
    rng ^= rng >> 12;
    rng ^= rng << 25;
    rng ^= rng >> 27;
    return rng * 0x2545f4914f6cdd1dULL;
}

// ライオンを1頭ずつ盤上の別のマスに置き, ひよこ・きりん・ぞうを2枚ずつ, 空いたマス (持ち主を選ぶ.
// ひよこは成っているかも選ぶ) か, どちらかの持ち駒に置く. 持ち駒は bit 48 から 2 ビットずつ
// (手番側のひよこ・きりん・ぞう, 相手のひよこ・きりん・ぞう. rankValid が読む並び)
static u_long random_board(void) {
    int sq[12], ne = 0;
    u_long b = 0;
    int a = (int)(next() % 12), c = (int)(next() % 11);
    if (c >= a) c++;
    b |= (u_long)LION1 << (4 * a);
    b |= (u_long)LION2 << (4 * c);
    for (int i = 0; i < 12; i++)
        if (i != a && i != c) sq[ne++] = i;
    // 種類ごとの (持ち主1の駒, 持ち主2の駒, 成った駒1, 成った駒2, 持ち駒の位置1, 持ち駒の位置2)
    static const int K[3][6] = {
        {CHICK1, CHICK2, CHICKEN1, CHICKEN2, 0, 6},
        {GIRAFFE1, GIRAFFE2, 0, 0, 2, 8},
        {ELEPHANT1, ELEPHANT2, 0, 0, 4, 10},
    };
    u_long h = 0;
    for (int k = 0; k < 3; k++)
        for (int p = 0; p < 2; p++) {
            int r = (int)(next() % (uint64_t)(ne + 2));
            if (r < ne) {
                int s = sq[r], own = (int)(next() & 1);
                int koma = K[k][own];
                if (k == 0 && (next() & 1)) koma = K[k][2 + own];
                b |= (u_long)koma << (4 * s);
                sq[r] = sq[--ne];
            } else {
                h += (u_long)1 << K[k][4 + (r - ne)];
            }
        }
    return b | h << 48;
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: verify <base.so> <arm.so> <n_random> <in.bin> ...\n");
        return 2;
    }
    void *h0 = open_so(argv[1]), *h1 = open_so(argv[2]);
    if (!h0 || !h1) return 2;
    r0 = (rank_fn)dlsym(h0, "rankBoard");
    r1 = (rank_fn)dlsym(h1, "rankBoard");
    cand_fn cand = (cand_fn)dlsym(h0, "unmoveCandidates");
    if (!r0 || !r1 || !cand) {
        fprintf(stderr, "rankBoard か unmoveCandidates が無い\n");
        return 2;
    }
    u_long n_rand = strtoul(argv[3], NULL, 10);
    u_long n_pos = 0, n_cand = 0, inv_pos = 0, inv_cand = 0, inv_rand = 0;
    u_long out[UNMOVE_CAP];
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
                n_pos++;
                inv_pos += (u_long)check("局面", buf[i]);
                int k = cand(buf[i], out);
                if (k < 0 || k > UNMOVE_CAP) {
                    fprintf(stderr, "unmoveCandidates が %d を返した: %016lx\n", k, buf[i]);
                    return 2;
                }
                for (int j = 0; j < k; j++) inv_cand += (u_long)check("候補", out[j]);
                n_cand += (u_long)k;
            }
        }
        fclose(fp);
    }
    for (u_long i = 0; i < n_rand; i++) inv_rand += (u_long)check("乱数", random_board());
    printf("局面 %lu (正しくない盤 %lu) / 候補 %lu (正しくない盤 %lu) / 乱数 %lu (正しくない盤 %lu) / 不一致 %lu\n",
           n_pos, inv_pos, n_cand, inv_cand, n_rand, inv_rand, bad);
    free(buf);
    return bad || inv_pos || inv_rand ? 1 : 0;
}
