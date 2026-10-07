#!/bin/bash
# run_*.sh が使う道具 (source して使う). experiments/unmove_prune/lib.sh の写し (sample_hw と freq_header) に, 空きの記録 (free_snapshot) を足した
# 1分おきに CPU 周波数・温度・スロットル回数と, メモリの状態
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
# 巨大ページに使える空き (各ノードの 2 MiB 以上の空きブロックの合計) と負荷を, ファイルに1組足す.
# 画面で読むだけにしない (CLAUDE.md「空きの値は手で読むだけにせず残す」). ノード0 が下限に満たなければ 1 を返す
#   free_snapshot <書き足すファイル> <見出し> <ノード0 の下限 GiB>
free_snapshot() {
    local out="$1" label="$2" min="$3" n0
    n0=$(awk '$2 == "0," && $4 == "Normal" {s = 0; for (i = 14; i <= NF; i++) s += $i * 2 ^ (i - 5) * 4 / 1024 / 1024; printf "%.2f", s}' /proc/buddyinfo)
    {
        echo "=== $label $(date --iso-8601=seconds) ==="
        awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
        awk '$4 == "Normal" {s = 0; for (i = 14; i <= NF; i++) s += $i * 2 ^ (i - 5) * 4 / 1024 / 1024; printf "node%s の 2 MiB 以上の空きブロック: %.2f GiB\n", substr($2, 1, length($2) - 1), s}' /proc/buddyinfo
        grep -E 'Node 0, zone +Normal' /proc/buddyinfo
        echo "下限 (ノード0): $min GiB"
    } >> "$out"
    awk -v a="$n0" -v b="$min" 'BEGIN {exit !(a >= b)}'
}
