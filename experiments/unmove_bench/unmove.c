// 一手前の局面 (前任) を直接作る生成器 (実験 unmove_bench。記録試行ではない)
//
// impl/33_hot_layout の animal_shogi.c をそのまま取り込み (build_so.sh が写す), 同じ翻訳単位に置く.
// ランクの表 (g_rank_*) と rankOf() は static なので, 外から呼ぶにはここに置くしかない.
// 本番と同じ gcc 行で .so にし, bench.c が dlopen して呼ぶ.
//
// ---- いまの生成器 (nextBoardInvNormal) の規約 -------------------------------------------
// 局面 p (手番側の駒が 1〜5, 手番側の持ち駒が bit 48〜53) を invBoard() で反転し (b'), 手番側の駒
// (9〜13. 所有者ビット 0b1000) を動かした盤 nb を normalBoard() に通したものが後続 q になる.
// nb ではもう反転しないので, q では「直前に指した側」の駒が 9〜13, その持ち駒が bit 54〜59 にある.
// だから前任は, q (と左右の鏡像) の上で 9〜13 の駒の手を1つ戻した盤 b' を作り, p = invBoard(b') とすればよい.
//
// ---- 正規化と重複 (README に詳しく書いた) ---------------------------------------------
// q = normalBoard(nb) なので, 手を指した直後の盤 nb は q か, q の鏡像のどちらか (q が左右対称なら q だけ).
// その両方から手を戻し, 戻した p が正規形 (normalBoard(p) == p) のものだけを残す.
// 正規形でない p の組は, 鏡像の側 (鏡像の nb から鏡像の手を戻した組) と1対1に重なるので捨てる.
// こうすると, 残る (nb, 戻した手) の組と, いまの生成器の (p, 手) の組がちょうど1対1になる.
// p が q を何回生むかの重複は, 戻した手の数としてそのまま数えられる.

#include "animal_shogi.c"

#include <sys/mman.h>

#define UNMOVE_MAX 1024

// 戻した手の種類 (一致の検査の内訳と, 食い違いの分類に使う)
enum UnmoveKind { UK_MOVE, UK_CAPTURE, UK_DROP, UK_PROMOTE, UK_PROMOTE_CAPTURE, UK_KINDS };

static const int UNMOVE_CAPTURED[4] = {CHICK1, CHICKEN1, GIRAFFE1, ELEPHANT1};

// 列を左右に反転する (normalBoard の入れ替えを無条件に行う)
static inline u_long unmoveMirror(u_long b) {
    return ((b >> 48) << 48) | ((b & 0xffff) << 32) | (b & 0xffff0000UL) | ((b >> 32) & 0xffff);
}

// 戻した盤 b' から p を作り, 正規形なら out に足す. kinds が NULL でなければ種類も残す
static inline int unmoveEmit(u_long bp, int kind, u_long *out, uint8_t *kinds, int n) {
    u_long p = invBoard(bp);
    if (normalBoard(p) != p) return n;
    if (kinds) kinds[n] = (uint8_t)kind;
    out[n] = p;
    return n + 1;
}

