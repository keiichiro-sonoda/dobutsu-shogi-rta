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

// パック値 -> 連番 の索引 (オープンアドレス法・線形探査)
static IndexEntry *g_index = NULL;
// Python 側の array('Q') をそのまま指す. indexFree までリサイズしてはいけない
static const u_long *g_packed = NULL;
static uint32_t g_index_n = 0;
static size_t g_index_mask = 0;
// 乗算ハッシュの右シフト量 (= 64 - スロット数のビット幅)
static int g_index_shift = 0;

#define INDEX_SLOT(key) ((size_t)(((u_long)(key) * INDEX_MULT) >> g_index_shift))

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
// pred / pred_off / cnt / dtm を, 索引と同じ hugeAlloc で確保して fill で埋める. #24 まで
// Python の array / bytearray で確保していて, 4 KiB ページのままだった.
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
    // 2 MiB 境界に揃えて確保し, 巨大ページを頼む (記録 #21). 64B 境界より強いので,
    // エントリ (16 B) がキャッシュラインを跨がないことも保たれる
    g_index = (IndexEntry *)hugeAlloc(slots * sizeof(IndexEntry));
    if (!g_index) return -3;
    g_index_mask = slots - 1;
    g_index_shift = 64 - bits;
    // 0xff で埋めると key が INDEX_EMPTY になる
    memset(g_index, 0xff, slots * sizeof(IndexEntry));
    for (i = 0; i < (size_t)n; i++) {
        // 記録 #20: 16 個先のキーのスロットを先読みする. 挿入は乱択なので,
        // 1個ずつ待つと DRAM 往復がそのまま積み上がる (距離 16 は固定. 調整はしていない)
        if (i + 16 < (size_t)n) __builtin_prefetch(&g_index[INDEX_SLOT(packed[i + 16])], 1, 3);
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
    // 記録 #20: 全後続のスロットを先に取り寄せてから探査する. 後続は最大 48 個で,
    // 探査を1つずつ待たせずに DRAM 往復を重ねるため (nextBoardSeenNormal と同じ形)
    for (i = 0; i < nbn; i++) __builtin_prefetch(&g_index[INDEX_SLOT(nbs[i])], 0, 3);
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

int nextBoardSeenNormal(u_long b, u_long *out) {
    u_long nbs[MAX_ACTION_NUM];
    uint64_t r[MAX_ACTION_NUM];
    int nbn, i;
    int found = 0;
    if (!g_seen && seenInit() != 0) return -3;
    nbn = nextBoardInvNormal(b, nbs);
    // 0 = キャッチ勝ち / -1 = トライ負け. どちらも後続を持たない
    // ⚠️ ここで規約を付け替える. 「未知だが初見が0個」を 0 で返したいため
    if (nbn == 0) return -1;
    if (nbn < 0) return -2;
    g_seen_probes += (u_long)nbn;
    // 記録 #20 と同じ形: 全後続の番号を先に出してビット表の語を取り寄せ, そのあとで順に立てる.
    // 先読みはヒントなので書く値は変わらない. 返す順序は nbs の順のまま
    for (i = 0; i < nbn; i++) {
        r[i] = rankOf(nbs[i]);
        __builtin_prefetch(&g_seen[r[i] >> 6], 1, 3);
    }
    for (i = 0; i < nbn; i++) {
        if (seenTestAndSet(r[i])) out[found++] = nbs[i];
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
            // 記録 #20: 2段の先読み (距離 16 / 32 は固定. 調整はしていない).
            //
            // ① なぜ2段か. 書き込み先 pred[pred_off[q]] は pred_off[q] を読み終えるまで
            //    決まらない. 1辺ごとに「pred_off を読む → pred に書く」の DRAM 待ちが
            //    直列に並ぶので, 32 本先で pred_off[q] を, 16 本先で (もう届いている)
            //    その値から pred の書き込み先を取り寄せておく.
            // ② 16 本先で読んだ pred_off[q16] が古くても答えは変わらない. その間に同じ
            //    行き先の辺があるとカーソルが進み, 取り寄せる場所が1つ以上ずれる. 先読みは
            //    ヒントで, 実際の書き込みは下の本処理がその瞬間のカーソルで行う. ずれても,
            //    その辺が先読みしなかったときと同じだけ待つだけ.
            // ③ pred_off[q16] は先読みではなく本当に読むので, q16 < n_all を確かめてから読む.
            //    pred[pred_off[q16]] の先読みは末尾の1つ先を指しうるが, x86 の先読みは
            //    例外を出さない. succ は出発をまたいで連続しているので出発の境界は気にしない
            if (e + 32 < n_edges) __builtin_prefetch(&pred_off[succ[e + 32]], 1, 3);
            if (e + 16 < n_edges) {
                uint32_t q16 = succ[e + 16];
                if (q16 < n_all) __builtin_prefetch(&pred[pred_off[q16]], 1, 3);
            }
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
    if (!unexp || !win || !lose || !uk) return -1;
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

// ---- 174段ループの1段 (記録 #14) -------------------------------------------
//
// #13 までは Python の二重ループが辺 938,671,869 本を1本ずつ辿り、未知局面ごとに
// pred[pred_off[q]:pred_off[q + 1]] のスライスを作っていた。記録 #12 が P4 で
// 潰したのと同じ形なので、同じようにC側へ移す。
//
// ⚠️ static を1つも置かない。呼び出しをまたいで残る状態が無ければ、
//    記録 #13 の「空入力でリセットを飛ばす」型の不具合は起こりようがない。

int retreatStep(const uint32_t *pred, const uint32_t *pred_off,
                uint8_t *dtm, uint8_t *cnt, uint32_t n_all, uint32_t n_uk,
                const uint32_t *frontier, uint32_t lo, uint32_t hi,
                uint8_t nd, int odd,
                uint32_t *found, uint32_t found_cap, uint32_t *out) {
    uint32_t i, q, p, n_found = 0;
    size_t e, e_end;
    // ⚠️ どの早期 return よりも前に置く (記録 #13 の不具合がこの順序だった)
    if (!out) return -1;
    out[0] = 0;
    if (!pred_off || !dtm || !cnt) return -1;
    if (found_cap && !found) return -1;
    if (lo > hi) return -1;
    // 範囲モードは q = i なので、hi が n_all を超えたら pred_off の外を読む
    if (!frontier && hi > n_all) return -1;
    if (lo == hi) return 0;

    for (i = lo; i < hi; i++) {
        // 記録 #23: 2段の先読み. frontier[i] → pred_off[q] → pred[e] と, 前の読みの値で次の番地が
        // 決まる読みが続くので, DRAM 待ちが直列に並ぶ (#20 の前の P4_scatter と同じ形).
        // 32 個先の q で pred_off[q] を, 16 個先の q で (もう届いているはずの) pred_off[q] から
        // pred の読み出し先を取り寄せる. 距離 32 / 16 は #20 の predScatter と同じで, 調整していない.
        // ① 先読みはヒントで, 書く値は変わらない (dtm / cnt / found は下の本処理だけが書く)
        // ② frontier[i + k] と pred_off[q16] は先読みではなく本当に読むので, i + k < hi と
        //    q < n_all (と pred != NULL) を先に確かめる. 範囲モード (frontier == NULL) は q = i + k
        if (i + 32 < hi) {
            uint32_t q32 = frontier ? frontier[i + 32] : i + 32;
            if (q32 < n_all) __builtin_prefetch(&pred_off[q32], 0, 3);
        }
        if (pred && i + 16 < hi) {
            uint32_t q16 = frontier ? frontier[i + 16] : i + 16;
            if (q16 < n_all) __builtin_prefetch(&pred[pred_off[q16]], 0, 3);
        }
        q = frontier ? frontier[i] : i;
        // pred_off は n_all + 1 要素. q はその外を指してはいけない
        if (q >= n_all) return -3;
        e_end = pred_off[q + 1];
        for (e = pred_off[q]; e < e_end; e++) {
            p = pred[e];
            // 後続を持つのは未知局面だけ. cnt は n_uk 要素しかない
            if (p >= n_uk) return -3;
            if (odd) {
                // q が勝ち → 前任の残り出次数を減らす. 0 になったら後続が全部勝ちなので負け
                uint8_t v;
                // ⚠️ 0 から減らすと 255 に回る. Python 版は bytearray への代入で
                //    ValueError になるところなので、C も同じ場所で落とす
                if (cnt[p] == 0) return -4;
                v = (uint8_t)(cnt[p] - 1);
                cnt[p] = v;
                if (v != 0 || dtm[p] != 255) continue;
            } else {
                // q が負け → 前任は1手で勝てる
                if (dtm[p] != 255) continue;
            }
            if (n_found >= found_cap) return -2;
            dtm[p] = nd;
            found[n_found++] = p;
        }
    }
    out[0] = n_found;
    return 0;
}

// ---- P2 後続生成の一区間 (記録 #15) -----------------------------------------
//
// #14 までは Python の for が 99,485,568 回まわり, 局面ごとに
// nextBoardIndexNormal を呼んでいた. プログラムに最後まで残っていた
// 「局面ごとの FFI 往復」で, 記録 #13 が F1 で潰したのと同じ形.
//
// ⚠️ static を1つも置かない. どこまで進んだかは呼び出し側が持ち,
//    C は「中継バッファに書いた数」と「止まった局面番号」を返すだけ.

int buildSuccRange(uint32_t lo, uint32_t hi, uint32_t n_uk,
                   uint32_t *stage, uint32_t stage_cap,
                   uint32_t *succ_off, uint8_t *cnt, uint32_t base,
                   int64_t *out) {
    uint32_t i, written = 0, outside = 0, n_found, degree;
    uint32_t tmp[MAX_ACTION_NUM + 2];
    int k;
    // ⚠️ どの早期 return よりも前に 0 に戻す (記録 #13 の不具合がこの順序だった)
    if (!out) return -1;
    out[0] = out[1] = out[2] = out[3] = 0;
    if (!stage || !succ_off || !cnt) return -1;
    if (lo > hi) return -1;
    if (hi > n_uk) return -1;
    // 1局面ぶんも入らない中継バッファでは1周も進めず, 呼び出し側が無限に回る
    if (stage_cap < MAX_ACTION_NUM) return -1;
    out[1] = lo;

    for (i = lo; i < hi; i++) {
        // 1局面ぶん (最大 MAX_ACTION_NUM 本) の空きが無ければここで止まる.
        // 呼び出し側が succ に繋いでから, 続きの局面番号で呼び直す
        if (written + MAX_ACTION_NUM > stage_cap) break;
        // ⚠️ stage + written を直接渡さない. -2 の経路が tmp[MAX_ACTION_NUM] と
        //    tmp[MAX_ACTION_NUM+1] に件数を書くので, そのまま渡すと succ の中に
        //    件数が紛れ込む (次の局面が上書きするので結果は同じだが,
        //    それを読んで確かめないと分からない形になる)
        k = nextBoardIndexNormal(i, tmp);
        if (k > 0) {
            n_found = (uint32_t)k;
            degree = (uint32_t)k;
        } else if (k == -2) {
            // 全探索を打ち切った dat/ では, 後続がまだ発見されていないことがある
            // (小さいフィクスチャでの等価性検査がこの経路を通る. 本番では起きない).
            // 未発見の後続は永久に未確定なので, 辺は張らずに出次数にだけ数えておく
            n_found = tmp[MAX_ACTION_NUM];
            degree = tmp[MAX_ACTION_NUM + 1];
            // ⚠️ outside を足すのは n_found <= degree を確かめたあと (下の -8 の検査).
            //    記録 #15 は検査より前に足していた. out[2] は正常終了のときしか
            //    書かないので外には出なかったが, 検査を先に置くほうが素直
        } else {
            // 0 (キャッチ) と -1 (トライ負け) なら未知盤面に終端が混ざっている.
            // -3 は src が範囲外か索引が未構築. どれもバグなので区別せず落とす.
            // ⚠️ 戻り値をそのまま返すと -1 (トライ負け) が引数不正と区別できない
            out[1] = i;
            out[3] = k;
            return -5;
        }
        // 出次数は MAX_ACTION_NUM (48) 以下なので cnt (1バイト) に必ず入る.
        // ⚠️ 現行の nextBoardIndexNormal では起こらない. 不変条件が崩れたときに
        //    cnt を黙って切り詰めないための保険.
        //    記録 #15 はこの2つを -6 に束ねていて, n_found > degree で落ちたときに
        //    「出次数が cnt に収まらない」という嘘の説明が出た. 戻り値を分ける
        if (degree > 255) {
            out[1] = i;
            out[3] = degree;
            return -6;
        }
        // 発見済みの後続が出次数を超えることはない (前者は後者の部分集合).
        // ⚠️ out は4要素なので out[4] は書けない. degree はコード側で分かるが
        //    実行時には残らないので, 食い違った側の n_found を out[3] に入れる
        if (n_found > degree) {
            out[1] = i;
            out[3] = n_found;
            return -8;
        }
        // 未発見の後続は永久に未確定なので, 辺は張らずに出次数にだけ数えておく
        outside += degree - n_found;
        // succ_off は uint32. 辺の総数が収まらなくなったら黙って巻かせない
        if ((uint64_t)base + written + n_found > (uint64_t)UINT32_MAX) {
            out[1] = i;
            return -7;
        }
        memcpy(stage + written, tmp, sizeof(uint32_t) * n_found);
        written += n_found;
        cnt[i] = (uint8_t)degree;
        succ_off[i + 1] = base + written;
    }
    out[0] = written;
    out[1] = i;
    out[2] = outside;
    return 0;
}

// ---- 連番 → パック値 の翻訳 (記録 #19) --------------------------------------
//
// #18 まで, 億単位のループで Python に残っていたのは「出力の準備」の2か所だけ.
//   ① 174段ループ   [packed[i] for i in found]                96,802,868 回
//   ② 引き分けの抽出 [packed[i] for i in range(n_uk) if ...]  99,485,568 回走査
// 後退解析は連番で動くが dat/ に書くのはパック値で, その翻訳が Python に残っていた.
// どちらも平たい配列から平たいバイト列を作るのに PyLong を2個ずつ起こしている.
// 記録 #16 (読む側) ・ #17 (書く側) とまったく同じ形の3回目.
//
// ⚠️ indexFree() が g_packed を NULL にしているので, C はもう packed を持っていない.
//    どちらの関数も呼び出し側から引数で受け取る.

// found[0..n) の連番を packed で引いて out に詰める.
//
// 出力の長さは n ちょうどなので, 呼び出し側が確保して渡す.
// ⚠️ 記録 #13 ・ #15 のような「容量不足からの再開」は要らない.
//
// 0=成功 / -1=引数不正 / -3=範囲違反 (found の値が n_all 以上)
int gatherPacked(const u_long *packed, uint32_t n_all,
                 const uint32_t *found, uint32_t n, u_long *out) {
    uint32_t j, v;
    if (!packed) return -1;
    // n == 0 なら found も out も NULL でよい (空の array("Q") のアドレスは 0 になる)
    if (n && (!found || !out)) return -1;
    for (j = 0; j < n; j++) {
        v = found[j];
        // packed の外を読まない. found は174段ループが書いた連番なので
        // 壊れていれば黙って別の局面を書き出すことになる (記録 #14 と同じ理由)
        if (v >= n_all) return -3;
        out[j] = packed[v];
    }
    return 0;
}

// dtm[0..n_uk) を走査し, 255 (＝最後まで未確定＝引き分け) のところの packed を
// out に詰める. 書いた数は n_out[0] に返す.
//
// ⚠️ 出力の長さが事前に分からないが, ここは2周すればよい.
//   1周目: out に NULL を渡して数える (1.0 億バイトの直線走査)
//   2周目: 呼び出し側がちょうどの長さを確保してから詰める
// 2周しても 2.0 億バイトの読み出しで, 伸びるバッファを持ち込む理由にならない.
//
// ⚠️ packed が n_uk 要素以上あることは呼び出し側が保証する (n_uk <= n_all).
//    走査するのは添字そのもので, データから来る値ではない.
//
// 0=成功 / -1=引数不正 / -2=out の容量不足
int gatherDraws(const u_long *packed, const uint8_t *dtm, uint32_t n_uk,
                u_long *out, uint32_t out_cap, uint32_t *n_out) {
    uint32_t i, k = 0;
    // ⚠️ どの早期 return よりも前に 0 に戻す (記録 #13 の不具合がこの順序だった)
    if (!n_out) return -1;
    n_out[0] = 0;
    if (!packed || !dtm) return -1;
    if (out_cap && !out) return -1;
    for (i = 0; i < n_uk; i++) {
        if (dtm[i] != 255) continue;
        if (out) {
            if (k >= out_cap) return -2;
            out[k] = packed[i];
        }
        k++;
    }
    n_out[0] = k;
    return 0;
}
