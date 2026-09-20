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

// ---- 全探索の発見済み集合 (記録 #11) --------------------------------------
//
// オープンアドレス法 + 線形探査. キーだけの 8 B 配列で, 空きは INDEX_EMPTY.
// 索引 (g_index) とは別の表で, 同時に生きることはない
// (全探索が終わって seenFree してから後退解析が indexBuild する).

static u_long *g_seen = NULL;
static size_t g_seen_slots = 0;
static size_t g_seen_mask = 0;
// 乗算ハッシュの上位ビットを取るためのシフト量 (64 - ビット幅)
static int g_seen_shift = 0;
static u_long g_seen_n = 0;
static u_long g_seen_probes = 0;
static u_long g_seen_rehashes = 0;

#define SEEN_SLOT(key) ((size_t)(((u_long)(key) * INDEX_MULT) >> g_seen_shift))

void seenFree(void) {
    free(g_seen);
    g_seen = NULL;
    g_seen_slots = 0;
    g_seen_mask = 0;
    g_seen_shift = 0;
    g_seen_n = 0;
    g_seen_probes = 0;
    g_seen_rehashes = 0;
}

int seenInit(void) {
    size_t slots = (size_t)1 << SEEN_MIN_BITS;
    seenFree();
    g_seen = (u_long *)aligned_alloc(64, slots * sizeof(u_long));
    if (!g_seen) return -3;
    // 0xff で埋めると全スロットが INDEX_EMPTY になる
    memset(g_seen, 0xff, slots * sizeof(u_long));
    g_seen_slots = slots;
    g_seen_mask = slots - 1;
    g_seen_shift = 64 - SEEN_MIN_BITS;
    return 0;
}

// 占有率が 0.5 を超えたら倍にして詰め直す
static int seenGrow(void) {
    u_long *old = g_seen;
    size_t old_slots = g_seen_slots;
    size_t i, slot, slots;
    int bits = (64 - g_seen_shift) + 1;
    if (bits > SEEN_MAX_BITS) return -3;
    slots = (size_t)1 << bits;
    g_seen = (u_long *)aligned_alloc(64, slots * sizeof(u_long));
    if (!g_seen) {
        g_seen = old;
        return -3;
    }
    memset(g_seen, 0xff, slots * sizeof(u_long));
    g_seen_slots = slots;
    g_seen_mask = slots - 1;
    g_seen_shift = 64 - bits;
    for (i = 0; i < old_slots; i++) {
        if (old[i] == INDEX_EMPTY) continue;
        slot = SEEN_SLOT(old[i]);
        while (g_seen[slot] != INDEX_EMPTY) slot = (slot + 1) & g_seen_mask;
        g_seen[slot] = old[i];
    }
    free(old);
    g_seen_rehashes++;
    return 0;
}

int seenInsert(u_long key) {
    size_t slot;
    if (!g_seen && seenInit() != 0) return -3;
    // パック値は 60bit なので番兵と衝突しない. 壊れた入力はここで弾く
    if (key == INDEX_EMPTY) return -4;
    slot = SEEN_SLOT(key);
    for (;;) {
        if (g_seen[slot] == INDEX_EMPTY) break;
        if (g_seen[slot] == key) return 0;
        slot = (slot + 1) & g_seen_mask;
    }
    g_seen[slot] = key;
    g_seen_n++;
    if (g_seen_n * 2 > (u_long)g_seen_slots) {
        if (seenGrow() != 0) return -3;
    }
    return 1;
}

int seenInsertMany(const u_long *keys, uint32_t n) {
    uint32_t i;
    int rc;
    int added = 0;
    if (!keys) return -1;
    if (!g_seen && seenInit() != 0) return -3;
    for (i = 0; i < n; i++) {
        rc = seenInsert(keys[i]);
        if (rc < 0) return rc;
        added += rc;
    }
    return added;
}

u_long seenCount(void) {
    return g_seen_n;
}

int seenContains(u_long key) {
    size_t slot;
    if (!g_seen || key == INDEX_EMPTY) return 0;
    slot = SEEN_SLOT(key);
    for (;;) {
        if (g_seen[slot] == key) return 1;
        if (g_seen[slot] == INDEX_EMPTY) return 0;
        slot = (slot + 1) & g_seen_mask;
    }
}

