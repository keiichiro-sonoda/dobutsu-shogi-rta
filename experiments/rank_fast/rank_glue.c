// rankOf だけを回すベンチの入口 (実験 rank_fast。記録試行ではない)
//
// 腕の animal_shogi.c をそのまま取り込み (書き換えない), 入力を作る関数と rankOf を回す関数を足す.
// impl/38_precheck の Makefile の gcc 行のまま (入力と出力の名前だけ替えて) .so にする (build_bench.sh).
// rankOf は腕の static inline のまま, 下の rbThr / rbChain の中に展開される.
//
//   rbFwdOne     F1 の入力の局面1つから後続を作る (nextBoardInvNormalNC. 本物で rankOf に渡る盤)
//   rbUnmoveOne  U_loop の入力の局面1つから前任の候補を作る (unmoveCandidates. 本物で rankOf に渡る盤)
//   rbThr        x[0..n) の番号を reps 周出して和を返す. 呼び出しどうしは独立 (続けて回す)
//   rbChain      同じだが, 前の呼び出しの番号と mask の AND を次の盤に xor で混ぜる (鎖にして回す).
//                mask は呼び出し側が 0 を渡すので盤は変わらないが, コンパイラにも CPU にもそれは分からず,
//                1呼び出しずつしか進めない. 鎖には and と xor の2命令ぶん (約2サイクル) が足される
//   rbRanks      x[0..n) の番号を out に書く (段2の一致の検査)
#include "animal_shogi.c"

int rbMaxFwd(void) { return MAX_ACTION_NUM; }
int rbMaxUnmove(void) { return UNMOVE_MAX; }

int rbFwdOne(u_long b, u_long *out) {
    int nc;
    rankTablesBuild();
    return nextBoardInvNormalNC(b, out, &nc);
}

int rbUnmoveOne(u_long q, u_long *out) {
    rankTablesBuild();
    return unmoveCandidates(q, out);
}

u_long rbThr(const u_long *x, size_t n, size_t reps) {
    u_long s = 0;
    rankTablesBuild();
    for (size_t r = 0; r < reps; r++)
        for (size_t i = 0; i < n; i++) s += rankOf(x[i]);
    return s;
}

u_long rbChain(const u_long *x, size_t n, size_t reps, u_long mask) {
    u_long s = 0, p = 0;
    rankTablesBuild();
    for (size_t r = 0; r < reps; r++)
        for (size_t i = 0; i < n; i++) {
            p = rankOf(x[i] ^ (p & mask));
            s += p;
        }
    return s;
}

void rbRanks(const u_long *x, size_t n, uint64_t *out) {
    rankTablesBuild();
    for (size_t i = 0; i < n; i++) out[i] = rankOf(x[i]);
}
