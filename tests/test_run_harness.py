"""計測ハーネス (tools/run.sh) と、記録済み env.txt についての取り決め。"""

from __future__ import annotations

import re

from conftest import RESULTS_DIR, ROOT

RUN_SH = ROOT / "tools" / "run.sh"

# env.txt に必ず入っていてほしい項目 (計測機の同一性と再現性の担保)
REQUIRED_ENV_FIELDS = ("kernel", "cpu", "cores", "mem_total", "gcc", "python", "git_commit")


def test_run_sh_does_not_record_the_hostname() -> None:
    """ホスト名は公開する記録に載せない。計測機の同一性は cpu / cores / mem_total で足りる。"""
    script = RUN_SH.read_text(encoding="utf-8")
    assert "hostname" not in script, "tools/run.sh がホスト名を取得している"
    assert not re.search(r'^\s*echo\s+"host:', script, re.MULTILINE), (
        "tools/run.sh が env.txt に host: 行を書いている"
    )


def test_run_sh_still_records_the_machine_identity() -> None:
    """ホスト名を消したついでに他の項目まで落とさないこと。"""
    script = RUN_SH.read_text(encoding="utf-8")
    for field in REQUIRED_ENV_FIELDS:
        assert f'echo "{field}:' in script, f"env.txt から {field} が消えている"


def test_recorded_env_files_have_no_hostname() -> None:
    """results/ に置いた証拠にもホスト名を残さない。"""
    env_files = sorted(RESULTS_DIR.glob("*/env.txt"))
    assert env_files, "results/ に env.txt が無い"
    for path in env_files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not line.startswith("host:"), f"{path}:{lineno} にホスト名が残っている"
