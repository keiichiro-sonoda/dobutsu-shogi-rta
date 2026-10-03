// ランクが #28 の成果物の全局面で単射かを確かめる (門番 #30。記録試行ではない)
//
//   gcc -O2 -march=native -I impl/30_rank_seen -o rank_check experiments/gate_30_rank_seen/rank_check.c
//   ./rank_check <dat/>
//
// impl/30_rank_seen/animal_shogi.c をそのまま取り込み (main は名前を替えて外す), dat/ の全ファイルの
// 全局面について rankBoard を出す. 正しくない盤面 (INDEX_EMPTY), 値域の外, 同じ番号が2度出たものを数える.
// 同じ番号の検出は, 値域ぶんのビット表 (106.9 MB) で行う
#define main animal_shogi_main
#include "animal_shogi.c"
#undef main
#include <dirent.h>

int main(int argc, char **argv) {
    DIR *d;
    struct dirent *ent;
    uint64_t range, invalid = 0, outside = 0, dup = 0, total = 0, files = 0;
    uint8_t *bits;
    static u_long buf[1 << 20];
    if (argc != 2) {
        fprintf(stderr, "usage: %s <dat/>\n", argv[0]);
        return 2;
    }
    range = rankRange();
    bits = calloc(range / 8 + 1, 1);
    d = opendir(argv[1]);
    if (!d || !bits) return 2;
    while ((ent = readdir(d))) {
        char path[4096];
        FILE *f;
        size_t n, i;
        if (ent->d_name[0] == '.') continue;
        snprintf(path, sizeof path, "%s/%s", argv[1], ent->d_name);
        f = fopen(path, "rb");
        if (!f) return 2;
        files++;
        while ((n = fread(buf, sizeof(u_long), 1 << 20, f)) > 0) {
            for (i = 0; i < n; i++) {
                u_long r = rankBoard(buf[i]);
                total++;
                if (r == INDEX_EMPTY) { invalid++; continue; }
                if (r >= range) { outside++; continue; }
                if (bits[r >> 3] & (1u << (r & 7))) dup++;
                bits[r >> 3] |= (uint8_t)(1u << (r & 7));
            }
        }
        fclose(f);
    }
    closedir(d);
    printf("range\t%lu\nfiles\t%lu\npositions\t%lu\ninvalid\t%lu\noutside\t%lu\nduplicates\t%lu\n",
           (unsigned long)range, (unsigned long)files, (unsigned long)total, (unsigned long)invalid,
           (unsigned long)outside, (unsigned long)dup);
    printf("ratio\t%.4f\n", (double)range / (double)total);
    printf("%s\n", (invalid || outside || dup) ? "FAIL" : "PASS: injective on all positions");
    return (invalid || outside || dup) ? 1 : 0;
}
