// 逆向きの生成器で, 盤の反転を局面ごとに1回にする (実験 unmove_flip。記録試行ではない)
//
// experiments/unmove_prune/prune.c (絞った版の逆向きの生成器と pruneStep. 書き換えずに使う) を取り込む.
// prune.c は unmove_catch の catch.c を, catch.c は unmove_bench の unmove.c を, unmove.c は
// impl/33_hot_layout/animal_shogi.c を取り込むので, 素朴な版・絞った版・反転を1回にした版が同じ翻訳単位に入る.
//
// ---- 写し方 (README に導き方を書いた) ---------------------------------------------------------
// 絞った版は手を指した直後の盤 nb (q か鏡像. 直前に指した側 X の駒が 9〜13, X の持ち駒が bit 54〜59) の上で
// 手を戻し, 戻した盤 b' を候補ごとに invBoard して前任 p にしている. invBoard はマス a を 44 − a へ移し,
// 駒の持ち主のビットを反転し, 持ち駒の2組を入れ替える. そこで先に f = invBoard(nb) を作り, f の上で手を戻す.
// f では X の駒が 1〜5, X の持ち駒が bit 48〜53, Y の駒が 9〜13. 戻した盤がそのまま p になる.
//   - マス a = 16 × 列 + 4 × 行 は 44 − a = 16 × (2 − 列) + 4 × (3 − 行) へ移るので, a % 16 は 12 − a % 16 になる
//   - nb で s から d = s + m へ動いた手は, f では s' = 44 − s から d' = 44 − d = s' − m へ. 戻すと s' = d' + m
//   - 回り込みの2条件 (s % 16 == 0 かつ d % 16 == 12 / s % 16 == 12 かつ d % 16 == 0) は,
//     % 16 が 12 − (% 16) に替わるので (s' % 16 == 12 かつ d' % 16 == 0 / s' % 16 == 0 かつ d' % 16 == 12). 同じ組
//   - ひよこ: nb では d = s − 4 へ進み d % 16 が 4 か 8 なら成らない手, 0 なら成る手. f では d' = s' + 4,
//     d' % 16 が 8 か 4 なら成らない手, 12 なら成る手 (にわとり CHICKEN1 が d' % 16 == 12 にいれば, s' = d' − 4 のひよこから)
//   - 打った手を戻す: X の持ち駒 (f では bit 48 + 2 × (k − 1)) を1つ増やす. 増やし方の式は同じ
//   - 取った駒を戻す: Y の駒 c を d' に c | 8 で置き, X の持ち駒 (f では c == CHICKEN1 なら bit 48, ほかは 46 + 2c) を1つ減らす
// 鏡像: invBoard(mirror(q)) == mirror(invBoard(q)) (列の入れ替えとマスの裏返しは入れ替えられる. 持ち駒は鏡像で変わらない) なので,
// q ごとに invBoard は1回だけにし, 鏡像の側は unmoveMirror(f) で作る. q が左右対称 ⇔ f が左右対称.
// 正規形の判定 (normalBoard(p) == p を候補ごとに見る) は絞った版と同じ.
//
// 絞り込みの写し方: A (q で Y に王手をかけている X の駒のマスの集合. 盤の列 A〜C とは関係ない) は f の上で作り直す.
// f では Y のライオンが LION2, X の駒 k がマス s から s − m へ利く (nb の s + m を裏返したもの), X のひよこ (CHICK1) は
// s + 4 へ利く (s % 16 == 12 なら利かない). この表は attack_count の g_att と同じ形.

#include "prune.c"

// f の上で, X の駒 k (1〜5) がマス sq にいるとき利くマスの集合. Y の駒と空きは 0
static uint16_t g_fatt[16][12];
static int g_fatt_ready = 0;

