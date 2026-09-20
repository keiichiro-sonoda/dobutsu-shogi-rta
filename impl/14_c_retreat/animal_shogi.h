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

// --------------------------------------------------------------------
// 全探索の「発見済み盤面」の集合 (記録 #11 で追加)
//
// #10 まではこれが Python の set で, F3 集合化 311 秒 + F4 重複排除 498 秒
// (全探索の 43.1%) をそこに使っていた. C 側の平坦な表に移し,
// 後続を生成しているその場で重複判定まで済ませる.
//
// 上の索引 (indexBuild) とは用途が違う. あちらは「パック値 → 連番」の写像で
// 値を持つ必要があるので 16 B/エントリ. こちらは存在判定だけなので
// キー 8 B だけでよい. 本番 (246,803,167 件) は 2^29 スロット x 8 B = 4.29 GB
// (占有率 0.46). 番兵と乗算ハッシュは索引と同じものを使う.
//
// ⚠️ 初期サイズに既知の総数 (246,803,167) を使わない. 事前に計算した表を
//    持ち込んだように見える余地を作らないため. 小さく確保して, 占有率が
//    0.5 を超えるたびに倍にして詰め直す (延べの詰め直しは件数の約2倍で済む).
// --------------------------------------------------------------------

// 最初のスロット数 2^20 (8 MB). ここから倍々に育てる
#define SEEN_MIN_BITS 20
// 2^33 スロットまで. 本番は 2^29 で止まる
#define SEEN_MAX_BITS 33

// 0=成功 / -3=確保できない. 既にあれば作り直す (件数と計数器も 0 に戻る)
int seenInit(void);

void seenFree(void);

// 1=新規に入った / 0=既に入っていた / -3=確保できない / -4=番兵と同じ値
int seenInsert(u_long key);

// keys を順に入れ, 新規に入った数を返す. 負ならエラー (seenInsert と同じ)
// ディスクから発見済み盤面を読み直す経路 (buildSeenBoards) 用で,
// ファイル1つにつき1回だけ呼ぶ
int seenInsertMany(const u_long *keys, uint32_t n);

u_long seenCount(void);          // 表に入っている件数
int seenContains(u_long key);    // 1=ある / 0=ない (テストと検算用)
u_long seenProbes(void);         // nextBoardSeenNormal が作った後続の総数
                                 // (buildSeenBoards の挿入は数えない)
u_long seenRehashes(void);       // 詰め直した回数

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
int nextBoardSeenNormal(u_long b, u_long *out);

// --------------------------------------------------------------------
// 前任リストの計数ソート (記録 #12 で追加)
//
// #11 まではこれが純 Python で, P4 は 548 秒 (全体の 25.8%, 後退解析の 47.5%) と
// 単独最大の段だった. 9億3867万辺を2周する計数ソートで, 1辺あたり
// array の要素アクセスが4回, さらに未知局面ごとに succ のスライスを作っていた.
//
// succ / succ_off / pred / pred_off はどれも array("I") の連続バッファなので,
// ゼロコピーでこちらに渡せる. 確保は Python 側のまま (後段の174段ループが
// そのまま array として使うので, 所有権を動かさない).
//
// ⚠️ 走査順は Python 版と同じ (src 昇順, その中は succ の順). 変えると pred の
//    並びが変わり, 成果物のチャンクの中身まで動く.
// --------------------------------------------------------------------

// 1周目: 入次数を数えて前置和にする.
// pred_off[q+1] に数えてから累積するので, 出来上がりがそのままオフセットになる
// (Python 版の indeg → itertools.accumulate と同じ形).
// pred_off は n_all + 1 要素なければならない. 中身は上書きする
//
// 0=成功 / -1=引数不正 / -2=後続の番号が範囲外, または総数が合わない
int predCount(const uint32_t *succ, size_t n_edges, uint32_t n_all, uint32_t *pred_off);

// 2周目: pred に散らす.
// ⚠️ カーソルの複製 (Python 版の cur = pred_off[:n_all], 本番で 987 MB) を作らない.
//    pred_off を直接進めて, 最後に1つずらして戻す.
// pred は n_edges 要素, pred_off は predCount が埋めたものでなければならない
//
// 0=成功 / -1=引数不正 / -2=succ_off が単調でない, または総数が合わない
int predScatter(const uint32_t *succ, size_t n_edges,
                const uint32_t *succ_off, uint32_t n_uk,
                uint32_t n_all, uint32_t *pred, uint32_t *pred_off);

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
int expandRound(const u_long *unexp, uint32_t n,
                u_long *win, u_long *lose, u_long *uk, u_long *out);

// 直前の expandRound が積んだ初見の後続 (expandNewCount 要素)
const u_long *expandNewPtr(void);
u_long expandNewCount(void);

// バッファを手放す (全探索が終わったら呼ぶ)
void expandFreeBuffer(void);

// ---- 174段ループの1段 (記録 #14) -------------------------------------------
//
// フロンティア q を順に見て、その前任 p を pred[pred_off[q] .. pred_off[q+1]-1] で
// 辿り、確定したものを found に書く。#13 までは Python の二重ループだった。
//
// frontier == NULL なら [lo, hi) の範囲そのものをフロンティアとする
// (深さ0 のトライ負けの範囲と、深さ1 のキャッチの範囲がこれ)。
// frontier != NULL なら frontier[lo .. hi-1] を見る。
//
// odd == 0: q が負け → 未確定の前任を nd で確定させる
// odd != 0: q が勝ち → cnt[p] を1減らし、0 かつ未確定なら nd で確定させる
//
// ⚠️ 走査の順を変えないこと。found の並びがそのまま dat/ のバイト列を決める
//    (writeWLFilesForDepth が set(...) に包んで pickle するため)。
//
// ⚠️ カーソルは呼び出し側が持つ。found には「書き始める位置」のポインタと
//    そこからの空き容量を渡し、C は書いた数を out[0] で返すだけ。
//    C 側に件数を覚えさせない (記録 #13 の空入力の不具合がその形だった)。
//
// out は1要素。戻り値に関わらず必ず埋める。
//
// 0=成功 / -1=引数不正 / -2=found の容量不足
// -3=範囲違反 (q >= n_all または p >= n_uk) / -4=cnt が 0 なのに減らそうとした
//
// ⚠️ -4 は Python 版が bytearray への代入で ValueError になっていたところ。
//    出次数より多く減らしているので、CSR かカウンタが壊れている
int retreatStep(const uint32_t *pred, const uint32_t *pred_off,
                uint8_t *dtm, uint8_t *cnt, uint32_t n_all, uint32_t n_uk,
                const uint32_t *frontier, uint32_t lo, uint32_t hi,
                uint8_t nd, int odd,
                uint32_t *found, uint32_t found_cap, uint32_t *out);

#endif
