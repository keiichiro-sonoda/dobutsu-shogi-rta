"""短い偽実装を実行し、計測ハーネスの終了コードと成果物を確認する。"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
from conftest import ROOT, DistRow
from test_verify_log import render_log


@pytest.mark.parametrize(
    ("analysis_exit", "log_kind", "expected_exit"),
    [(0, "valid", 0), (42, "valid", 42), (0, "invalid", 1), (0, "missing", 1)],
)
def test_harness_reports_analysis_and_verification_failures(
    tmp_path: pathlib.Path,
    distribution: list[DistRow],
    analysis_exit: int,
    log_kind: str,
    expected_exit: int,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("run.sh", "verify_log.py"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    shutil.copytree(ROOT / "oracle", tmp_path / "oracle")
    impl = tmp_path / "implementation with spaces"
    impl.mkdir()
    (impl / "impl.env").write_text(
        'BUILD_CMD="true"\nRUN_CMD="python3 solver.py"\nMAIN_LOG="custom.log"\n',
        encoding="utf-8",
    )
    log = render_log(distribution) if log_kind == "valid" else "incomplete\n"
    script = "from pathlib import Path\n"
    if log_kind != "missing":
        script += f"Path('custom.log').write_text({log!r}, encoding='utf-8')\n"
    script += f"raise SystemExit({analysis_exit})\n"
    (impl / "solver.py").write_text(script, encoding="utf-8")

    # 空き容量チェックだけを代替し、CI のディスク容量に依存させない。
    # この実装は数KBのログしか作らない。
    launcher = 'df() { printf "Avail\\n100G\\n"; }; export -f df; bash "$@"'
    result = subprocess.run(
        ["bash", "-c", launcher, "test", str(tools / "run.sh"), str(impl), "trial"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == expected_exit, result.stdout + result.stderr
    work_dirs = list((tmp_path / "runs").glob("*_trial"))
    assert len(work_dirs) == 1
    work = work_dirs[0]
    assert f"成果物: {work}" in result.stdout + result.stderr
    assert (work / "solver.py").read_text(encoding="utf-8") == script
    assert not (impl / "custom.log").exists(), "実装元へログを書いてはいけない"
    assert f"Exit status: {analysis_exit}" in (work / "time.txt").read_text(encoding="utf-8")

    # ハードウェアのサンプラ。1本目は同期で書くので、一瞬で終わる実行でも残る
    freq_lines = (work / "freq.log").read_text(encoding="utf-8").splitlines()
    assert freq_lines[0].split("\t") == [
        "time_jst",
        "freq_max_mhz",
        "freq_mean_mhz",
        "pkg_temp_c",
        "throttle",
    ]
    assert len(freq_lines) >= 2, "データ行が1本も無い"
    assert len(freq_lines[1].split("\t")) == 5
    if log_kind == "valid":
        assert "PASS: 174 行すべて一致" in result.stdout
    elif log_kind == "invalid":
        assert "FAIL:" in result.stdout
    else:
        assert "メインログが無い" in result.stderr
