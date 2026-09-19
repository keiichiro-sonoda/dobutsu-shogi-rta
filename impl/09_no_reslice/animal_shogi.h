#ifndef ANIMAL_SHOGI_H
#define ANIMAL_SHOGI_H

#define INITIAL_BOARD (u_long)0x000a003c914b002

#define SAMPLE_BOARD01 (u_long)0x28000300c340000
// ひよこの成り, 持ち駒ひよこときりん
#define SAMPLE_BOARD02 (u_long)0x005c043a1000030
// にわとりキャッチ, 持ち駒ぞう
#define SAMPLE_BOARD03 (u_long)0x01005d003220c04
// トライチェック
#define SAMPLE_BOARD04 (u_long)0x51400045050000c

#define SAMPLE_BOARD05 (u_long)0x404c000db200504
// 最大の枝分かれ (多分)
#define SAMPLE_BOARD06 (u_long)0x02a0000c0400000
// 持ち駒の上限チェック
#define SAMPLE_BOARD07 (u_long)0x0150d000a40cb00

#define SAMPLE_BOARD08 (u_long)0x5100102c1040000

#define SAMPLE_BOARD09 (u_long)0x515c00000400500

// 表示する文字
#define DISPLAY_PEACES " hgelc"

// 取りうる手の最大値
// 多分38で十分だが, 念のため余裕を持たせる
#define MAX_ACTION_NUM 48

#define getKoma(b, adr) ((b) >> (adr) & 0xf)

#define delKoma(b, adr) ((b) & ((0xffffffffffffffff - (((u_long)1 << ((adr) + 4)) - 1)) | (((u_long)1 << (adr)) - 1)))

#define delKomaDouble(b, adr1, adr2) (delKoma(delKoma(b, adr1), adr2))

// 駒を置く
#define putKoma(b, adr, koma) ((b) | ((koma) << (adr)))

enum PEACES {EMPTY, CHICK1, GIRAFFE1, ELEPHANT1, LION1, CHICKEN1, CHICK2=9, GIRAFFE2, ELEPHANT2, LION2, CHICKEN2};

extern int GIRAFFE_MOVE[4];
extern int ELEPHANT_MOVE[4];
extern int LION_MOVE[8];
extern int CHICKEN2_MOVE[6];

void showBoard(u_long b);

// 盤面反転
u_long invBoard(u_long b);

// 左右対称盤面は数値が小さい方に正規化
u_long normalBoard(u_long b);

int nextBoardInvNormal(u_long b, u_long *nbs);

// --------------------------------------------------------------------
// 記録 #8: パック値 -> 連番 の索引をC側に置く
//
// Python の dict は 24.41 GiB に膨らんでキャッシュに全く乗らず,
// 1回の引きに約 0.85 us かかっていた. オープンアドレス法の平坦な表なら
// 本番 (246,803,167 件) で 8.59 GB に収まり, 1回の引きで触る
// キャッシュラインが1本で済む.
//
// キーと値を別配列にすると keys[slot] と vals[slot] で DRAM 往復が2回に
// なるので, 16 B のエントリ1本にまとめてある (ラインを跨がない).
// --------------------------------------------------------------------

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// 空きスロットの番兵. パック値は 60bit なので実在しない
// (indexBuild が入力にこの値が無いことを検査する)
#define INDEX_EMPTY (u_long)0xffffffffffffffff

// 乗算ハッシュ. 上位ビットほどよく混ざるので上から桁を取る
#define INDEX_MULT (u_long)0x9e3779b97f4a7c15

// スロット数は n 以上の 2 の冪のうち, 占有率が 0.5 を超えないものにする.
// 本番の 246,803,167 件なら 2^29 = 536,870,912 スロット (占有率 0.46) で
// 16 B x 2^29 = 8.59 GB. 小さな入力ではそのぶん小さく確保する
// (等価性テストが数千件で回るので, ここを固定にすると 8.59 GB を毎回掴む)
#define INDEX_MIN_BITS 4
#define INDEX_MAX_BITS 33

typedef struct {
    u_long key;
    uint32_t val;
    uint32_t pad;
} IndexEntry;

// 0=成功 / -1=引数不正 / -2=件数が多すぎる / -3=確保できない
// -4=入力に番兵と同じ値がある / -5=キーが重複している
int indexBuild(const u_long *packed, uint32_t n);

void indexFree(void);

// 既存の nextBoardInvNormal と同じ規約だが, out に書くのは連番 (uint32)
//  >0 : 後続数. out[0..n-1] に連番. すべて索引が引けた
//   0 : キャッチ            -1 : トライ負け
//  -2 : 索引外の後続があった. out には引けたぶんだけ.
//       out[MAX_ACTION_NUM]=引けた数, out[MAX_ACTION_NUM+1]=出次数
//  -3 : src が範囲外, または索引が未構築 (バグ)
// out は MAX_ACTION_NUM + 2 要素なければならない
int nextBoardIndexNormal(uint32_t src, uint32_t *out);

#endif