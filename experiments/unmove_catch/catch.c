// キャッチ局面への手を, 残りの後続の数から最初に外す (実験 unmove_catch。記録試行ではない)
//
// experiments/unmove_bench/unmove.c (逆向きの生成器。素朴な版のまま) を取り込む. unmove.c は
// impl/33_hot_layout/animal_shogi.c を取り込むので, 前向きの生成器・ランク・逆向きの生成器が同じ翻訳単位に入る.
// build_so.sh が impl/33 と unmove_bench から写して, impl/33 の Makefile の gcc 行のまま .so にする.
//
// ここに置くもの:
//   A. 試作の後退解析の1段 (catchStep) と, 残りの後続の数を数える口 (B2 と同じ数え方)
//   B1. 全探索で後続を作るその場で, その後続がキャッチ局面かを見分ける前向きの生成器 (nextBoardCountNonCatch)
//   B2. 全探索のあとで数え直す: 前向きの生成器を回し, 後続のランクで cls を引いてキャッチ局面を除く (countNonCatchB2)

#include "unmove.c"

// ---- B1: 手を指した直後の盤で, 相手が指した側のライオンを取れるか ------------------------------
//
// いまの生成器 (nextBoardInvNormal) は, 後続 q を受け取ると反転した盤の上で「手番側の駒 (9〜13) が
// LION1 のマスへ動けるか」を見て, 動けたら 0 (キャッチ) を返す. 後続 q の手番側は, 手を指した直後の盤 nb では
// 所有者ビットが 0 の駒 (1〜5), 指した側のライオンは LION2 (12).
// 反転はマス a を 44 − a へ移すので, 反転した盤で「元のマス s' から移動量 m で L' へ」は,
// nb では「s から L = s − m へ」(m の符号が逆) になる. 回り込みを捨てる2つの条件
// (s' % 16 == 0 かつ L' % 16 == 12 / s' % 16 == 12 かつ L' % 16 == 0) は, 反転すると
// (s % 16 == 12 かつ L % 16 == 0 / s % 16 == 0 かつ L % 16 == 12) で, 同じ組み合わせになる.
// ひよこ (反転した盤では -4 だけ進み, s' % 16 == 0 なら動けない) は, nb では L = s + 4 で, s % 16 != 12.
//
// だから, nb の LION2 のマス L の8近傍 s (= L + o) に所有者ビット 0 の駒 k があり,
// 移動量 m = s − L = o が k の移動表 (反転した盤での表) に入っていればキャッチ.
// 表は ATTACK_MASK[k] の8ビット (o の並びは CATCH_OFFSETS の順).

static const int CATCH_OFFSETS[8] = {-20, -16, -12, -4, 4, 12, 16, 20};

// k (1〜5) が, 位置の差 o = s − L のとき L へ動けるか. いまの生成器の移動表から作る
static uint8_t g_attack_mask[16];
static int g_attack_ready = 0;

static void catchAttackBuild(void) {
    static const int *const tables[4] = {GIRAFFE_MOVE, ELEPHANT_MOVE, LION_MOVE, CHICKEN2_MOVE};
    static const int sizes[4] = {4, 4, 8, 6};
    static const int owners[4] = {GIRAFFE1, ELEPHANT1, LION1, CHICKEN1};
    if (g_attack_ready) return;
    memset(g_attack_mask, 0, sizeof g_attack_mask);
    for (int t = 0; t < 4; t++)
        for (int i = 0; i < sizes[t]; i++)
            for (int j = 0; j < 8; j++)
                if (CATCH_OFFSETS[j] == tables[t][i]) g_attack_mask[owners[t]] |= (uint8_t)(1u << j);
    // ひよこ: 反転した盤では src - 4 へ進む. nb では L = s + 4, つまり o = s − L = −4
    for (int j = 0; j < 8; j++)
        if (CATCH_OFFSETS[j] == -4) g_attack_mask[CHICK1] |= (uint8_t)(1u << j);
    g_attack_ready = 1;
}

// 手を指した直後の盤 nb (正規化の前でも後でもよい. 左右の反転でキャッチかどうかは変わらない) が,
// 次の手番側にとってキャッチ局面か
static inline int catchAfterMove(u_long nb) {
    int L = rankFindKoma(nb & 0xffffffffffffUL, LION2) * 4;
    int L16 = L % 16;
    for (int j = 0; j < 8; j++) {
        int s = L + CATCH_OFFSETS[j];
        if (s < 0 || 44 < s) continue;
        int s16 = s % 16;
        if (s16 == 12 && L16 == 0) continue;
        if (s16 == 0 && L16 == 12) continue;
        u_long k = getKoma(nb, s);
        if (!k || (k & 0b1000)) continue;
        if (k == CHICK1 && s16 == 12) continue;  // いまの生成器: 反転した盤の端の行のひよこは動けない
        if (g_attack_mask[k] & (1u << j)) return 1;
    }
    return 0;
}

