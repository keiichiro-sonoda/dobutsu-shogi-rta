#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
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
// 記録 #26: ループと分岐を無くした. #25 までは12マスを1つずつ読み, 空きマスを飛ばし,
// 駒のあるマスを反対側 (マス i → 11 - i) へ, 所有者ビットを反転して置き直していた.
// 同じ値を3つの手順で作る (全 246,803,167 局面で旧版と1ビットも違わないことを
// experiments/gen_bench で確かめた).
//   1. マスの並びを逆にする. 盤は下位6バイト (4ビット x 12マス) なので, 8バイトを逆順にして
//      16ビット右へずらすと, バイト k がバイト 5 - k に来る. 続けて各バイトの上下4ビットを
//      入れ替えると, マス 2k は 11 - 2k に, マス 2k + 1 は 10 - 2k に来る (旧版の 44 - i と同じ)
//   2. 駒のあるマスだけ所有者ビット (0b1000) を反転する. 1ビット・2ビット右へずらした OR で,
//      各マスの4ビットの OR を最下位ビットに集める. 1つ上のマスのビットが漏れ込むのは上位の
//      ビットにだけなので, 0x1111... で最下位ビットだけを取れば混ざらない. それを3ビット左へ
//      ずらして XOR する. 空きマス (0) は 0 のまま (旧版が飛ばしていたのと同じ)
//   3. 持ち駒の6ビット2組は旧版の式のまま入れ替える. 1 のあと上位16ビットは 0 なので OR で置ける
u_long invBoard(u_long b) {
    const u_long nib_lo = 0x0f0f0f0f0f0fUL;
    u_long ib, occ, own1, own2;
    ib = __builtin_bswap64(b & 0xffffffffffffUL) >> 16;
    ib = ((ib & nib_lo) << 4) | ((ib >> 4) & nib_lo);
    occ = ib | (ib >> 1);
    occ |= occ >> 2;
    ib ^= (occ & 0x111111111111UL) << 3;
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
// 記録 #20: moves を宣言で NULL に初期化した. default: 経路 (koma が 1/2/3/5) では
// 未設定のまま抜けるが, 直後の if (!moves_num) continue; で読まれないので挙動は正しい.
// ただ値域解析が moves と moves_num の相関を追えない処理系では -Wmaybe-uninitialized の種になる
int nextBoardInvNormal(u_long b, u_long *nbs) {
    u_long nb, koma, dst_koma;
    int i, j, dst, own_num, own_p, *moves = NULL, moves_num, src_mod16, dst_mod16;
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

// ---- 2 MiB ページを頼んで確保する (記録 #21) ------------------------------------
//
// 索引 (8 GiB) と発見済み表 (最終 4 GiB) はランダムに引かれる. 4 KiB ページのままだと,
// データを読む前に番地の翻訳のためにもう1回メモリを読むことが多い. 2 MiB ページなら
// 翻訳の件数が 1/512 になり, CPU が覚えておける翻訳で表の大部分を覆える.
//
// この機械の THP は [madvise] なので, 頼んだ領域にだけ巨大ページが付く (OS の設定は変えない).
//   1. madvise は memset より前に頼む. 触ったあとに頼んでも, その場では付かない
//   2. 付かなくても 4 KiB ページのまま正しく動く. 答えは変わらず, 遅いだけ
//      (付いたかどうかは Python 側が表を捨てる直前に AnonHugePages を読んで残す)
//   3. 解放は free() のまま (aligned_alloc と対になっている)
#define HUGE_ALIGN ((size_t)1 << 21)

static void *hugeAlloc(size_t bytes) {
    size_t sz = (bytes + HUGE_ALIGN - 1) & ~(HUGE_ALIGN - 1);
    void *p = aligned_alloc(HUGE_ALIGN, sz);
    if (p) madvise(p, sz, MADV_HUGEPAGE);
    return p;
}

// ---- 後退解析の配列を 2 MiB ページで確保する (記録 #25) -------------------------------
//
// 記録 #25〜#33 は pred / pred_off / cnt / dtm を, 索引と同じ hugeAlloc で確保して fill で埋めていた. #24 まで
// Python の array / bytearray で確保していて, 4 KiB ページのままだった. 記録 #34 の後退解析は, 手数の配列を
// unmoveInit が hugeAlloc で直接確保する. これは Python 側に残した口 (いまは使っていない).
//   1. madvise (hugeAlloc の中) のあとに memset する. 先に触ると 4 KiB ページが付いてしまう
//      (上の hugeAlloc の 1 と同じ)
//   2. 解放はしない. 後退解析が終わるまで使い, そのままプロセスが終わる (#24 までの Python の
//      配列も retreatAnalysis() が返るまで持っていたので, 持つ期間は変わらない)
void *hugeFill(size_t bytes, int fill) {
    void *p;
    if (bytes == 0) bytes = 1;
    p = hugeAlloc(bytes);
    if (p) memset(p, fill, bytes);
    return p;
}

// ---- 全探索の発見済み集合: ランクで引く到達済みビット表 (記録 #30) ---------------
//
// #11〜#28 はオープンアドレス法のハッシュ表 (キー 8 B, 2^20 スロットから倍々, 最終 4 GiB) だった.
// #30 からは, 局面から番号を計算で直接出す関数 (ランク) を作り, その番号を添字にした 1 ビットの表で
// 「もう見たか」を判定する. 意味 (初めて見た局面だけを返す) と返す順序は変えていない.
//
// ランクの作り方 (定義域は normalBoard で正規化した局面. ライオンは盤上に1頭ずつ):
//   1. ライオンの組. 手番側 (4) と相手 (12) の置き方 12 x 11 = 132 通りを, 左右の鏡像どうしで
//      まとめて 72 組にする (2頭とも中央の列にある 12 通りは鏡像が自分自身なので, そのまま).
//      まとめた組の片方では, 盤を左右反転してから数える (反転しても同じ局面の類なので単射のまま)
//   2. 残り 10 マス. ライオンの2マスを抜いて詰め, 前半5マス・後半5マスに分ける. 各マスは
//      9 通り (空き, きりん・ぞう・ひよこ・にわとり x 持ち主) なので, 5 マスを 9 進数にして
//      前計算の表 (59,049 項目) を引き, 「5マスの中の駒の数の組 (きりん・ぞう・ひよこ各 0〜2)」と
//      「その組の中での順位」を得る. 前後の組を合わせ, 種類ごとに 2 以下になる組み合わせだけを数える
//   3. 持ち駒. 種類ごとに盤上の数 n が決まれば持ち駒の合計は 2 - n なので, 下位の持ち駒
//      (bit 48〜53) の数だけを基数 3 - n で数える
//
// 値域は 72 x 11,878,227 = 855,232,344 (到達局面 246,803,167 の 3.47 倍) で, 表は 106.9 MB.
// ⚠️ 値域も前計算の表も, 駒の数と盤の形 (ルール) だけから seenInit で数える. 到達局面の数や
//    解析の結果は使わない (#11 で初期サイズに既知の総数を使わなかったのと同じ理由).
// ⚠️ 前計算の表は1回だけ作る (seenFree しても残す. 数十 KB で, 中身は呼ぶたびに同じ).

static uint64_t *g_seen = NULL;     // 到達済みビット表 (ランクを添字にした 1 ビット)
static size_t g_seen_words = 0;
static u_long g_seen_n = 0;
static u_long g_seen_probes = 0;

// 前計算の表 (rankTablesBuild が作る)
typedef struct {
    uint64_t base;   // ライオンの組の先頭の番号
    uint64_t mirror; // 盤を左右反転するなら全ビット 1
    uint8_t hi, lo;  // 反転したあとのライオンの2マス (hi > lo)
} RankLion;
static RankLion g_rank_lion[144];        // 手番側ライオンのマス * 12 + 相手のライオンのマス
static uint8_t g_rank_code[16];          // 4ビットの駒の値 -> 0〜8 (不正は 0xff)
static uint16_t g_rank_pair[256];        // 2マス (1バイト) -> 0〜80 (不正は 0xffff)
static uint32_t g_rank_half[59049];      // 5マスの 9 進数 -> 組 << 16 | 組の中での順位
static uint32_t g_rank_cnt5[27];         // 5マスで組ごとに何通りあるか
static uint64_t g_rank_split[27][27];    // 前後の組 -> 番号の先頭 (合わせた組の先頭を含む)
static uint32_t g_rank_rmul[27][27];     // 前半の順位に掛ける数 (= 後半の通り数 x 持ち駒の通り数)
static uint32_t g_rank_hand[27][27];     // 持ち駒の通り数 | (3 - ひよこ) << 8 | (3 - きりん) << 12
static uint64_t g_rank_range = 0;        // 値域の大きさ
static int g_rank_ready = 0;

// 5マス (9進数の各桁) の駒の種類: 0 空き / 1 きりん / 2 ぞう / 3 ひよこ・にわとり
static const uint8_t RANK_CODE_KIND[9] = {0, 1, 1, 2, 2, 3, 3, 3, 3};
// 9 通りの並び (この順が 9 進数の桁の値になる)
static const uint8_t RANK_CODE_KOMA[9] = {EMPTY, GIRAFFE1, GIRAFFE2, ELEPHANT1, ELEPHANT2,
                                          CHICK1, CHICK2, CHICKEN1, CHICKEN2};

static int rankMirrorSquare(int sq) { return (2 - sq / 4) * 4 + sq % 4; }

static void rankTablesBuild(void) {
    int a, b, i, s, s0, s1, idx, cls;
    uint32_t cnt[27];
    uint64_t board10[27], sigbase[27], handcnt[27], per_class;
    int16_t sigadd[27][27];
    uint64_t pairoff[27][27];
    int8_t lclass[144];
    if (g_rank_ready) return;
    memset(g_rank_code, 0xff, sizeof g_rank_code);
    for (i = 0; i < 9; i++) g_rank_code[RANK_CODE_KOMA[i]] = (uint8_t)i;
    for (i = 0; i < 256; i++) {
        int c0 = g_rank_code[i & 15], c1 = g_rank_code[i >> 4];
        g_rank_pair[i] = (c0 == 0xff || c1 == 0xff) ? 0xffff : (uint16_t)(c0 + 9 * c1);
    }
    // 5マスの全 9^5 通りを順に見て, 組ごとに出てきた順で順位を振る
    memset(cnt, 0, sizeof cnt);
    for (idx = 0; idx < 59049; idx++) {
        int x = idx, n[4] = {0, 0, 0, 0};
        for (i = 0; i < 5; i++) {
            n[RANK_CODE_KIND[x % 9]]++;
            x /= 9;
        }
        if (n[1] > 2 || n[2] > 2 || n[3] > 2) {
            g_rank_half[idx] = 0xffffffffu;
            continue;
        }
        s = n[1] * 9 + n[2] * 3 + n[3];
        g_rank_half[idx] = ((uint32_t)s << 16) | cnt[s]++;
    }
    memcpy(g_rank_cnt5, cnt, sizeof cnt);
    // 前後の組を足した組 (種類ごとに 2 を超えたら -1)
    for (s0 = 0; s0 < 27; s0++)
        for (s1 = 0; s1 < 27; s1++) {
            int g = s0 / 9 + s1 / 9, e = s0 / 3 % 3 + s1 / 3 % 3, c = s0 % 3 + s1 % 3;
            sigadd[s0][s1] = (int16_t)((g > 2 || e > 2 || c > 2) ? -1 : g * 9 + e * 3 + c);
        }
    // 合わせた組ごとに, 前半の組の小さい順に塊を並べる
    memset(board10, 0, sizeof board10);
    for (s0 = 0; s0 < 27; s0++)
        for (s1 = 0; s1 < 27; s1++) {
            s = sigadd[s0][s1];
            if (s < 0) continue;
            pairoff[s0][s1] = board10[s];
            board10[s] += (uint64_t)cnt[s0] * cnt[s1];
        }
    per_class = 0;
    for (s = 0; s < 27; s++) {
        handcnt[s] = (uint64_t)(3 - s / 9) * (3 - s / 3 % 3) * (3 - s % 3);
        sigbase[s] = per_class;
        per_class += board10[s] * handcnt[s];
    }
    memset(g_rank_split, 0, sizeof g_rank_split);
    memset(g_rank_rmul, 0, sizeof g_rank_rmul);
    memset(g_rank_hand, 0, sizeof g_rank_hand);
    for (s0 = 0; s0 < 27; s0++)
        for (s1 = 0; s1 < 27; s1++) {
            s = sigadd[s0][s1];
            if (s < 0) continue;
            g_rank_split[s0][s1] = sigbase[s] + pairoff[s0][s1] * handcnt[s];
            g_rank_rmul[s0][s1] = (uint32_t)(cnt[s1] * handcnt[s]);
            g_rank_hand[s0][s1] = (uint32_t)handcnt[s] | (uint32_t)(3 - s % 3) << 8
                                  | (uint32_t)(3 - s / 9) << 12;
        }
    // ライオンの組. 走査で先に出てきた側を代表にし, 鏡像の側は盤を反転して代表に寄せる
    memset(lclass, -1, sizeof lclass);
    memset(g_rank_lion, 0, sizeof g_rank_lion);
    cls = 0;
    for (a = 0; a < 12; a++)
        for (b = 0; b < 12; b++) {
            int ma = rankMirrorSquare(a), mb = rankMirrorSquare(b);
            if (a == b || lclass[a * 12 + b] >= 0) continue;
            lclass[a * 12 + b] = (int8_t)cls;
            g_rank_lion[a * 12 + b].mirror = 0;
            lclass[ma * 12 + mb] = (int8_t)cls;
            if (ma * 12 + mb != a * 12 + b) g_rank_lion[ma * 12 + mb].mirror = ~(uint64_t)0;
            cls++;
        }
    for (i = 0; i < 144; i++) {
        int l1 = i / 12, l2 = i % 12;
        if (lclass[i] < 0) continue;
        if (g_rank_lion[i].mirror) {
            l1 = rankMirrorSquare(l1);
            l2 = rankMirrorSquare(l2);
        }
        g_rank_lion[i].base = (uint64_t)lclass[i] * per_class;
        g_rank_lion[i].hi = (uint8_t)(l1 > l2 ? l1 : l2);
        g_rank_lion[i].lo = (uint8_t)(l1 > l2 ? l2 : l1);
    }
    g_rank_range = (uint64_t)cls * per_class;
    g_rank_ready = 1;
}

// 4ビットの組のうち値が t のものの位置 (0〜11). 盤上にちょうど1つある前提
static inline int rankFindKoma(u_long b48, u_long t) {
    u_long x = b48 ^ (t * 0x111111111111UL);
    u_long z = ~(((x & 0x777777777777UL) + 0x777777777777UL) | x) & 0x888888888888UL;
    return __builtin_ctzl(z) >> 2;
}

// 4ビットの組 sq を抜いて, 上の組を1つずつ下へ詰める
static inline u_long rankSqueeze(u_long x, int sq) {
    u_long low = ((u_long)1 << (4 * sq)) - 1;
    return (x & low) | ((x >> 4) & ~low);
}

static inline uint32_t rankHalf(u_long x) {
    return g_rank_pair[x & 0xff] + 81 * g_rank_pair[(x >> 8) & 0xff] + 6561 * g_rank_code[(x >> 16) & 15];
}

// ランク. 正しい盤面 (rankValid が真) に対してだけ意味がある. 分岐は使わない
// 記録 #32: always_inline で呼び出し元へ必ず展開させる. #30 では gcc -O2 が大きさの見積もりで展開せず,
// nextBoardSeenNormal() から後続ごとに call していた. 計算の中身は変えていない
static inline __attribute__((always_inline)) uint64_t rankOf(u_long b) {
    u_long b48 = b & 0xffffffffffffUL, m, x, h;
    const RankLion *lt = &g_rank_lion[rankFindKoma(b48, LION1) * 12 + rankFindKoma(b48, LION2)];
    uint32_t t0, t1, s0, s1, hs;
    m = ((b48 & 0xffff) << 32) | (b48 & 0xffff0000UL) | (b48 >> 32);
    b48 ^= (b48 ^ m) & lt->mirror;
    x = rankSqueeze(rankSqueeze(b48, lt->hi), lt->lo);
    t0 = g_rank_half[rankHalf(x & 0xfffff)];
    t1 = g_rank_half[rankHalf(x >> 20)];
    s0 = t0 >> 16;
    s1 = t1 >> 16;
    hs = g_rank_hand[s0][s1];
    h = b >> 48;
    return lt->base + g_rank_split[s0][s1] + (uint64_t)(t0 & 0xffff) * g_rank_rmul[s0][s1]
           + (uint64_t)(t1 & 0xffff) * (hs & 0xff)
           + (h & 3) + ((hs >> 8) & 15) * (((h >> 2) & 3) + ((hs >> 12) & 15) * ((h >> 4) & 3));
}

// 盤面として正しいか (ライオンが盤上に1頭ずつ, ほかの駒は種類ごとに盤と持ち駒で2枚, 上位4ビットは 0)
static int rankValid(u_long b) {
    int i, nl1 = 0, nl2 = 0, n[4] = {0, 0, 0, 0};
    u_long h = b >> 48;
    for (i = 0; i < 12; i++) {
        int koma = (int)getKoma(b, 4 * i);
        if (koma == LION1) nl1++;
        else if (koma == LION2) nl2++;
        else if (g_rank_code[koma] == 0xff) return 0;
        else n[RANK_CODE_KIND[g_rank_code[koma]]]++;
    }
    if (nl1 != 1 || nl2 != 1 || (b >> 60)) return 0;
    return n[3] + (int)(h & 3) + (int)((h >> 6) & 3) == 2
           && n[1] + (int)((h >> 2) & 3) + (int)((h >> 8) & 3) == 2
           && n[2] + (int)((h >> 4) & 3) + (int)((h >> 10) & 3) == 2;
}

u_long rankBoard(u_long b) {
    rankTablesBuild();
    return rankValid(b) ? rankOf(b) : INDEX_EMPTY;
}

u_long rankRange(void) {
    rankTablesBuild();
    return g_rank_range;
}

void seenFree(void) {
    free(g_seen);
    g_seen = NULL;
    g_seen_words = 0;
    g_seen_n = 0;
    g_seen_probes = 0;
}

int seenInit(void) {
    size_t bytes;
    seenFree();
    rankTablesBuild();
    g_seen_words = (size_t)((g_rank_range + 63) / 64);
    bytes = g_seen_words * sizeof(uint64_t);
    // 最初に1回だけ確保する (作り直しは無い). madvise (hugeAlloc の中) のあとに 0 で埋める
    g_seen = (uint64_t *)hugeAlloc(bytes);
    if (!g_seen) return -3;
    memset(g_seen, 0, bytes);
    return 0;
}

// 1=新しく立てた / 0=既に立っていた
static inline int seenTestAndSet(uint64_t r) {
    uint64_t bit = (uint64_t)1 << (r & 63), *w = &g_seen[r >> 6];
    if (*w & bit) return 0;
    *w |= bit;
    g_seen_n++;
    return 1;
}

int seenInsert(u_long key) {
    if (!g_seen && seenInit() != 0) return -3;
    // 盤面として正しくない値 (番兵を含む) はここで弾く. nextBoardSeenNormal は生成した盤面しか
    // 入れないので, この検査を通さない
    if (!rankValid(key)) return -4;
    return seenTestAndSet(rankOf(key));
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
    uint64_t r;
    if (!g_seen || !rankValid(key)) return 0;
    r = rankOf(key);
    return (int)((g_seen[r >> 6] >> (r & 63)) & 1);
}

u_long seenProbes(void) {
    return g_seen_probes;
}

// 作り直しは無いので常に 0 (forward.tsv の n_rehash の列を残すための口)
u_long seenRehashes(void) {
    return 0;
}

// ---- 後退解析の準備を全探索で書く (記録 #34) ---------------------------------------
//
// 全探索で展開した局面 p ごとに, ランクを添字にした 1 バイトの配列 g_prep に, 種類と
// キャッチ抜きの数 (後続のうちキャッチ局面でないものの数. 重複込み) を書く. 後退解析 (下の
// 「一手前を直接作る」) が手数と残りの数の初期値に使う. 実験 forward_prep の腕 carry と同じ形.
// あわせて, キャッチ抜きの数が 0 の未知局面 (手数 2 の負け) を見つけた順に g_zero に積む
// (後退解析の手数 2 の段のフロンティアに足す. 到達局面ではランクから盤面に戻せないので, ここで持つ).
//   0       到達しない (書かれていない)
//   1〜49   未知局面. キャッチ抜きの数 + 1 (1 ならキャッチ抜きの数が 0. 手数 2 の負けになる)
//   0xFE    トライ負け局面
//   0xFF    キャッチ局面
// キャッチ抜きの数は experiments/attack_count の B1′ (相手の利きの一覧) で数える.
#define PREP_TRY 0xFE
#define PREP_CATCH 0xFF

static uint8_t *g_prep = NULL;
static u_long *g_zero = NULL;
static size_t g_zero_n = 0, g_zero_cap = 0;
static uint16_t g_att[16][12];  // 相手の駒 k (1〜5) がマス sq にいるとき届くマスの集合 (反転した盤の上)
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
        if (s16 != 12) g_att[CHICK1][s / 4] |= (uint16_t)(1u << ((s + 4) / 4));
    }
    g_att_ready = 1;
}

