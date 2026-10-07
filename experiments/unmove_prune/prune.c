// 逆向きの生成器で, キャッチ局面になる前任を作る前に捨てる (実験 unmove_prune。記録試行ではない)
//
// experiments/unmove_catch/catch.c (試作の後退解析 catchStep と B2. 書き換えずに使う) を取り込む. catch.c は
// experiments/unmove_bench/unmove.c (素朴な版の逆向きの生成器) を, unmove.c は impl/33_hot_layout/animal_shogi.c を
// 取り込むので, 素朴な版と絞った版, 試作の後退解析の1段が同じ翻訳単位に入る.
//
// ---- 考え方 (README に詳しく書いた) -----------------------------------------------------------
// 手を指した直後の盤 nb (q か, その鏡像) では, 直前に指した側 X の駒が 9〜13, q の手番側 Y の駒が 1〜5.
// 手を1つ戻した盤 b' も同じ向きで, 前任 p = invBoard(b'). p をいまの生成器に通すと, p を反転した盤 (= b') の上で
// X の駒 (9〜13) を動かし, Y のライオン (LION1) のマスへ動ける手があれば 0 (キャッチ) を返す.
// だから「p がキャッチ局面か」は「b' で X の駒が LION1 のマスに利くか」. 利きの規則はいまの生成器の手の規則そのまま:
//   X の駒 k がマス s から s + m へ (m は移動表の値. 0〜44 の外と, 回り込みの2条件
//   (s % 16 == 0 かつ 行き先 % 16 == 12 / s % 16 == 12 かつ 行き先 % 16 == 0) を捨てる).
//   X のひよこ (CHICK2) は s − 4 へ. s % 16 == 0 なら動けない.
// どの駒も1マスしか動かないので, X の駒を1つ戻しても X のほかの駒の利きは変わらない. 取った駒を戻しても
// それは Y の駒で, Y のライオンは取られていないので位置も変わらない. そこで nb ごとに1回,
//   A = { LION1 のマス L に利いている X の駒のマス }
// (A は集合の記号で, 盤の列 A〜C とは関係ない. q で Y に王手をかけている X の駒のマスの集まり)
// を作り, マス d の駒を戻す手は「A から d を除いて空」のときだけ作る (打った手を戻すのも同じ).
// さらに, 駒 k0 (成りを戻すならひよこ) を s へ戻す手は, s の k0 が L に利くなら作らない.
// A が2マス以上なら, どの駒を戻しても A は空にならないので, nb から前任は1つも出ない.

#include "catch.c"

// X の駒 k (9〜13) がマス sq にいるとき利くマスの集合 (12ビット. マス番号 = 番地 / 4). Y の駒と空きは 0
static uint16_t g_xatt[16][12];
static int g_xatt_ready = 0;

static void pruneTableBuild(void) {
    static const int *const tables[4] = {GIRAFFE_MOVE, ELEPHANT_MOVE, LION_MOVE, CHICKEN2_MOVE};
    static const int sizes[4] = {4, 4, 8, 6};
    static const int owners[4] = {GIRAFFE2, ELEPHANT2, LION2, CHICKEN2};
    if (g_xatt_ready) return;
    memset(g_xatt, 0, sizeof g_xatt);
    for (int s = 0; s < 48; s += 4) {
        int s16 = s % 16;
        for (int t = 0; t < 4; t++)
            for (int i = 0; i < sizes[t]; i++) {
                int dst = s + tables[t][i];
                if (dst < 0 || 44 < dst) continue;
                if (s16 == 0 && dst % 16 == 12) continue;
                if (s16 == 12 && dst % 16 == 0) continue;
                g_xatt[owners[t]][s / 4] |= (uint16_t)(1u << (dst / 4));
            }
        if (s16 != 0) g_xatt[CHICK2][s / 4] |= (uint16_t)(1u << ((s - 4) / 4));
    }
    g_xatt_ready = 1;
}

// nb の A (LION1 に利いている X の駒のマスの集合) と, LION1 のマス
static inline __attribute__((always_inline)) unsigned pruneChecks(u_long nb, int *lsq) {
    int L = rankFindKoma(nb & 0xffffffffffffUL, LION1);
    unsigned a = 0;
    for (int sq = 0; sq < 12; sq++) a |= ((g_xatt[getKoma(nb, 4 * sq)][sq] >> L) & 1u) << sq;
    *lsq = L;
    return a;
}

// 候補ごとの判定 (分類する版だけが使う). 下位2ビットが捨てる理由, 3ビット目が「戻した先から利く」
enum { PR_KEEP = 0, PR_MULTI = 1, PR_OTHER = 2, PR_DEST = 3, PR_DEST_FLAG = 4 };

// 戻した盤 b' から p を作り, 正規形なら out に足す (unmove.c の unmoveEmit と同じ. 判定と A の大きさも残す)
static inline __attribute__((always_inline)) int pruneEmit(u_long bp, int kind, int code, int asz, u_long *out,
                                                           uint8_t *kinds, uint8_t *codes, uint8_t *aszs, int n) {
    u_long p = invBoard(bp);
    if (normalBoard(p) != p) return n;
    if (kinds) kinds[n] = (uint8_t)kind;
    if (codes) codes[n] = (uint8_t)code;
    if (aszs) aszs[n] = (uint8_t)asz;
    out[n] = p;
    return n + 1;
}