// B1: いまの生成器と同じ後続を同じ順で作り, キャッチ局面でない後続の数を *non_catch に入れる.
// 本体は nextBoardInvNormal の写しで, 違いは後続を積むところで catchAfterMove() を足したことだけ
int nextBoardCountNonCatch(u_long b, u_long *nbs, int *non_catch) {
    u_long nb, koma, dst_koma, x;
    int i, j, dst, own_num, own_p, *moves = NULL, moves_num, src_mod16, dst_mod16;
    int emp_adrs[10];
    int emp_num = 0;
    int nbs_p = 0;
    int nc = 0;
    int try_flag = 0;
    catchAttackBuild();
    *non_catch = 0;
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
            if (dst % 16 == 0) {
                koma = CHICKEN2;
            }
            x = nb | (koma << dst);
            nc += !catchAfterMove(x);
            nbs[nbs_p++] = normalBoard(x);
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
                x = nb | (koma << dst);
                nc += !catchAfterMove(x);
                nbs[nbs_p++] = normalBoard(x);
            }
        }
    }
    if (try_flag) return -1;
    for (i = 0; i < 3; i++) {
        own_p = 54 + i * 2;
        own_num = (b >> own_p) & 0b11;
        if (!own_num) continue;
        nb = b ^ (own_num == 2 ? (u_long)0b11 << own_p : (u_long)0b01 << own_p);
        koma = i + 9;
        for (j = 0; j < emp_num; j++) {
            x = nb | (koma << emp_adrs[j]);
            nc += !catchAfterMove(x);
            nbs[nbs_p++] = normalBoard(x);
        }
    }
    *non_catch = nc;
    return nbs_p;
}

// ---- B2: 全探索のあとで数え直す ----------------------------------------------------------------
// 前向きの生成器を回し, 後続のランクで cls (0 到達しない / 1 未知 / 2 キャッチ / 3 トライ負け) を引き,
// キャッチ局面でない後続を数える. 戻り値は生成器の戻り値 (正なら後続の数), *non_catch にキャッチ抜きの数
int countNonCatchB2(u_long p, const uint8_t *cls, int *non_catch) {
    u_long nbs[MAX_ACTION_NUM];
    uint64_t r[MAX_ACTION_NUM];
    int n = nextBoardInvNormal(p, nbs), nc = 0;
    *non_catch = 0;
    if (n <= 0) return n;
    for (int i = 0; i < n; i++) {
        r[i] = rankOf(nbs[i]);
        __builtin_prefetch(&cls[r[i]], 0, 3);
    }
    for (int i = 0; i < n; i++) nc += cls[r[i]] != 2;
    *non_catch = nc;
    return n;
}

// ---- A: 試作の後退解析の1段 --------------------------------------------------------------------
//
// いまの174段ループ (retreatStep) と同じ規則を, ランクを添字にした配列の上で, 逆向きの生成器でたどる.
//   dtm[r]: 手数. 255 が未定. 奇数が勝ち, 偶数が負け (いまの dtm と同じ)
//   cnt[r]: 未知局面の残りの後続の数 (版によって, 重複込みの出次数か, キャッチ抜きの数)
// frontier は手数 nd − 1 で決まった局面 q の値. odd が真なら q は勝ち (前任の残りを1つ減らし, 0 になったら
// 負けで手数 nd), 偽なら q は負け (前任は勝ちで手数 nd). 決まった前任の値を found に足す.
// 候補はふるい (cls == 1 の未知局面だけ) にかけてから使う. ふるいで捨てた候補の理由を drop[cls] に数える.
typedef struct {
    uint64_t expanded, candidates, kept, drop[4], found;
} CatchStepStats;

int catchStep(const u_long *frontier, size_t n, int odd, uint8_t nd, const uint8_t *cls, uint8_t *dtm,
              uint8_t *cnt, u_long *found, size_t found_cap, CatchStepStats *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    size_t nf = 0;
    for (size_t i = 0; i < n; i++) {
        int nc = unmoveCandidates(frontier[i], cand, NULL), m = 0;
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
                if (cnt[rr] == 0) return -4;  // 0 から減らした (残りの数が実際の後続より少ない)
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