// 配列を確保する (発見済み表と同じく最初に1回. 巨大ページを頼んでから 0 で埋める)
int prepInit(void) {
    free(g_prep);
    attackTableBuild();
    if (!g_rank_range) rankTablesBuild();
    g_prep = (uint8_t *)hugeAlloc((size_t)g_rank_range);
    if (!g_prep) return -3;
    memset(g_prep, 0, (size_t)g_rank_range);
    return 0;
}

const uint8_t *prepPtr(void) {
    return g_prep;
}

void prepFree(void) {
    free(g_prep);
    g_prep = NULL;
    free(g_zero);
    g_zero = NULL;
    g_zero_n = g_zero_cap = 0;
}

u_long prepZeroCount(void) {
    return g_zero_n;
}

// 手数 2 の負けになる局面を1つ積む. 足りなければ倍に伸ばす. 返り値 0 / -3 確保できない
static int zeroPush(u_long b) {
    if (g_zero_n == g_zero_cap) {
        size_t cap = g_zero_cap ? g_zero_cap * 2 : ((size_t)1 << 16);
        u_long *grown = (u_long *)realloc(g_zero, cap * sizeof(u_long));
        if (!grown) return -3;
        g_zero = grown;
        g_zero_cap = cap;
    }
    g_zero[g_zero_n++] = b;
    return 0;
}

