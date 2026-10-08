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

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// 正しくない盤面に rankBoard が返す値 (記録 #8〜#33 の索引の番兵と同じ値. 索引は記録 #34 で無くなった)
#define INDEX_EMPTY (u_long)0xffffffffffffffff

// --------------------------------------------------------------------
// 全探索の「発見済み盤面」の集合 (記録 #11 で追加, #30 でランクのビット表に替えた)
//
// #10 まではこれが Python の set で, F3 集合化 311 秒 + F4 重複排除 498 秒
// (全探索の 43.1%) をそこに使っていた. #11 で C 側のハッシュ表 (最終 4 GiB) に移し,
// 後続を生成しているその場で重複判定まで済ませるようにした.
//
// #30 からは, 盤面から番号を計算で直接出す関数 (ランク) を作り, その番号を添字にした
// 1 ビットの表 (106.9 MB) で判定する. 作り方は animal_shogi.c の「ランクで引く到達済み
// ビット表」の見出しにある. 値域 (855,232,344) は駒の数と盤の形だけから seenInit で数え,
// 到達局面の数は使わない. 表は最初に1回だけ確保し, 作り直しは無い.
// --------------------------------------------------------------------

// 0=成功 / -3=確保できない. 既にあれば作り直す (件数と計数器も 0 に戻る)
int seenInit(void);

void seenFree(void);

// 1=新規に入った / 0=既に入っていた / -3=確保できない
// -4=盤面として正しくない値 (ライオンが盤上に1頭ずつでない, 駒の数が合わない, 番兵など)
int seenInsert(u_long key);

// keys を順に入れ, 新規に入った数を返す. 負ならエラー (seenInsert と同じ)
int seenInsertMany(const u_long *keys, uint32_t n);

u_long seenCount(void);          // 表に入っている件数 (立っているビットの数)
int seenContains(u_long key);    // 1=ある / 0=ない (テストと検算用)
u_long seenProbes(void);         // nextBoardSeenNormal が作った後続の総数
u_long seenRehashes(void);       // 詰め直した回数. ビット表には作り直しが無いので常に 0

// ランク (記録 #30). 正しい盤面なら 0 以上 rankRange() 未満, 正しくなければ INDEX_EMPTY.
// 正規化した (normalBoard を通した) 盤面どうしでは単射. ライオンが2頭とも中央の列に無い盤では,
// 鏡像どうしが同じ番号になる (鏡像をまとめたため)
u_long rankBoard(u_long b);
u_long rankRange(void);

// 盤面 b の後続を作り, すべて seen 表に登録し, **初見だったものだけ** を out に書く
//
// ⚠️ 名前が示す以上のことをしている. 返さなかった後続も含めて, 生成した後続は
//    すべて表に登録する. 分けて2回呼ぶ設計にすると FFI が局面ごとに2回になり,
//    246,803,167 回 x 約 1.5 us で 370 秒の追加になるので, ここは融合させている.
//
//  -1 : キャッチ勝ち (後続なし)   -2 : トライ負け
//  >=0: 未知. 初見だった後続の数. out[0..n-1] にそのパック値
//  -3 : 表を確保できない
//
// ⚠️ 戻り値の規約が nextBoardInvNormal (0=勝ち / -1=負け) と違う.
//    「未知だが初見の後続が0個」が起こりうるので, 0 を勝ちには使えない.
// out は MAX_ACTION_NUM 要素なければならない
// 記録 #34: rb は b のランク (待ち行列に一緒に積んだもの). 初見の後続のランクを out_rank に out と同じ並びで返す.
// b の種類とキャッチ抜きの数を, ランクを添字にした配列 (後退解析の準備) に書く. out_rank も MAX_ACTION_NUM 要素
int nextBoardSeenNormal(u_long b, uint32_t rb, u_long *out, uint32_t *out_rank);

// 後退解析の準備 (記録 #34). ランクを添字にした 1 バイトの配列 (0 到達しない / 1〜49 未知局面でキャッチ抜きの数 + 1 /
// 0xFE トライ負け / 0xFF キャッチ). 最初の nextBoardSeenNormal が確保する
const uint8_t *prepPtr(void);
u_long prepZeroCount(void);      // キャッチ抜きの数が 0 の未知局面の数
void prepFree(void);
// nextBoardInvNormal と同じ後続を同じ順で作り, *non_catch にキャッチ抜きの数を入れる
int nextBoardInvNormalNC(u_long b, u_long *nbs, int *non_catch);

