// キャッチ抜きの数を, 相手の利きの一覧で数える (実験 attack_count。記録試行ではない)
//
// experiments/unmove_catch/catch.c (B1・B2 と試作の後退解析。書き換えずに使う) を取り込む. catch.c は
// experiments/unmove_bench/unmove.c を, unmove.c は impl/33_hot_layout/animal_shogi.c を取り込むので,
// いまの生成器・B1 (unmove_catch)・B2 と, ここの B1′ が同じ翻訳単位に入る.
//
// ---- 一覧の考え方 ------------------------------------------------------------------------------
// いまの生成器は p を反転した盤 b の上で, 手番側の駒 (9〜13) を動かす. 後続 q がキャッチ局面か
// (q を生成器に通すと 0 が返るか) は, 手を指した直後の盤で「相手の駒 (1〜5) が手番側のライオン (LION2) のマスへ届くか」で決まる
// (unmove_catch の catchAfterMove と同じ写し方: 相手の駒がマス s から L = s − m へ届く. m は移動表の値.
//  回り込みを捨てる2条件 (s % 16 == 12 かつ L % 16 == 0 / s % 16 == 0 かつ L % 16 == 12).
//  相手のひよこは L = s + 4 で, s % 16 != 12).
// どの駒も1マスしか動かないので, 手番側が駒を動かしても相手の駒の利きは変わらない. 変わるのは, 相手の駒を
// 取ったときに, その駒の利きが消えることだけ. だから一覧は局面ごとに1回, 反転した盤 b の上で作ればよい.
//
// 一覧 (局面の頭, invBoard の直後に作る):
//   att1: 相手の駒が1つ以上届くマスの集合 (12ビット. マス番号 = 番地 / 4). 相手の駒がいるマスにも数える
//   atkL: 手番側のライオンのマス L に届いている相手の駒の, いるマスの集合
// 後続ごとの判定 (キャッチ局面になるか):
//   ライオンを dst へ動かす: dst が att1 に入っている (取る手でも同じ. 取られる駒は自分のマスには届かない)
//   ほかの駒を dst へ動かす: atkL から dst を除いて空でない (dst の相手の駒を取れば, その駒の利きが消える)
//   持ち駒を打つ: atkL が空でない
// 表 g_att[k][sq] は「相手の駒 k がマス sq にいるとき届くマスの集合」. いまの生成器の移動表から作る.

#include "catch.c"

static uint16_t g_att[16][12];
static int g_att_ready = 0;

static void attackTableBuild(void) {
    static const int *const tables[4] = {GIRAFFE_MOVE, ELEPHANT_MOVE, LION_MOVE, CHICKEN2_MOVE};
    static const int sizes[4] = {4, 4, 8, 6};
    static const int owners[4] = {GIRAFFE1, ELEPHANT1, LION1, CHICKEN1};
    if (g_att_ready) return;
    memset(g_att, 0, sizeof g_att);
    for (int s = 0; s < 48; s += 4) {
        int s16 = s % 16;
        for (int t = 0; t < 4; t++)
            for (int i = 0; i < sizes[t]; i++) {
                int L = s - tables[t][i];
                if (L < 0 || 44 < L) continue;
                if (s16 == 12 && L % 16 == 0) continue;
                if (s16 == 0 && L % 16 == 12) continue;
                g_att[owners[t]][s / 4] |= (uint16_t)(1u << (L / 4));
            }
        // ひよこ: L = s + 4. s % 16 == 12 のひよこは (反転した盤では端の行で) 動けない
        if (s16 != 12) g_att[CHICK1][s / 4] |= (uint16_t)(1u << ((s + 4) / 4));
    }
    g_att_ready = 1;
}

// 後続の種類 (一致の検査で, 食い違いを分けるため)
enum { AK_LION, AK_LION_CAPTURE, AK_LION_TRY, AK_MOVE, AK_CAPTURE, AK_PROMOTE, AK_DROP, AK_KINDS };