// nextBoardInvNormal の写しに, キャッチ抜きの数を数える仕事 (experiments/attack_count の B1′) を足したもの.
// 後続の列と順番, 戻り値は nextBoardInvNormal と同じ. *non_catch にキャッチ抜きの数
int nextBoardInvNormalNC(u_long b, u_long *nbs, int *non_catch) {
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
    // 一覧: 相手の駒が届くマスの集合 att1 と, 手番側のライオンに届いている相手の駒のマスの集合 atkL
    {
        int Lsq = rankFindKoma(b & 0xffffffffffffUL, LION2);
        for (int sq = 0; sq < 12; sq++) {
            unsigned m = g_att[getKoma(b, 4 * sq)][sq];
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
            if (dst % 16 == 0) {
                koma = CHICKEN2;
            }
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
                if (koma == LION2) c = (att1 >> (dst / 4)) & 1u;
                else c = (atkL & ~(1u << (dst / 4))) != 0;
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
            nc += !c;
            nbs[nbs_p++] = normalBoard(nb | (koma << emp_adrs[j]));
        }
    }
    *non_catch = nc;
    return nbs_p;
}

// 記録 #34: 展開する局面 b のランク rb は, 後続として見つけたときに待ち行列に一緒に積んだものを受け取る
// (計算し直さない. 実験 forward_prep で, 計算し直す形より F1 が 3.1 秒軽かった).
// 初見の後続のランクを out_rank に out と同じ並びで返す. b の種類とキャッチ抜きの数を g_prep[rb] に書く
int nextBoardSeenNormal(u_long b, uint32_t rb, u_long *out, uint32_t *out_rank) {
    u_long nbs[MAX_ACTION_NUM];
    uint64_t r[MAX_ACTION_NUM];
    int nbn, i, nc;
    int found = 0;
    if (!g_seen && seenInit() != 0) return -3;
    if (!g_prep && prepInit() != 0) return -3;
    __builtin_prefetch(&g_prep[rb], 1, 3);
    nbn = nextBoardInvNormalNC(b, nbs, &nc);
    // 0 = キャッチ勝ち / -1 = トライ負け. どちらも後続を持たない
    // ⚠️ ここで規約を付け替える. 「未知だが初見が0個」を 0 で返したいため
    if (nbn == 0) {
        g_prep[rb] = PREP_CATCH;
        return -1;
    }
    if (nbn < 0) {
        g_prep[rb] = PREP_TRY;
        return -2;
    }
    g_prep[rb] = (uint8_t)(nc + 1);
    if (nc == 0 && zeroPush(b) != 0) return -3;
    g_seen_probes += (u_long)nbn;
    // 記録 #20 と同じ形: 全後続の番号を先に出してビット表の語を取り寄せ, そのあとで順に立てる.
    // 先読みはヒントなので書く値は変わらない. 返す順序は nbs の順のまま
    for (i = 0; i < nbn; i++) {
        r[i] = rankOf(nbs[i]);
        __builtin_prefetch(&g_seen[r[i] >> 6], 1, 3);
    }
    for (i = 0; i < nbn; i++) {
        if (seenTestAndSet(r[i])) {
            out_rank[found] = (uint32_t)r[i];
            out[found++] = nbs[i];
        }
    }
    return found;
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
static uint32_t *g_exp_rank = NULL;  // 記録 #34: g_exp_new と同じ並びの, 初見の後続のランク
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
    {
        uint32_t *gr = (uint32_t *)realloc(g_exp_rank, cap * sizeof(uint32_t));
        if (!gr) return -2;
        g_exp_rank = gr;
    }
    g_exp_cap = cap;
    return 0;
}

