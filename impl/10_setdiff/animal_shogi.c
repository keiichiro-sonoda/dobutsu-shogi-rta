#include <stdio.h>
#include <stdlib.h>
#include "animal_shogi.h"

int GIRAFFE_MOVE[4] = {-16, -4, 4, 16};
int ELEPHANT_MOVE[4] = {-20, -12, 12, 20};
int LION_MOVE[8] = {-20, -16, -12, -4, 4, 12, 16, 20};
int CHICKEN2_MOVE[6] = {-20, -16, -4, 4, 12, 16};

int main(void) {
    int nbsn;
    u_long nbs[MAX_ACTION_NUM];
    u_long b0;
    b0 = SAMPLE_BOARD09;
    showBoard(invBoard(b0));
    nbsn = nextBoardInvNormal(b0, nbs);
    printf("%d\n", nbsn);
    for (int i = 0; i < nbsn; i++) {
        showBoard(nbs[i]);
    }
    return 0;
}

// 盤面表示
void showBoard(u_long b) {
    int i, j;
    u_char p, own_p, own_p_num;
    own_p = b >> 54;
    printf("0x%lx\n", b);
    printf("E: ");
    for (i = 0; i < 3; i++) {
        own_p_num = (own_p >> (i * 2)) & 0b11;
        for (j = 0; j < own_p_num; j++) {
            putchar(DISPLAY_PEACES[i + 1]);
            printf("2 ");
        }
    }
    putchar(10);
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 3; j++) {
            p = (b >> (44 - i * 4 - j * 16)) & 0b1111;
            putchar(DISPLAY_PEACES[p & 0b0111]);
            if (p & 0b1000) {
                putchar('2');
            } else if (p) {
                putchar('1');
            } else {
                putchar(' ');
            }
            putchar(' ');
        }
        putchar(10);
    }
    own_p = b >> 48;
    printf("D: ");
    for (i = 0; i < 3; i++) {
        own_p_num = (own_p >> (i * 2)) & 0b11;
        for (j = 0; j < own_p_num; j++) {
            putchar(DISPLAY_PEACES[i + 1]);
            printf("1 ");
        }
    }
    printf("\n---------------------------------------------\n");
}

// 先手後手入れ替え
u_long invBoard(u_long b) {
    u_long ib = 0;
    u_long koma, own1, own2;
    for (u_char i = 0; i < 48; i += 4) {
        if (!(koma = getKoma(b, i))) continue;
        ib = putKoma(ib, 44 - i, koma ^ 0b1000);
    }
    own1 = (b >> 48) & 0b111111;
    own2 = b >> 54;
    ib |= (own1 << 54) | (own2 << 48);
    return ib;
}

// 左右対称盤面は数値が小さい方だけ扱う
u_long normalBoard(u_long b) {
    u_long col_A, col_B, col_C;
    col_A = (b >> 32) & 0xffff;
    col_C = b & 0xffff;
    // 入れ替えた数値が元の数値以上の場合
    if (col_A <= col_C) return b;
    col_B = (b >> 16) & 0xffff;
    return ((b >> 48) << 48) | (col_C << 32) | (col_B) << 16 | col_A;
}

// 手番入れ替え, 左右対称を正規化して次の盤面の配列を作成
// 冒頭で反転し, 後手目線の手を指す
int nextBoardInvNormal(u_long b, u_long *nbs) {
    u_long nb, koma, dst_koma;
    int i, j, dst, own_num, own_p, *moves, moves_num, src_mod16, dst_mod16;
    int emp_adrs[10];
    int emp_num = 0;
    int nbs_p = 0;
    int try_flag = 0;
    b = invBoard(b);
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
            // 成り
            if (dst % 16 == 0) {
                koma = CHICKEN2;
            }
            nbs[nbs_p++] = normalBoard(nb | (koma << dst));
        }
        // トライ判定
        else if (koma == LION1) {
            if (src % 16 == 12) try_flag = 1;
        } else {
            switch (koma) {
                case GIRAFFE2:
                    moves = GIRAFFE_MOVE;
                    moves_num = 4;
                    break;
                case ELEPHANT2:
                    moves = ELEPHANT_MOVE;
                    moves_num = 4;
                    break;
                case LION2:
                    moves = LION_MOVE;
                    moves_num = 8;
                    break;
                case CHICKEN2:
                    moves = CHICKEN2_MOVE;
                    moves_num = 6;
                    break;
                default:
                    moves_num = 0;
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
                    // ライオンが取れるなら0を返して終了
                    if (dst_koma == LION1) return 0;
                    nb = delKomaDouble(b, src, dst);
                    own_p = dst_koma == CHICKEN1 ? 54 : 52 + dst_koma * 2;
                    nb ^= (b >> own_p) & 0b11 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p;
                } else {
                    nb = delKoma(b, src);
                }
                nbs[nbs_p++] = normalBoard(nb | (koma << dst));
            }
        }
    }
    if (try_flag) return -1;
    // 持ち駒の処理
    for (i = 0; i < 3; i++) {
        own_p = 54 + i * 2;
        own_num = (b >> own_p) & 0b11;
        if (!own_num) continue;
        nb = b ^ (own_num == 2 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p);
        koma = i + 9;
        for (j = 0; j < emp_num; j++) {
            nbs[nbs_p++] = normalBoard(nb | (koma << emp_adrs[j]));
        }
    }
    return nbs_p;
}

