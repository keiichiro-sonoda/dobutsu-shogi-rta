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

#endif