// ---- 1ラウンドぶんの展開 (記録 #13) ---------------------------------------
//
// unexp[0..n-1] を **前から後ろへ** 走査し, 1局面ずつ nextBoardSeenNormal に通して
// 勝ち / 負け / 未知に振り分ける. #12 までは Python の while が 246,803,167 回
// まわしていたもので, FFI 越えとバッファ確保と list 生成がそのぶん乗っていた.
//
// ⚠️ 走査の向きを変えないこと. Python の set.pop() を繰り返した順は集合の反復順で,
//    array("Q", 集合) の並びがちょうどそれ. 逆から回すと採番順が変わり,
//    後退解析の局所性も dat/ のバイト列も動く.
//
// win / lose / uk は呼び出し側が n 要素ずつ確保して渡す (3本あわせてちょうど n 本).
// 初見の後続は C 側の伸びるバッファに溜まる. expandNewPtr / expandNewCount で取る.
// out は5要素. 戻り値に関わらず必ず埋める.
//   out[0]=勝ち数 out[1]=負け数 out[2]=未知数
//   out[3]=生成した後続の延べ数 (検算用) out[4]=処理し終えた入力の数
//
// n == 0 なら unexp / win / lose / uk は NULL でよい (空の array("Q") の
// buffer_info() が 0 を返すため. predCount と同じ扱い)
//
// 0=成功 / -1=引数不正 / -2=バッファを確保できない
// -3=発見済み表を伸ばせない / -4=知らない戻り値 (バグ)
//
// ⚠️ 0 以外が返ったら, そのラウンドはやり直せない. そこまでの局面の後続は
//    もう seen 表に入っているので, 同じ入力で呼び直すと全部「既出」になって
//    永久に拾えなくなる. 呼び出し側は走行ごと落とすこと.
//    expandRound はファイルを1つも書く前に走るので dat/ は無傷で, 再走できる.
// 記録 #34: unexp_rank[i] は unexp[i] のランク (待ち行列に一緒に積んだもの)
int expandRound(const u_long *unexp, const uint32_t *unexp_rank, uint32_t n,
                u_long *win, u_long *lose, u_long *uk, u_long *out);

// 直前の expandRound が積んだ初見の後続 (expandNewCount 要素) と, そのランク (記録 #34)
const u_long *expandNewPtr(void);
const uint32_t *expandNewRankPtr(void);
u_long expandNewCount(void);

// バッファを手放す (全探索が終わったら呼ぶ)
void expandFreeBuffer(void);

// ---- 後退解析: 一手前を直接作る (記録 #34) ------------------------------------------
//
// 記録 #33 までの P1 (索引)・P2 (後続を作る)・P4 (前任の表)・174段ループに替わる. 作りは animal_shogi.c の見出しにある.

// q の前任の候補 (正規形. キャッチ局面になるものは作らない. 到達しない局面も混ざる). out は 1024 要素
int unmoveCandidates(u_long q, u_long *out);

// 初期化: 準備の配列から手数の配列を作り, 準備の配列をその場で残りの数に読み替える.
// 0=成功 / -1=準備の配列が無い / -3=確保できない
int unmoveInit(void);

// 1段. frontier[0..n) (手数 nd − 1 で決まった局面) から前任を作り, 手数 nd で決まった前任を found に書く.
// odd == 0: frontier は負け (前任は勝ち) / odd != 0: frontier は勝ち (前任の残りの数を減らし, 0 なら負け).
// out は3要素: 書いた数, 候補の数, 手数が未定で残った候補の数. 戻り値に関わらず必ず埋める.
// 0=成功 / -1=引数不正 / -2=found の容量不足 / -4=残りの数を 0 から減らそうとした
// ⚠️ 異常終了のとき, 手数と残りの数の書き換えはそこまで済んでいる. その段をやり直すことはできない
int unmoveStep(const u_long *frontier, size_t n, int odd, int nd, u_long *found, size_t found_cap,
               uint64_t *out);

// 手数 2 の負け (キャッチ抜きの数が 0 の未知局面) を全探索で見つけた順に dst に写す. 返り値は数 (-2=容量不足)
long unmoveZeros(u_long *dst, size_t cap);

// 引き分け (手数が未定のまま残った未知局面) を, 未知局面の列 uk[0..n) の順に集める.
// 返り値は数 (-1=引数不正 / -3=確保できない). 集めたものは unmoveDrawsPtr() で読む
long unmoveDraws(const u_long *uk, size_t n);
const u_long *unmoveDrawsPtr(void);

#endif
