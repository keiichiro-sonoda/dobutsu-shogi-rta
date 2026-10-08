/* 記録 #33: 熱い関数の置き場所を固定する. 記録 #34 で一覧を作り替えた (後退解析の P1・P2・P4・174段ループの関数が
 * 無くなり, 準備を書く生成器と一手前を直接作る後退解析の関数が入った).
 *
 * gcc の -ffunction-sections で関数ごとに .text.<関数名> の区画を作り, ここで熱い関数だけを拾って
 * .text の前の専用の区画 .text.hot_layout に並べる. 既定のリンカースクリプトに足すだけ (INSERT).
 *
 * - 区画の先頭は 4 KiB の区切り. 前にある .init / .plt が伸びても (新しい libc の関数を呼ぶなど),
 *   熱い関数のページの中の位置は変わらない
 * - 熱い関数の先頭はそれぞれ 64 バイトの区切り. 並びは #32 の .so と同じ (C のファイルの順)
 * - 熱くない関数は後ろの .text に入るので, 変えても熱い関数は動かない
 * - normalBoard は入れない. 呼び出し元 (nextBoardInvNormal) に全部インライン展開されていて,
 *   外にある実体は Python から ctypes で引けるだけで, 解析の中では実行されない (perf で標本 0)
 *
 * 熱い関数を足したら, ここに1行足す. 書き漏らすと .text に入り, 置き場所が固定されない
 * (tests/test_impl_33_hot_layout.py が, 一覧の関数が全部この区画にあることを見ている).
 */
SECTIONS
{
  .text.hot_layout : ALIGN(4096)
  {
    *(.text.invBoard)
    . = ALIGN(64); *(.text.nextBoardInvNormal)
    . = ALIGN(64); *(.text.nextBoardInvNormalNC)
    . = ALIGN(64); *(.text.nextBoardSeenNormal)
    . = ALIGN(64); *(.text.expandRound)
    . = ALIGN(64); *(.text.unmoveCandidates)
    . = ALIGN(64); *(.text.unmoveInit)
    . = ALIGN(64); *(.text.unmoveStep)
    . = ALIGN(64); *(.text.unmoveDraws)
  }
}
INSERT BEFORE .text;