static void flipTableBuild(void) {
    static const int *const tables[4] = {GIRAFFE_MOVE, ELEPHANT_MOVE, LION_MOVE, CHICKEN2_MOVE};
    static const int sizes[4] = {4, 4, 8, 6};
    static const int owners[4] = {GIRAFFE1, ELEPHANT1, LION1, CHICKEN1};
    if (g_fatt_ready) return;
    memset(g_fatt, 0, sizeof g_fatt);
    for (int s = 0; s < 48; s += 4) {
        int s16 = s % 16;
        for (int t = 0; t < 4; t++)
            for (int i = 0; i < sizes[t]; i++) {
                int L = s - tables[t][i];
                if (L < 0 || 44 < L) continue;
                if (s16 == 12 && L % 16 == 0) continue;
                if (s16 == 0 && L % 16 == 12) continue;
                g_fatt[owners[t]][s / 4] |= (uint16_t)(1u << (L / 4));
            }
        if (s16 != 12) g_fatt[CHICK1][s / 4] |= (uint16_t)(1u << ((s + 4) / 4));
    }
    g_fatt_ready = 1;
}

// 一致の検査用の数え (NULL なら数えない)
typedef struct {
    int nonnormal;  // 正規形でないとして捨てた戻し方
} FlipCount;

// 戻した盤 (そのまま p) が正規形なら out に足す. side は nb が q (0) か鏡像 (1) か
static inline __attribute__((always_inline)) int flipEmit(u_long p, int kind, int asz, int side, u_long *out,
                                                          uint8_t *kinds, uint8_t *aszs, uint8_t *sides,
                                                          FlipCount *fc, int n) {
    if (normalBoard(p) != p) {
        if (fc) fc->nonnormal++;
        return n;
    }
    if (kinds) kinds[n] = (uint8_t)kind;
    if (aszs) aszs[n] = (uint8_t)asz;
    if (sides) sides[n] = (uint8_t)side;
    out[n] = p;
    return n + 1;
}

// f のマス d の X の駒の手を全部戻す. 絞った版の prunePiece (classify = 0) を f の上に写したもの
static inline __attribute__((always_inline)) int flipPiece(u_long f, int d, int L, int asz, int side, u_long *out,
                                                           uint8_t *kinds, uint8_t *aszs, uint8_t *sides,
                                                           FlipCount *fc, int n) {
    u_long k = getKoma(f, d);
    u_long base = delKoma(f, d);
    int d16 = d % 16;
    if (k == CHICK1 || k == GIRAFFE1 || k == ELEPHANT1) {
        int own_p = 48 + (int)(k - CHICK1) * 2;
        u_long c = (f >> own_p) & 0b11;
        if (c < 2)
            n = flipEmit(base ^ ((c ? (u_long)0b11 : (u_long)0b01) << own_p), UK_DROP, asz, side, out, kinds, aszs,
                         sides, fc, n);
    }
    int srcs[10], k0s[10], promo[10], ns = 0;
    if (k == CHICK1) {
        if (d16 == 4 || d16 == 8) {
            srcs[ns] = d - 4;
            k0s[ns] = CHICK1;
            promo[ns++] = 0;
        }
    } else {
        const int *moves = NULL;
        int moves_num = 0;
        switch (k) {
            case GIRAFFE1: moves = GIRAFFE_MOVE; moves_num = 4; break;
            case ELEPHANT1: moves = ELEPHANT_MOVE; moves_num = 4; break;
            case LION1: moves = LION_MOVE; moves_num = 8; break;
            case CHICKEN1: moves = CHICKEN2_MOVE; moves_num = 6; break;
            default: break;
        }
        for (int i = 0; i < moves_num; i++) {
            int s = d + moves[i];
            if (s < 0 || 44 < s) continue;
            int s16 = s % 16;
            if (s16 == 12 && d16 == 0) continue;
            if (s16 == 0 && d16 == 12) continue;
            srcs[ns] = s;
            k0s[ns] = (int)k;
            promo[ns++] = 0;
        }
        if (k == CHICKEN1 && d16 == 12) {
            srcs[ns] = d - 4;
            k0s[ns] = CHICK1;
            promo[ns++] = 1;
        }
    }
    for (int j = 0; j < ns; j++) {
        int s = srcs[j];
        if (getKoma(f, s)) continue;
        if ((g_fatt[k0s[j]][s / 4] >> L) & 1) continue;  // 戻した先 s から Y のライオンに利く: 前任はキャッチ局面
        u_long b0 = base | ((u_long)k0s[j] << s);
        n = flipEmit(b0, promo[j] ? UK_PROMOTE : UK_MOVE, asz, side, out, kinds, aszs, sides, fc, n);
        for (int t = 0; t < 4; t++) {
            int c = UNMOVE_CAPTURED[t];
            int own_p = c == CHICKEN1 ? 48 : 46 + c * 2;
            u_long cnt = (b0 >> own_p) & 0b11;
            if (!cnt) continue;
            u_long b1 = (b0 ^ ((cnt == 2 ? (u_long)0b11 : (u_long)0b01) << own_p)) | ((u_long)(c | 8) << d);
            n = flipEmit(b1, promo[j] ? UK_PROMOTE_CAPTURE : UK_CAPTURE, asz, side, out, kinds, aszs, sides, fc, n);
        }
    }
    return n;
}