const u_long *expandNewPtr(void) {
    return g_exp_new;
}

const uint32_t *expandNewRankPtr(void) {
    return g_exp_rank;
}

u_long expandNewCount(void) {
    return g_exp_n;
}

void expandFreeBuffer(void) {
    free(g_exp_new);
    g_exp_new = NULL;
    free(g_exp_rank);
    g_exp_rank = NULL;
    g_exp_cap = 0;
    g_exp_n = 0;
}

int expandRound(const u_long *unexp, const uint32_t *unexp_rank, uint32_t n,
                u_long *win, u_long *lose, u_long *uk, u_long *out) {
    uint32_t i = 0, n_win = 0, n_lose = 0, n_uk = 0;
    u_long probes0 = g_seen_probes;
    int nbn, rc = 0;
    // ⚠️ どの早期 return よりも前に 0 に戻す (記録 #13・#14 の不具合がここの順序だった).
    //    出口や引数検査の後ろで戻すと, 空入力のラウンドで expandNewCount() が
    //    前のラウンドの値を返し, 同じ後続がもう一度未探索盤面に積まれる.
    //    途中で落ちたラウンドの残骸に積み足さないためでもある.
    //    記録 #15 では !out の return だけがこれより前に残っていて,
    //    コメントのほうが実コードより強いことを言っていた (g_exp_n は static なので,
    //    引数検査より前に出してもコストはゼロ)
    g_exp_n = 0;
    if (!out) return -1;
    out[0] = out[1] = out[2] = out[3] = out[4] = 0;
    // 空のチャンクは起こりうる (searchNext が unexplored に set() を書く).
    // そのとき array("Q") の buffer_info() は 0 を返すので, NULL を許す
    // (predCount が n_edges == 0 でやっているのと同じ)
    if (n == 0) return 0;
    if (!unexp || !unexp_rank || !win || !lose || !uk) return -1;
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
        nbn = nextBoardSeenNormal(unexp[i], unexp_rank[i], g_exp_new + g_exp_n, g_exp_rank + g_exp_n);
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

// ---- 後退解析: 一手前を直接作る (記録 #34) ------------------------------------------
//
// #33 までの後退解析は, 未知局面の後続を全部作り (P2), 向きを逆にして前任の表に並べ替え (P4),
// 174段ループでその表を引いていた. 表を引くための番号は, パック値 → 連番の索引 (P1, 8 GiB) で振っていた.
// #34 からは, 全探索が展開した局面ごとにランクを添字にした 1 バイトの配列 g_prep (種類と
// キャッチ抜きの数) を書いておき (上の nextBoardSeenNormal), 後退解析ではそれを手数の配列 g_dtm と
// 残りの数 (g_prep をその場で読み替えたもの) にして, 決まった局面 q から手を1つ戻して前任をその場で作る.
// 実験 unmove_bench〜forward_prep で1つずつ確かめた形を写した.
//
// 手数の配列 g_dtm (ランクを添字. 1 バイト):
//   0〜254 の手数 (偶数が負け, 奇数が勝ち. いまの dtm と同じ) / 255 未定の未知局面 / DTM_NONE 到達しない局面
//   (到達しない番号は前任の候補として出てくるので, 未定と区別する. 手数は 174 まで)
// 残りの数 (g_prep を読み替える): 未知局面だけが意味を持つ. キャッチ抜きの数 (キャッチ局面への手を外した後続の数. 重複込み)
//
// キャッチ局面への手を外しても答えは変わらない (experiments/unmove_catch の README):
// 負けに決まる局面の手数は「1 ＋ 後続の勝ちの手数の最大」で, キャッチ局面 (手数 1 の勝ち) はその最大を決めない.
// 後続がキャッチ局面だけの未知局面 (キャッチ抜きの数が 0) は手数 2 の負けで, 初期化で決め, 手数 2 の段の
// フロンティアに足す. キャッチ局面からは前任をたどらない.
#define DTM_UNDECIDED 255
#define DTM_NONE 254

static uint8_t *g_dtm = NULL;
static u_long *g_draws = NULL;

// 前任を作る: q の手を1つ戻す (逆向きの生成器. experiments/unmove_bench の unmove.c と
// experiments/unmove_prune の prune.c の絞った版).
//
// いまの生成器 (nextBoardInvNormal) は p を invBoard で反転し, 手番側の駒 (9〜13) を動かした盤 nb を
// normalBoard に通したものを後続 q にする. だから q (と左右の鏡像) の上で 9〜13 の駒 (直前に指した側 X) の手を
// 1つ戻した盤 b' を作り, p = invBoard(b') とすればよい. 戻した p が正規形のものだけを残すと,
// 残った (nb, 戻した手) の組と, いまの生成器の (p, 手) の組がちょうど1対1になる (重複も手の数として数えられる).
//
// 作る前に絞る: p がキャッチ局面か (p で X の駒が q の手番側 Y のライオン LION1 に利くか) は, 盤を見るだけで分かる.
// どの駒も1マスしか動かないので, X の駒を1つ戻しても X のほかの駒の利きは変わらない. そこで nb ごとに1回
//   A = { LION1 に利いている X の駒のマス }  (q で Y に王手をかけている駒のマスの集合. 盤の列 A〜C とは関係ない)
// を作り, マス d の駒を戻す手は「A から d を除いて空」のときだけ作る (A が2マス以上なら何も作らない).
// 戻した先 s の駒 (成りを戻すならひよこ) が LION1 に利く戻し方も作らない. 利きの規則はいまの生成器の手の規則と同じ.
enum UnmoveKind { UK_MOVE, UK_CAPTURE, UK_DROP, UK_PROMOTE, UK_PROMOTE_CAPTURE };

static const int UNMOVE_CAPTURED[4] = {CHICK1, CHICKEN1, GIRAFFE1, ELEPHANT1};

// X の駒 k (9〜13) がマス sq にいるとき利くマスの集合 (12ビット). Y の駒と空きは 0
static uint16_t g_xatt[16][12];
static int g_xatt_ready = 0;

static void unmoveTableBuild(void) {
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

// 列を左右に反転する (normalBoard の入れ替えを無条件に行う)
static inline u_long unmoveMirror(u_long b) {
    return ((b >> 48) << 48) | ((b & 0xffff) << 32) | (b & 0xffff0000UL) | ((b >> 32) & 0xffff);
}

// 戻した盤 b' から p を作り, 正規形なら out に足す
static inline __attribute__((always_inline)) int unmoveEmit(u_long bp, u_long *out, int n) {
    u_long p = invBoard(bp);
    if (normalBoard(p) != p) return n;
    out[n] = p;
    return n + 1;
}

// nb のマス d の X の駒の手を全部戻す (戻した先から LION1 (マス L) に利く戻し方は作らない)
static inline __attribute__((always_inline)) int unmovePiece(u_long nb, int d, int L, u_long *out, int n) {
    u_long k = getKoma(nb, d);
    u_long base = delKoma(nb, d);
    int d16 = d % 16;
    // 持ち駒を打った (ひよこ・きりん・ぞう). 打ったあとの数が 0 なら 1 に, 1 なら 2 に戻す
    if (k == CHICK2 || k == GIRAFFE2 || k == ELEPHANT2) {
        int own_p = 54 + (int)(k - CHICK2) * 2;
        u_long c = (nb >> own_p) & 0b11;
        if (c < 2) n = unmoveEmit(base ^ ((c ? (u_long)0b11 : (u_long)0b01) << own_p), out, n);
    }
    // 駒を動かした. (元の駒, 元のマス) を並べる
    int srcs[10], k0s[10], ns = 0;
    if (k == CHICK2) {
        // 成らない前進: 行き先が端 (d16 == 0) でなく, 元のマスが同じ列にある (d16 != 12)
        if (d16 == 4 || d16 == 8) {
            srcs[ns] = d + 4;
            k0s[ns++] = CHICK2;
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
            k0s[ns++] = (int)k;
        }
        // にわとりが端の行にいれば, ひよこが1つ前のマスから進んで成った手もありうる
        if (k == CHICKEN2 && d16 == 0) {
            srcs[ns] = d + 4;
            k0s[ns++] = CHICK2;
        }
    }
    for (int j = 0; j < ns; j++) {
        int s = srcs[j];
        if (getKoma(nb, s)) continue;                    // 元のマスは空いていなければならない
        if ((g_xatt[k0s[j]][s / 4] >> L) & 1) continue;  // 戻した先から LION1 に利く: 前任はキャッチ局面
        u_long b0 = base | ((u_long)k0s[j] << s);
        n = unmoveEmit(b0, out, n);
        // 駒を取った: 取った駒は直前に指した側の持ち駒 (bit 54〜59) に入っている.
        // ひよことにわとりはどちらも bit 54 に入る. 取ったあとの数が 1 なら 0 に, 2 なら 1 に戻す
        for (int t = 0; t < 4; t++) {
            int c = UNMOVE_CAPTURED[t];
            int own_p = c == CHICKEN1 ? 54 : 52 + c * 2;
            u_long cnt = (b0 >> own_p) & 0b11;
            if (!cnt) continue;
            u_long b1 = (b0 ^ ((cnt == 2 ? (u_long)0b11 : (u_long)0b01) << own_p)) | ((u_long)c << d);
            n = unmoveEmit(b1, out, n);
        }
    }
    return n;
}

static inline __attribute__((always_inline)) int unmoveRaw(u_long nb, u_long *out, int n) {
    int L = rankFindKoma(nb & 0xffffffffffffUL, LION1);
    unsigned a = 0;
    for (int sq = 0; sq < 12; sq++) a |= ((g_xatt[getKoma(nb, 4 * sq)][sq] >> L) & 1u) << sq;
    int asz = __builtin_popcount(a);
    // 局面と駒の単位: A が2マス以上なら前任は無い. 1マスなら, そのマスの駒だけを戻す
    if (asz >= 2) return n;
    if (asz == 1) return unmovePiece(nb, 4 * __builtin_ctz(a), L, out, n);
    for (int d = 0; d < 48; d += 4) {
        if (!(getKoma(nb, d) & 0b1000)) continue;
        n = unmovePiece(nb, d, L, out, n);
    }
    return n;
}

#define UNMOVE_MAX 1024

// q の前任の候補 (正規形. キャッチ局面になるものは作らない). 到達しない局面も混ざる
int unmoveCandidates(u_long q, u_long *out) {
    unmoveTableBuild();
    int n = unmoveRaw(q, out, 0);
    u_long m = unmoveMirror(q);
    if (m != q) n = unmoveRaw(m, out, n);
    return n;
}

// 初期化: 全探索の配列から手数の配列を作り, 配列をその場で残りの数に読み替える.
// キャッチ局面は手数 1 の勝ち, トライ負け局面は手数 0 の負け, キャッチ抜きの数が 0 の未知局面は手数 2 の負け.
// 返り値: 0 / -1 配列が無い / -3 確保できない
int unmoveInit(void) {
    uint64_t n = g_rank_range, r;
    if (!g_prep || !n) return -1;
    unmoveTableBuild();
    free(g_dtm);
    g_dtm = (uint8_t *)hugeAlloc((size_t)n);
    if (!g_dtm) return -3;
    for (r = 0; r < n; r++) {
        uint8_t v = g_prep[r];
        uint8_t d = v == 0 ? DTM_NONE : v == PREP_CATCH ? 1 : v == PREP_TRY ? 0 : v == 1 ? 2 : DTM_UNDECIDED;
        g_dtm[r] = d;
        g_prep[r] = (uint8_t)(v - 1);  // 未知局面ではキャッチ抜きの数. ほかの値は読まない
    }
    return 0;
}

// 後退解析の1段. 手数 nd − 1 で決まった局面 frontier[0..n) から前任を作り, 決まった前任を found に書く.
// odd が偽なら frontier は負け (前任は勝ちで手数 nd), 真なら勝ち (前任の残りの数を辺1本につき1つ減らし,
// 0 になったら負けで手数 nd). 前任の候補は, 手数が未定のものだけを残す (到達しない番号・決まった局面は捨てる).
// out[0] 書いた数 / out[1] 候補の数 / out[2] 未定で残った候補の数.
// 返り値: 0 / -1 引数 / -2 found があふれた / -4 残りの数を 0 から減らそうとした (数え方の誤り)
int unmoveStep(const u_long *frontier, size_t n, int odd, int nd, u_long *found, size_t found_cap,
               uint64_t *out) {
    u_long cand[UNMOVE_MAX];
    uint64_t r[UNMOVE_MAX];
    size_t nf = 0;
    uint64_t n_cand = 0, n_kept = 0;
    if (!out) return -1;
    out[0] = out[1] = out[2] = 0;
    if (!g_dtm || !g_prep || (n && !frontier) || !found) return -1;
    for (size_t i = 0; i < n; i++) {
        int nc = unmoveCandidates(frontier[i], cand), m = 0;
        n_cand += (uint64_t)nc;
        // 候補のランクを全部出して手数の行を取り寄せてから, 未定のものだけを残す (#20 / #30 と同じ形)
        for (int j = 0; j < nc; j++) {
            r[j] = rankOf(cand[j]);
            __builtin_prefetch(&g_dtm[r[j]], 1, 3);
        }
        for (int j = 0; j < nc; j++) {
            if (g_dtm[r[j]] != DTM_UNDECIDED) continue;
            cand[m] = cand[j];
            r[m++] = r[j];
            if (odd) __builtin_prefetch(&g_prep[r[j]], 1, 3);
        }
        n_kept += (uint64_t)m;
        for (int j = 0; j < m; j++) {
            uint64_t rr = r[j];
            // 同じ前任が同じ q の候補に2回以上出ることがある (辺の重複). 先の回で決まっていたら飛ばす
            if (g_dtm[rr] != DTM_UNDECIDED) continue;
            if (odd) {
                if (g_prep[rr] == 0) return -4;
                if (--g_prep[rr] != 0) continue;
            }
            if (nf >= found_cap) return -2;
            g_dtm[rr] = (uint8_t)nd;
            found[nf++] = cand[j];
        }
    }
    out[0] = nf;
    out[1] = n_cand;
    out[2] = n_kept;
    return 0;
}

// 手数 2 の負け (キャッチ抜きの数が 0 の未知局面) を, 全探索で見つけた順に dst に写す. 返り値は写した数 (-2 あふれ)
long unmoveZeros(u_long *dst, size_t cap) {
    if (g_zero_n > cap) return -2;
    if (g_zero_n) memcpy(dst, g_zero, g_zero_n * sizeof(u_long));
    return (long)g_zero_n;
}

// 引き分け (最後まで手数が未定の未知局面) を, 未知局面の列 uk[0..n) の順に集める. 返り値は数 (-1 引数 / -3 確保できない).
// 集めたものは unmoveDrawsPtr() で読む. 16 個先のランクを出して手数の行を取り寄せる
long unmoveDraws(const u_long *uk, size_t n) {
    size_t nd = 0;
    uint64_t rk[16];
    if (!g_dtm || (n && !uk)) return -1;
    free(g_draws);
    g_draws = (u_long *)malloc((n ? n : 1) * sizeof(u_long));
    if (!g_draws) return -3;
    for (size_t i = 0; i < n && i < 16; i++) {
        rk[i] = rankOf(uk[i]);
        __builtin_prefetch(&g_dtm[rk[i]], 0, 3);
    }
    for (size_t i = 0; i < n; i++) {
        uint64_t rr = rk[i % 16];
        if (i + 16 < n) {
            rk[i % 16] = rankOf(uk[i + 16]);
            __builtin_prefetch(&g_dtm[rk[i % 16]], 0, 3);
        }
        if (g_dtm[rr] == DTM_UNDECIDED) g_draws[nd++] = uk[i];
    }
    return (long)nd;
}

const u_long *unmoveDrawsPtr(void) {
    return g_draws;
}
