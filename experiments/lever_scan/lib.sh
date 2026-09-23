#!/bin/bash
# run_forward.sh と run_retreat.sh が共有する道具 (source して使う)
#
# ⚠️ ここに置くのは「測る側」だけ。腕の中身は make_arm.sh と patches/ にある

# 1分おきに CPU 周波数・温度・スロットル回数と, メモリの状態
# ⚠️ 列は experiments/numa_bind と同じ8列. 前半5列は tools/run.sh と同じ名前・順番
sample_hw() {
    while :; do
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$(TZ=Asia/Tokyo date +%Y-%m-%dT%H:%M:%S)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.0f", m/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{s+=$1; n++} END {if (n) printf "%.0f", s/n/1000}' \
                /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null || echo -)" \
            "$(awk '{if ($1>m) m=$1} END {if (NR) printf "%.1f", m/1000}' \
                /sys/class/thermal/thermal_zone*/temp 2>/dev/null || echo -)" \
            "$(cat /sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count 2>/dev/null || echo -)" \
            "$(awk '/^MemFree:/{print $2}' /proc/meminfo 2>/dev/null || echo -)" \
            "$(awk '/^Cached:/{print $2}' /proc/meminfo 2>/dev/null || echo -)" \
            "$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null || echo -)"
        sleep 60
    done
}
freq_header() {
    printf 'time_jst\tfreq_max_mhz\tfreq_mean_mhz\tpkg_temp_c\tthrottle\tmem_free_kb\tmem_cached_kb\tmem_available_kb\n'
}

# /proc/vmstat のカウンタ. 解析の直前と直後の2行だけ残し, 差分は読む側で引く.
# thp_* は巨大ページが付いたか (thp_fault_fallback は「頼んだが付かなかった」),
# compact_* はそのためのコンパクション, numa_* と pgmigrate_* は numa_bind と同じ.
# ⚠️ これはマシン全体の累積値. 走行中に他の計算を回していなければ,
#    差分はほぼこの走行のもの, と書けるだけ
VMSTAT_KEYS=(
    thp_fault_alloc thp_fault_fallback thp_collapse_alloc
    compact_stall compact_success compact_fail
    numa_hint_faults numa_hint_faults_local numa_pages_migrated
    numa_local numa_other pgmigrate_success pgmigrate_fail
)
vmstat_header() {
    printf 'when'
    printf '\t%s' "${VMSTAT_KEYS[@]}"
    printf '\n'
}
vmstat_row() {
    printf '%s' "$1"
    for k in "${VMSTAT_KEYS[@]}"; do
        printf '\t%s' \
            "$(awk -v k="$k" '$1==k {v=$2} END {print (v == "" ? "-" : v)}' /proc/vmstat)"
    done
    printf '\n'
}

# dat/ の md5 一覧の sha256. results/*/bytecompare.txt の recipe
#   cd <dat>; find . -type f -print0 | LC_ALL=C sort -z | xargs -0 md5sum | sha256sum
# と同じ値を, dat/ の中へ cd せずに出す (CLAUDE.md の .cc-writes の件)
md5_list_sha() {
    local d="${1%/}"
    find "$d" -type f -printf './%P\0' \
      | LC_ALL=C sort -z \
      | while IFS= read -r -d '' f; do
            printf '%s  %s\n' "$(md5sum "$d/${f#./}" | cut -d' ' -f1)" "$f"
        done \
      | sha256sum | cut -d' ' -f1
}

# driver.py の先頭に差し込む, 巨大ページの記録.
# 実装のソースは変えず, モジュールの関数を包んで, 表を捨てる直前に
# /proc/self/smaps_rollup の Rss と AnonHugePages を huge.txt に1行書く.
# ⚠️ 全腕で同じように取る (費用を腕で偏らせないため. base で 0 なら対照になる).
#    読む費用は searchAll の「解放」と retreatAnalysis の P2_free に入り,
#    判定に使う段 (F0〜F6, P0〜P4, 174段) には入らない
# shellcheck disable=SC2034  # run_forward.sh / run_retreat.sh が使う
HUGE_HOOK='
def _huge_line(where):
    vals = {}
    with open("/proc/self/smaps_rollup") as f:
        for line in f:
            k, _, v = line.partition(":")
            if k in ("Rss", "AnonHugePages"):
                vals[k] = int(v.split()[0])
    with open("huge.txt", "a") as f:
        f.write("%s\tRss_kB\t%d\tAnonHugePages_kB\t%d\n" % (where, vals["Rss"], vals["AnonHugePages"]))

def _wrap(name):
    real = getattr(mod, name)
    def wrapped():
        _huge_line(name + " の直前")
        return real()
    setattr(mod, name, wrapped)
'