// 手を指した直後の盤 nb から, 直前の手を全部戻す. 返り値は out に足した後の件数
static int unmoveRaw(u_long nb, u_long *out, uint8_t *kinds, int n) {
    for (int d = 0; d < 48; d += 4) {
        u_long k = getKoma(nb, d);
        if (!(k & 0b1000)) continue;
        u_long base = delKoma(nb, d);
        int d16 = d % 16;
        // 持ち駒を打った (ひよこ・きりん・ぞう). 打ったあとの数が 0 なら 1 に, 1 なら 2 に戻す
        if (k == CHICK2 || k == GIRAFFE2 || k == ELEPHANT2) {
            int own_p = 54 + (int)(k - CHICK2) * 2;
            u_long c = (nb >> own_p) & 0b11;
            if (c < 2) n = unmoveEmit(base ^ ((c ? (u_long)0b11 : (u_long)0b01) << own_p), UK_DROP, out, kinds, n);
        }
        // 駒を動かした. (元の駒, 元のマス, 成りか) を並べる
        int srcs[10], k0s[10], promo[10], ns = 0;
        if (k == CHICK2) {
            // 成らない前進: 行き先が端 (d16 == 0) でなく, 元のマスが同じ列にある (d16 != 12)
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
                // いまの生成器が捨てている手 (列をまたいで端から端へ回り込む手) は戻さない
                if (s16 == 0 && d16 == 12) continue;
                if (s16 == 12 && d16 == 0) continue;
                srcs[ns] = s;
                k0s[ns] = (int)k;
                promo[ns++] = 0;
            }
            // にわとりが端の行にいれば, ひよこが1つ前のマスから進んで成った手もありうる
            if (k == CHICKEN2 && d16 == 0) {
                srcs[ns] = d + 4;
                k0s[ns] = CHICK2;
                promo[ns++] = 1;
            }
        }
        for (int j = 0; j < ns; j++) {
            int s = srcs[j];
            if (getKoma(nb, s)) continue;  // 元のマスは空いていなければならない
            u_long b0 = base | ((u_long)k0s[j] << s);
            n = unmoveEmit(b0, promo[j] ? UK_PROMOTE : UK_MOVE, out, kinds, n);
            // 駒を取った: 取った駒は直前に指した側の持ち駒 (bit 54〜59) に入っている.
            // ひよことにわとりはどちらも bit 54 に入る. 取ったあとの数が 1 なら 0 に, 2 なら 1 に戻す
            for (int t = 0; t < 4; t++) {
                int c = UNMOVE_CAPTURED[t];
                int own_p = c == CHICKEN1 ? 54 : 52 + c * 2;
                u_long cnt = (b0 >> own_p) & 0b11;
                if (!cnt) continue;
                u_long b1 = (b0 ^ ((cnt == 2 ? (u_long)0b11 : (u_long)0b01) << own_p)) | ((u_long)c << d);
                n = unmoveEmit(b1, promo[j] ? UK_PROMOTE_CAPTURE : UK_CAPTURE, out, kinds, n);
            }
        }
    }
    return n;
}

// 1. 前任の候補 (ふるう前). 正規形の p だけを出す. kinds は NULL でよい
int unmoveCandidates(u_long q, u_long *out, uint8_t *kinds) {
    int n = unmoveRaw(q, out, kinds, 0);
    u_long m = unmoveMirror(q);
    if (m != q) n = unmoveRaw(m, out, kinds, n);
    return n;
}

// ランクを外から引く口 (表は rankRange() が作る)
u_long unmoveRank(u_long b) {
    return rankOf(b);
}

// 2. 候補をふるう: 未知局面 (cls[rank] == 1) だけを残す. cls は到達しない局面が 0,
//    未知 1, キャッチ 2, トライ負け 3 (bench.c が全局面をいまの生成器に通して作る).
//    ランクを先に全部出して cls の行を取り寄せてから, 順に見る (#20 / #30 と同じ形)
int unmoveSieved(u_long q, u_long *out, uint8_t *kinds, const uint8_t *cls) {
    u_long cand[UNMOVE_MAX];
    uint8_t ck[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmoveCandidates(q, cand, kinds ? ck : NULL), m = 0;
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

// 3. 2 に加えて, 残った前任ごとにランクを添字にした 1 バイトの状態を1回読んで1回書く
//    (作り替えた後退解析で, 前任の残りの後続の数を1つ減らすのに当たる). 返り値は残った前任の数
int unmoveVisit(u_long q, const uint8_t *cls, uint8_t *st) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    int n = unmoveCandidates(q, cand, NULL), m = 0;
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

// 換算用: 出次数を全探索で数えて持ち越す案の費用. 局面ごとにランクを出し, 1 バイトを書くだけ
// (後続の数 n はいまの生成器がすでに返しているので, 足すのはこの書き込み)
void unmoveDegWrite(const u_long *ps, const int *ns, size_t count, uint8_t *st) {
    for (size_t i = 0; i < count; i++) {
        if (i + 8 < count) __builtin_prefetch(&st[rankOf(ps[i + 8])], 1, 3);
        st[rankOf(ps[i])] = (uint8_t)ns[i];
    }
}
