// ベンチ用の入口 (実験 perf_34。記録試行ではない)
//
// impl/34_unmove/animal_shogi.c をそのまま取り込み (書き換えない), 生成器の部分だけを回す関数を足す.
// impl/34_unmove の Makefile の gcc 行のまま (入力と出力の名前だけ替えて) .so にする (build_bench.sh).
// 番号は本物と同じ static inline の rankOf で出す (rankBoard は番号にできる盤かの検査と呼び出しが乗る).
//
//   benchFwd     F1 の生成器の部分: nextBoardInvNormalNC で後続を作り, 後続ごとに rankOf で番号を出す
//                (本物の nextBoardSeenNormal から, 発見済みの表・準備の配列・初見の後続の書き出しを除いたもの)
//   benchUnmove  U_loop の生成器の部分: unmoveCandidates で前任の候補を作り, 候補ごとに rankOf で番号を出す
//                (本物の unmoveStep から, 手数の配列と残りの数の読み書き・決まった局面の書き出しを除いたもの)
// どちらも in[0..n) を1回ずつ回し, 番号の和を返す (最適化で消されないため). outs に後続 (候補) の延べ数
#include "animal_shogi.c"

u_long benchFwd(const u_long *in, size_t n, uint64_t *outs) {
    u_long nbs[MAX_ACTION_NUM];
    uint64_t s = 0, o = 0;
    int nc;
    rankTablesBuild();
    for (size_t i = 0; i < n; i++) {
        int k = nextBoardInvNormalNC(in[i], nbs, &nc);
        for (int j = 0; j < k; j++) s += rankOf(nbs[j]);
        if (k > 0) o += (uint64_t)k;
    }
    *outs = o;
    return s;
}

u_long benchUnmove(const u_long *in, size_t n, uint64_t *outs) {
    u_long cand[UNMOVE_MAX];
    uint64_t s = 0, o = 0;
    rankTablesBuild();
    for (size_t i = 0; i < n; i++) {
        int k = unmoveCandidates(in[i], cand);
        for (int j = 0; j < k; j++) s += rankOf(cand[j]);
        o += (uint64_t)k;
    }
    *outs = o;
    return s;
}