static inline __attribute__((always_inline)) int flipRaw(u_long f, int side, u_long *out, uint8_t *kinds,
                                                         uint8_t *aszs, uint8_t *sides, FlipCount *fc, int n) {
    int L = rankFindKoma(f & 0xffffffffffffUL, LION2);
    unsigned a = 0;
    for (int sq = 0; sq < 12; sq++) a |= ((g_fatt[getKoma(f, 4 * sq)][sq] >> L) & 1u) << sq;
    int asz = __builtin_popcount(a);
    // 局面と駒の単位: A が2マス以上なら前任は無い. 1マスなら, そのマスの駒だけを戻す
    if (asz >= 2) return n;
    if (asz == 1) return flipPiece(f, 4 * __builtin_ctz(a), L, asz, side, out, kinds, aszs, sides, fc, n);
    for (int d = 0; d < 48; d += 4) {
        u_long k = getKoma(f, d);
        if (!k || (k & 0b1000)) continue;
        n = flipPiece(f, d, L, asz, side, out, kinds, aszs, sides, fc, n);
    }
    return n;
}

static inline __attribute__((always_inline)) int flipCore(u_long q, u_long *out, uint8_t *kinds, uint8_t *aszs,
                                                          uint8_t *sides, FlipCount *fc) {
    u_long f = invBoard(q);
    int n = flipRaw(f, 0, out, kinds, aszs, sides, fc, 0);
    u_long fm = unmoveMirror(f);
    if (fm != f) n = flipRaw(fm, 1, out, kinds, aszs, sides, fc, n);
    return n;
}

// 1''. 反転を1回にした版の候補 (ふるう前). 絞った版 (unmovePrunedCandidates) と同じ候補を, 違う順で作る
int unmoveFlipCandidates(u_long q, u_long *out, uint8_t *kinds) {
    flipTableBuild();
    return flipCore(q, out, kinds, NULL, NULL, NULL);
}

// 一致の検査用: 候補ごとの手の種類・A の大きさ・nb が q か鏡像か と, 正規形でないとして捨てた数
int unmoveFlipCounted(u_long q, u_long *out, uint8_t *kinds, uint8_t *aszs, uint8_t *sides, int *nonnormal) {
    FlipCount fc = {0};
    flipTableBuild();
    int n = flipCore(q, out, kinds, aszs, sides, &fc);
    *nonnormal = fc.nonnormal;
    return n;
}