// マス d の駒の手を全部戻す. 本体は unmove.c の unmoveRaw のループの中身の写しで, 足したのは判定だけ.
// classify が 0 なら捨てる候補を作らない (絞った版). 1 なら全部作って理由を codes に残す (一致の検査用)
static inline __attribute__((always_inline)) int prunePiece(u_long nb, int d, int unit, int L, int asz, int classify,
                                                            u_long *out, uint8_t *kinds, uint8_t *codes,
                                                            uint8_t *aszs, int n) {
    u_long k = getKoma(nb, d);
    u_long base = delKoma(nb, d);
    int d16 = d % 16;
    if (k == CHICK2 || k == GIRAFFE2 || k == ELEPHANT2) {
        int own_p = 54 + (int)(k - CHICK2) * 2;
        u_long c = (nb >> own_p) & 0b11;
        if (c < 2)
            n = pruneEmit(base ^ ((c ? (u_long)0b11 : (u_long)0b01) << own_p), UK_DROP, unit, asz, out, kinds, codes,
                          aszs, n);
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
        int dest = (g_xatt[k0s[j]][s / 4] >> L) & 1;
        if (!classify && dest) continue;  // 戻した先 s から LION1 に利く: 前任はキャッチ局面
        int code = unit ? unit | (dest ? PR_DEST_FLAG : 0) : dest ? PR_DEST : PR_KEEP;
        u_long b0 = base | ((u_long)k0s[j] << s);
        n = pruneEmit(b0, promo[j] ? UK_PROMOTE : UK_MOVE, code, asz, out, kinds, codes, aszs, n);
        for (int t = 0; t < 4; t++) {
            int c = UNMOVE_CAPTURED[t];
            int own_p = c == CHICKEN1 ? 54 : 52 + c * 2;
            u_long cnt = (b0 >> own_p) & 0b11;
            if (!cnt) continue;
            u_long b1 = (b0 ^ ((cnt == 2 ? (u_long)0b11 : (u_long)0b01) << own_p)) | ((u_long)c << d);
            n = pruneEmit(b1, promo[j] ? UK_PROMOTE_CAPTURE : UK_CAPTURE, code, asz, out, kinds, codes, aszs, n);
        }
    }
    return n;
}

static inline __attribute__((always_inline)) int pruneRaw(u_long nb, int classify, u_long *out, uint8_t *kinds,
                                                          uint8_t *codes, uint8_t *aszs, int *asz_out, int n) {
    int L;
    unsigned a = pruneChecks(nb, &L);
    int asz = __builtin_popcount(a);
    if (asz_out) *asz_out = asz;
    if (!classify) {
        // 局面と駒の単位: A が2マス以上なら前任は無い. 1マスなら, そのマスの駒だけを戻す
        if (asz >= 2) return n;
        if (asz == 1) return prunePiece(nb, 4 * __builtin_ctz(a), 0, L, asz, 0, out, kinds, codes, aszs, n);
    }
    for (int d = 0; d < 48; d += 4) {
        if (!(getKoma(nb, d) & 0b1000)) continue;
        int unit = (a & ~(1u << (d / 4))) ? (asz >= 2 ? PR_MULTI : PR_OTHER) : PR_KEEP;
        n = prunePiece(nb, d, unit, L, asz, classify, out, kinds, codes, aszs, n);
    }
    return n;
}

// 1'. 絞った版の候補 (ふるう前). 素朴な版 (unmoveCandidates) の候補のうち, キャッチ局面になるものを作らない
int unmovePrunedCandidates(u_long q, u_long *out, uint8_t *kinds) {
    pruneTableBuild();
    int n = pruneRaw(q, 0, out, kinds, NULL, NULL, NULL, 0);
    u_long m = unmoveMirror(q);
    if (m != q) n = pruneRaw(m, 0, out, kinds, NULL, NULL, NULL, n);
    return n;
}

// 一致の検査用: 素朴な版と同じ候補を同じ順で全部作り, 候補ごとに捨てる理由 (codes) と, その候補を作った盤の
// A の大きさ (aszs) を残す. *asz_q / *asz_m は q と鏡像の A の大きさ (q が左右対称なら鏡像は -1)
int unmoveClassify(u_long q, u_long *out, uint8_t *kinds, uint8_t *codes, uint8_t *aszs, int *asz_q, int *asz_m) {
    pruneTableBuild();
    int n = pruneRaw(q, 1, out, kinds, codes, aszs, asz_q, 0);
    u_long m = unmoveMirror(q);
    *asz_m = -1;
    if (m != q) n = pruneRaw(m, 1, out, kinds, codes, aszs, asz_m, n);
    return n;
}

// 2'. 絞った版の候補をふるう (unmove.c の unmoveSieved と同じ形)
int unmovePrunedSieved(u_long q, u_long *out, uint8_t *kinds, const uint8_t *cls) {
    u_long cand[UNMOVE_MAX];
    uint8_t ck[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmovePrunedCandidates(q, cand, kinds ? ck : NULL), m = 0;
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

// 3'. 2' に加えて, 残った前任ごとに 1 バイトの状態を1回読んで1回書く (unmove.c の unmoveVisit と同じ形)
int unmovePrunedVisit(u_long q, const uint8_t *cls, uint8_t *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmovePrunedCandidates(q, cand, NULL), m = 0;
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

// 試作の後退解析の1段の, 絞った版. catch.c の catchStep の写しで, 違いは逆向きの生成器
// (unmoveCandidates → unmovePrunedCandidates) だけ
int pruneStep(const u_long *frontier, size_t n, int odd, uint8_t nd, const uint8_t *cls, uint8_t *dtm, uint8_t *cnt,
              u_long *found, size_t found_cap, CatchStepStats *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    size_t nf = 0;
    for (size_t i = 0; i < n; i++) {
        int nc = unmovePrunedCandidates(frontier[i], cand, NULL), m = 0;
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