u_long seenProbes(void) {
    return g_seen_probes;
}

u_long seenRehashes(void) {
    return g_seen_rehashes;
}

int nextBoardSeenNormal(u_long b, u_long *out) {
    u_long nbs[MAX_ACTION_NUM];
    int nbn, i, rc;
    int found = 0;
    if (!g_seen && seenInit() != 0) return -3;
    nbn = nextBoardInvNormal(b, nbs);
    // 0 = キャッチ勝ち / -1 = トライ負け. どちらも後続を持たない
    // ⚠️ ここで規約を付け替える. 「未知だが初見が0個」を 0 で返したいため
    if (nbn == 0) return -1;
    if (nbn < 0) return -2;
    g_seen_probes += (u_long)nbn;
    for (i = 0; i < nbn; i++) {
        rc = seenInsert(nbs[i]);
        if (rc < 0) return -3;
        // 初見だったものだけ返す. 既出は表に入っているので積む必要がない
        if (rc == 1) out[found++] = nbs[i];
    }
    return found;
}

// ---- 前任リストの計数ソート (記録 #12) ------------------------------------

int predCount(const uint32_t *succ, size_t n_edges, uint32_t n_all, uint32_t *pred_off) {
    size_t e;
    size_t i;
    size_t total = 0;
    uint32_t q;
    if (!pred_off || n_all == 0) return -1;
    // 辺が1本も無いと array("I") の buffer_info() が 0 を返す (小さいフィクスチャで起きる).
    // その場合だけポインタが NULL でもよい
    if (n_edges > 0 && !succ) return -1;
    memset(pred_off, 0, ((size_t)n_all + 1) * sizeof(uint32_t));
    for (e = 0; e < n_edges; e++) {
        q = succ[e];
        // 範囲外を書くと他の配列を壊す. Python 版は IndexError で落ちていたので,
        // ここでも落とす (1辺あたり比較1回)
        if (q >= n_all) return -2;
        pred_off[(size_t)q + 1]++;
    }
    // 前置和. 添字は size_t で持つ (値は 9.4 億で uint32 に収まる)
    for (i = 1; i <= (size_t)n_all; i++) {
        total += pred_off[i];
        pred_off[i] = (uint32_t)total;
    }
    if (total != n_edges) return -2;
    return 0;
}

int predScatter(const uint32_t *succ, size_t n_edges,
                const uint32_t *succ_off, uint32_t n_uk,
                uint32_t n_all, uint32_t *pred, uint32_t *pred_off) {
    size_t src;
    size_t e;
    size_t i;
    size_t lo;
    size_t hi;
    uint32_t q;
    if (!succ_off || !pred_off || n_all == 0) return -1;
    // 辺が無いときは succ と pred が NULL でもよい (predCount と同じ事情)
    if (n_edges > 0 && (!succ || !pred)) return -1;
    if ((size_t)succ_off[n_uk] != n_edges) return -2;
    for (src = 0; src < (size_t)n_uk; src++) {
        lo = succ_off[src];
        hi = succ_off[src + 1];
        if (hi < lo || hi > n_edges) return -2;
        for (e = lo; e < hi; e++) {
            q = succ[e];
            if (q >= n_all) return -2;
            // pred_off[q] をカーソルとして進める. あとで1つずらして戻す
            pred[pred_off[q]++] = (uint32_t)src;
        }
    }
    // カーソルとして進めたぶんを戻す. pred_off[i] には i-1 の終端が入っている
    for (i = (size_t)n_all; i > 0; i--) {
        pred_off[i] = pred_off[i - 1];
    }
    pred_off[0] = 0;
    return 0;
}

// ---- 1ラウンドぶんの展開 (記録 #13) ---------------------------------------
//
// #12 までは局面ごとに Python から nextBoardSeenNormal を呼んでいた.
// 246,803,167 回ぶんの FFI 越え・48要素バッファの確保・nba[:nbn] の list 生成が
// そのまま乗っていたので, ラウンドあたり1回の呼び出しにまとめる.

// 初見の後続を溜めるバッファ. ラウンドをまたいで使い回し, 縮めない
// (本番の最大は 1ラウンド 11,258,320 件 = 90 MB. 最悪値 n * 48 で固定すると
//  5,000,000 * 48 * 8 = 1.92 GB の空撃ちになるので, 倍々に伸ばす)
static u_long *g_exp_new = NULL;
static size_t g_exp_cap = 0;
static u_long g_exp_n = 0;