// 2''. ふるう (unmove.c の unmoveSieved と同じ形)
int unmoveFlipSieved(u_long q, u_long *out, uint8_t *kinds, const uint8_t *cls) {
    u_long cand[UNMOVE_MAX];
    uint8_t ck[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmoveFlipCandidates(q, cand, kinds ? ck : NULL), m = 0;
    for (int i = 0; i < n; i++) {
        r[i] = rankOf(cand[i]);
        __builtin_prefetch(&cls[r[i]], 0, 3);
    }
    for (int i = 0; i < n; i++) {
        if (cls[r[i]] != 1) continue;
        if (kinds) kinds[m] = ck[i];
        out[m++] = cand[i];
    }
    return m;
}

// 3''. 2'' ＋ 状態の読み書き (unmove.c の unmoveVisit と同じ形)
int unmoveFlipVisit(u_long q, const uint8_t *cls, uint8_t *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmoveFlipCandidates(q, cand, NULL), m = 0;
    for (int i = 0; i < n; i++) {
        r[i] = rankOf(cand[i]);
        __builtin_prefetch(&cls[r[i]], 0, 3);
    }
    for (int i = 0; i < n; i++) {
        if (cls[r[i]] != 1) continue;
        r[m++] = r[i];
        __builtin_prefetch(&st[r[i]], 1, 3);
    }
    for (int i = 0; i < m; i++) st[r[i]] = (uint8_t)(st[r[i]] - 1);
    return m;
}

// 試作の後退解析の1段の, 反転を1回にした版. prune.c の pruneStep の写しで, 違いは逆向きの生成器
// (unmovePrunedCandidates → unmoveFlipCandidates) だけ
int flipStep(const u_long *frontier, size_t n, int odd, uint8_t nd, const uint8_t *cls, uint8_t *dtm, uint8_t *cnt,
             u_long *found, size_t found_cap, CatchStepStats *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    size_t nf = 0;
    for (size_t i = 0; i < n; i++) {
        int nc = unmoveFlipCandidates(frontier[i], cand, NULL), m = 0;
        st->candidates += (uint64_t)nc;
        for (int j = 0; j < nc; j++) {
            r[j] = rankOf(cand[j]);
            __builtin_prefetch(&cls[r[j]], 0, 3);
        }
        for (int j = 0; j < nc; j++) {
            uint8_t c = cls[r[j]];
            if (c != 1) {
                st->drop[c]++;
                continue;
            }
            cand[m] = cand[j];
            r[m++] = r[j];
            __builtin_prefetch(&dtm[r[j]], 1, 3);
            if (odd) __builtin_prefetch(&cnt[r[j]], 1, 3);
        }
        st->kept += (uint64_t)m;
        for (int j = 0; j < m; j++) {
            uint64_t rr = r[j];
            if (odd) {
                if (cnt[rr] == 0) return -4;
                cnt[rr]--;
                if (cnt[rr] != 0 || dtm[rr] != 255) continue;
            } else {
                if (dtm[rr] != 255) continue;
            }
            if (nf >= found_cap) return -2;
            dtm[rr] = nd;
            found[nf++] = cand[j];
        }
    }
    st->expanded += n;
    st->found += nf;
    return (int)nf;
}

// ---- 一致の検査用: 絞った版を数えながら作る写し ----------------------------------------------------
// prune.c の prunePiece / pruneRaw (classify = 0) と同じ候補を同じ順で作り, 正規形でないとして捨てた数と,
// 候補ごとの A の大きさ・nb が q か鏡像か を残す. prune.c の関数は数えを持たないので写した.
// 写しが絞った版と同じものを作ることは, 検査で unmovePrunedCandidates の出力と順番まで突き合わせて確かめる
static inline __attribute__((always_inline)) int pcEmit(u_long bp, int kind, int asz, int side, u_long *out,
                                                        uint8_t *kinds, uint8_t *aszs, uint8_t *sides, int *nn,
                                                        int n) {
    u_long p = invBoard(bp);
    if (normalBoard(p) != p) {
        (*nn)++;
        return n;
    }
    kinds[n] = (uint8_t)kind;
    aszs[n] = (uint8_t)asz;
    sides[n] = (uint8_t)side;
    out[n] = p;
    return n + 1;
}

static int pcPiece(u_long nb, int d, int L, int asz, int side, u_long *out, uint8_t *kinds, uint8_t *aszs,
                   uint8_t *sides, int *nn, int n) {
    u_long k = getKoma(nb, d);
    u_long base = delKoma(nb, d);
    int d16 = d % 16;
    if (k == CHICK2 || k == GIRAFFE2 || k == ELEPHANT2) {
        int own_p = 54 + (int)(k - CHICK2) * 2;
        u_long c = (nb >> own_p) & 0b11;
        if (c < 2)
            n = pcEmit(base ^ ((c ? (u_long)0b11 : (u_long)0b01) << own_p), UK_DROP, asz, side, out, kinds, aszs,
                       sides, nn, n);
    }
    int srcs[10], k0s[10], promo[10], ns = 0;
    if (k == CHICK2) {
        if (d16 == 4 || d16 == 8) {
            srcs[ns] = d + 4;
            k0s[ns] = CHICK2;
            promo[ns++] = 0;
        }
    } else {
        const int *moves = NULL;
        int moves_num = 0;
        switch (k) {
            case GIRAFFE2: moves = GIRAFFE_MOVE; moves_num = 4; break;
            case ELEPHANT2: moves = ELEPHANT_MOVE; moves_num = 4; break;
            case LION2: moves = LION_MOVE; moves_num = 8; break;
            case CHICKEN2: moves = CHICKEN2_MOVE; moves_num = 6; break;
            default: break;
        }
        for (int i = 0; i < moves_num; i++) {
            int s = d - moves[i];
            if (s < 0 || 44 < s) continue;
            int s16 = s % 16;
            if (s16 == 0 && d16 == 12) continue;
            if (s16 == 12 && d16 == 0) continue;
            srcs[ns] = s;
            k0s[ns] = (int)k;
            promo[ns++] = 0;
        }
        if (k == CHICKEN2 && d16 == 0) {
            srcs[ns] = d + 4;
            k0s[ns] = CHICK2;
            promo[ns++] = 1;
        }
    }
    for (int j = 0; j < ns; j++) {
        int s = srcs[j];
        if (getKoma(nb, s)) continue;
        if ((g_xatt[k0s[j]][s / 4] >> L) & 1) continue;
        u_long b0 = base | ((u_long)k0s[j] << s);
        n = pcEmit(b0, promo[j] ? UK_PROMOTE : UK_MOVE, asz, side, out, kinds, aszs, sides, nn, n);
        for (int t = 0; t < 4; t++) {
            int c = UNMOVE_CAPTURED[t];
            int own_p = c == CHICKEN1 ? 54 : 52 + c * 2;
            u_long cnt = (b0 >> own_p) & 0b11;
            if (!cnt) continue;
            u_long b1 = (b0 ^ ((cnt == 2 ? (u_long)0b11 : (u_long)0b01) << own_p)) | ((u_long)c << d);
            n = pcEmit(b1, promo[j] ? UK_PROMOTE_CAPTURE : UK_CAPTURE, asz, side, out, kinds, aszs, sides, nn, n);
        }
    }
    return n;
}

static int pcRaw(u_long nb, int side, u_long *out, uint8_t *kinds, uint8_t *aszs, uint8_t *sides, int *nn, int n) {
    int L;
    unsigned a = pruneChecks(nb, &L);
    int asz = __builtin_popcount(a);
    if (asz >= 2) return n;
    if (asz == 1) return pcPiece(nb, 4 * __builtin_ctz(a), L, asz, side, out, kinds, aszs, sides, nn, n);
    for (int d = 0; d < 48; d += 4) {
        if (!(getKoma(nb, d) & 0b1000)) continue;
        n = pcPiece(nb, d, L, asz, side, out, kinds, aszs, sides, nn, n);
    }
    return n;
}

int unmovePrunedCounted(u_long q, u_long *out, uint8_t *kinds, uint8_t *aszs, uint8_t *sides, int *nonnormal) {
    pruneTableBuild();
    *nonnormal = 0;
    int n = pcRaw(q, 0, out, kinds, aszs, sides, nonnormal, 0);
    u_long m = unmoveMirror(q);
    if (m != q) n = pcRaw(m, 1, out, kinds, aszs, sides, nonnormal, n);
    return n;
}