// B1′ の本体. いまの生成器 (nextBoardInvNormal) の写しに, 一覧づくりと後続ごとの判定を足した.
// flags / kinds が NULL でなければ, 後続ごとにキャッチ局面か (1/0) と手の種類を残す (一致の検査用)
static inline __attribute__((always_inline)) int attackCountCore(u_long b, u_long *nbs, int *non_catch,
                                                                   uint8_t *flags, uint8_t *kinds) {
    u_long nb, koma, dst_koma;
    int i, j, dst, own_num, own_p, *moves = NULL, moves_num, src_mod16, dst_mod16;
    int emp_adrs[10];
    int emp_num = 0;
    int nbs_p = 0;
    int nc = 0, c;
    int try_flag = 0;
    unsigned att1 = 0, atkL = 0;
    *non_catch = 0;
    b = invBoard(b);
    // 一覧: 相手の駒 (所有者ビット 0 の 1〜5) ごとに, 届くマスの集合を表から引いて重ねる
    {
        int Lsq = rankFindKoma(b & 0xffffffffffffUL, LION2);
        for (int sq = 0; sq < 12; sq++) {
            unsigned m = g_att[getKoma(b, 4 * sq)][sq];  // 空き (0) と手番側の駒 (9〜13) は表が 0
            att1 |= m;
            atkL |= ((m >> Lsq) & 1u) << sq;
        }
    }
    for (int src = 0; src < 48; src += 4) {
        if (!(koma = getKoma(b, src))) {
            emp_adrs[emp_num++] = src;
        } else if (koma == CHICK2) {
            if (src % 16 == 0) continue;
            dst = src - 4;
            if ((dst_koma = getKoma(b, dst))) {
                if (dst_koma & 0b1000) continue;
                if (dst_koma == LION1) return 0;
                nb = delKomaDouble(b, src, dst);
                own_p = dst_koma == CHICKEN1 ? 54 : 52 + dst_koma * 2;
                nb ^= (b >> own_p) & 0b11 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p;
            } else {
                nb = delKoma(b, src);
            }
            c = (atkL & ~(1u << (dst / 4))) != 0;
            if (kinds) kinds[nbs_p] = dst % 16 == 0 ? AK_PROMOTE : dst_koma ? AK_CAPTURE : AK_MOVE;
            if (dst % 16 == 0) {
                koma = CHICKEN2;
            }
            if (flags) flags[nbs_p] = (uint8_t)c;
            nc += !c;
            nbs[nbs_p++] = normalBoard(nb | (koma << dst));
        } else if (koma == LION1) {
            if (src % 16 == 12) try_flag = 1;
        } else {
            switch (koma) {
                case GIRAFFE2: moves = GIRAFFE_MOVE; moves_num = 4; break;
                case ELEPHANT2: moves = ELEPHANT_MOVE; moves_num = 4; break;
                case LION2: moves = LION_MOVE; moves_num = 8; break;
                case CHICKEN2: moves = CHICKEN2_MOVE; moves_num = 6; break;
                default: moves_num = 0;
            }
            if (!moves_num) continue;
            src_mod16 = src % 16;
            for (i = 0; i < moves_num; i++) {
                dst = src + moves[i];
                if (dst < 0 || 44 < dst) continue;
                dst_mod16 = dst % 16;
                if (src_mod16 == 0 && dst_mod16 == 12) continue;
                if (src_mod16 == 12 && dst_mod16 == 0) continue;
                if ((dst_koma = getKoma(b, dst))) {
                    if (dst_koma & 0b1000) continue;
                    if (dst_koma == LION1) return 0;
                    nb = delKomaDouble(b, src, dst);
                    own_p = dst_koma == CHICKEN1 ? 54 : 52 + dst_koma * 2;
                    nb ^= (b >> own_p) & 0b11 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p;
                } else {
                    nb = delKoma(b, src);
                }
                if (koma == LION2) {
                    c = (att1 >> (dst / 4)) & 1u;
                    if (kinds) kinds[nbs_p] = dst_mod16 == 0 ? AK_LION_TRY : dst_koma ? AK_LION_CAPTURE : AK_LION;
                } else {
                    c = (atkL & ~(1u << (dst / 4))) != 0;
                    if (kinds) kinds[nbs_p] = dst_koma ? AK_CAPTURE : AK_MOVE;
                }
                if (flags) flags[nbs_p] = (uint8_t)c;
                nc += !c;
                nbs[nbs_p++] = normalBoard(nb | (koma << dst));
            }
        }
    }
    if (try_flag) return -1;
    c = atkL != 0;
    for (i = 0; i < 3; i++) {
        own_p = 54 + i * 2;
        own_num = (b >> own_p) & 0b11;
        if (!own_num) continue;
        nb = b ^ (own_num == 2 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p);
        koma = i + 9;
        for (j = 0; j < emp_num; j++) {
            if (flags) flags[nbs_p] = (uint8_t)c;
            if (kinds) kinds[nbs_p] = AK_DROP;
            nc += !c;
            nbs[nbs_p++] = normalBoard(nb | (koma << emp_adrs[j]));
        }
    }
    *non_catch = nc;
    return nbs_p;
}

// B1′: 計時に使う形 (後続の列と, キャッチ抜きの数)
int nextBoardCountNonCatchX(u_long b, u_long *nbs, int *non_catch) {
    attackTableBuild();
    return attackCountCore(b, nbs, non_catch, NULL, NULL);
}

// 一致の検査に使う形 (後続ごとのキャッチの判定と手の種類も残す)
int nextBoardCatchFlagsX(u_long b, u_long *nbs, int *non_catch, uint8_t *flags, uint8_t *kinds) {
    attackTableBuild();
    return attackCountCore(b, nbs, non_catch, flags, kinds);
}