#define EXPAND_MIN_CAP ((size_t)1 << 20)

// need 要素が入るまで倍にする. 足りていれば比較1回で返る
static int expandReserve(size_t need) {
    size_t cap = g_exp_cap ? g_exp_cap : EXPAND_MIN_CAP;
    u_long *grown;
    if (need <= g_exp_cap) return 0;
    while (cap < need) {
        if (cap > SIZE_MAX / 2) return -2;
        cap *= 2;
    }
    if (cap > SIZE_MAX / sizeof(u_long)) return -2;
    grown = (u_long *)realloc(g_exp_new, cap * sizeof(u_long));
    if (!grown) return -2;
    g_exp_new = grown;
    g_exp_cap = cap;
    return 0;
}

const u_long *expandNewPtr(void) {
    return g_exp_new;
}

u_long expandNewCount(void) {
    return g_exp_n;
}

void expandFreeBuffer(void) {
    free(g_exp_new);
    g_exp_new = NULL;
    g_exp_cap = 0;
    g_exp_n = 0;
}

int expandRound(const u_long *unexp, uint32_t n,
                u_long *win, u_long *lose, u_long *uk, u_long *out) {
    uint32_t i = 0, n_win = 0, n_lose = 0, n_uk = 0;
    u_long probes0 = g_seen_probes;
    int nbn, rc = 0;
    if (!out) return -1;
    out[0] = out[1] = out[2] = out[3] = out[4] = 0;
    // 空のチャンクは起こりうる (searchNext が unexplored に set() を書く).
    // そのとき array("Q") の buffer_info() は 0 を返すので, NULL を許す
    // (predCount が n_edges == 0 でやっているのと同じ)
    if (n == 0) return 0;
    if (!unexp || !win || !lose || !uk) return -1;
    // ⚠️ 入口で 0 に戻す. 出口で戻すと, 途中で落ちたラウンドの残骸に
    //    次のラウンドが積み足してしまう
    g_exp_n = 0;
    // ⚠️ 前から後ろへ走査する. Python の set.pop() を繰り返した順は集合の反復順で,
    //    array("Q", 集合) の並びがちょうどそれ. 逆から回すと採番順が変わる
    for (i = 0; i < n; i++) {
        // 初見の後続は伸びるバッファの続きに直接書かせる. 中間バッファもコピーも要らない
        // (1局面の後続は MAX_ACTION_NUM 個まで. 呼ぶ前にそのぶんの空きを作っておく)
        // ⚠️ 確保できなければそこで終わり. このラウンドはやり直せない
        //    (そこまでの後続はもう表に入っていて, 呼び直すと「既出」になる).
        //    ただし expandRound はファイルを1つも書く前に走るので, dat/ は無傷.
        //    走行ごと落として再走すればよい (CLAUDE.md「再開ではなく再走」)
        if (expandReserve((size_t)g_exp_n + MAX_ACTION_NUM) != 0) {
            rc = -2;
            break;
        }
        nbn = nextBoardSeenNormal(unexp[i], g_exp_new + g_exp_n);
        // ⚠️ 分岐の順は件数の多い順 (勝ち 140,298,614 / 未知 99,485,568 /
        //    負け 7,018,985). 記録 #12 と同じ順序で判定する
        if (nbn == -1) {
            win[n_win++] = unexp[i];
        } else if (nbn >= 0) {
            uk[n_uk++] = unexp[i];
            g_exp_n += (u_long)nbn;
        } else if (nbn == -2) {
            lose[n_lose++] = unexp[i];
        } else {
            // ⚠️ 握りつぶさない (記録 #11 の不具合の家族).
            // -3 = 表を確保できない / -4 = 知らない戻り値 (こちらはバグ)
            rc = (nbn == -3) ? -3 : -4;
            break;
        }
    }
    out[0] = n_win;
    out[1] = n_lose;
    out[2] = n_uk;
    // 生成した後続の延べ数. Python 側の n_new_pre と突き合わせるための検算値
    out[3] = g_seen_probes - probes0;
    // 処理し終えた入力の数. 落ちたときにどの局面で止まったかが分かる
    out[4] = i;
    return rc;
}