// パック値 -> 連番 の索引 (オープンアドレス法・線形探査)
static IndexEntry *g_index = NULL;
// Python 側の array('Q') をそのまま指す. indexFree までリサイズしてはいけない
static const u_long *g_packed = NULL;
static uint32_t g_index_n = 0;
static size_t g_index_mask = 0;
// 乗算ハッシュの右シフト量 (= 64 - スロット数のビット幅)
static int g_index_shift = 0;

#define INDEX_SLOT(key) ((size_t)(((u_long)(key) * INDEX_MULT) >> g_index_shift))

void indexFree(void) {
    free(g_index);
    g_index = NULL;
    g_packed = NULL;
    g_index_n = 0;
    g_index_mask = 0;
    g_index_shift = 0;
}

int indexBuild(const u_long *packed, uint32_t n) {
    size_t i, slot, slots;
    int bits;
    u_long key;
    if (!packed) return -1;
    // 占有率が 0.5 を超えないビット幅を選ぶ
    for (bits = INDEX_MIN_BITS; bits <= INDEX_MAX_BITS; bits++) {
        if (((size_t)1 << bits) >= (size_t)n * 2) break;
    }
    if (bits > INDEX_MAX_BITS) return -2;
    indexFree();
    slots = (size_t)1 << bits;
    // 64B 境界に揃えて確保する. エントリ (16 B) がキャッシュラインを跨がないため
    g_index = (IndexEntry *)aligned_alloc(64, slots * sizeof(IndexEntry));
    if (!g_index) return -3;
    g_index_mask = slots - 1;
    g_index_shift = 64 - bits;
    // 0xff で埋めると key が INDEX_EMPTY になる
    memset(g_index, 0xff, slots * sizeof(IndexEntry));
    for (i = 0; i < (size_t)n; i++) {
        key = packed[i];
        if (key == INDEX_EMPTY) {
            indexFree();
            return -4;
        }
        slot = INDEX_SLOT(key);
        for (;;) {
            if (g_index[slot].key == INDEX_EMPTY) {
                g_index[slot].key = key;
                g_index[slot].val = (uint32_t)i;
                break;
            }
            // 重複があると連番が全単射にならない (3群が互いに素であることの検算)
            if (g_index[slot].key == key) {
                indexFree();
                return -5;
            }
            slot = (slot + 1) & g_index_mask;
        }
    }
    g_packed = packed;
    g_index_n = n;
    return 0;
}

int nextBoardIndexNormal(uint32_t src, uint32_t *out) {
    u_long nbs[MAX_ACTION_NUM];
    u_long key;
    size_t slot;
    int nbn, i;
    int found = 0;
    if (!g_index || src >= g_index_n) return -3;
    nbn = nextBoardInvNormal(g_packed[src], nbs);
    // 0 = キャッチ / -1 = トライ負け. どちらも後続を持たない
    if (nbn <= 0) return nbn;
    for (i = 0; i < nbn; i++) {
        key = nbs[i];
        slot = INDEX_SLOT(key);
        for (;;) {
            if (g_index[slot].key == key) {
                out[found++] = g_index[slot].val;
                break;
            }
            // 番兵に当たったら索引外. 全探索を打ち切った dat/ でだけ起きる
            if (g_index[slot].key == INDEX_EMPTY) break;
            slot = (slot + 1) & g_index_mask;
        }
    }
    if (found != nbn) {
        out[MAX_ACTION_NUM] = (uint32_t)found;
        out[MAX_ACTION_NUM + 1] = (uint32_t)nbn;
        return -2;
    }
    return nbn;
}
