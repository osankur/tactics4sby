"""CLI tests such as

    python ag4sby.py -f tests/strategy0.json

Coverage of the subprocess is collected thanks to
``[tool.coverage.run] patch = ["subprocess"]`` in ``pyproject.toml``, so these
tests contribute to the same report as the in-process unit tests.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
AG4SBY = REPO_ROOT / "ag4sby.py"

PARAM_STRATEGIES = ["strategy0", "strategy2"]
OTHER_STRATEGIES = [
    "cyclic",
    "strategy1",
    "strategy3",
    "strategy_err0",
    "strategy_err1",
    "strategy_err2",
    "ag_w_asserts",
    "ag_w_asserts_err0",
]


def run_main_program(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AG4SBY), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def run_sby(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    sby = shutil.which("sby")
    assert sby is not None, "sby executable not found on PATH"
    return subprocess.run(
        [sby, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def sby_output(result: subprocess.CompletedProcess[str]) -> str:
    """Format an sby run's output for an assertion message."""
    return (
        f"sby exited with {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A scratch copy of the fixtures the example strategies need.

    The tool resolves a strategy's relative paths against the directory
    containing the strategy file and writes ``<strategy>.sby`` next to it, so
    each test gets its own directory.  This keeps the repository clean and
    lets the tests run in parallel.
    """
    for name in (
        "module_dep0.sv",
        "module_dep1.sv",
        "module_dep2.sv",
        "module_dep3.sv",
        "cyclic.sv",
        "ag_w_asserts.sv",
    ):
        shutil.copy(TESTS_DIR / name, tmp_path / name)
    for name in PARAM_STRATEGIES + OTHER_STRATEGIES:
        shutil.copy(TESTS_DIR / f"{name}.json", tmp_path / f"{name}.json")
    return tmp_path


@pytest.mark.parametrize("name", PARAM_STRATEGIES)
def test_cli_output_is_deterministic(workdir: Path, name: str):
    """Running the tool twice produces byte-identical output."""
    assert run_main_program("-f", f"{name}.json", cwd=workdir).returncode == 0
    first = (workdir / f"{name}.sby").read_text(encoding="utf-8")

    assert run_main_program("-f", f"{name}.json", cwd=workdir).returncode == 0
    second = (workdir / f"{name}.sby").read_text(encoding="utf-8")

    assert first == second


def test_cli_refuses_to_overwrite_without_force(workdir: Path):
    """Without ``-f`` an existing ``.sby`` is left untouched."""
    assert run_main_program("-f", "strategy0.json", cwd=workdir).returncode == 0
    result = run_main_program("strategy0.json", cwd=workdir)
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_cli_strategy0_ag_vc(workdir: Path):
    assert (
        run_main_program(
            "-f", "strategy0.json", "--tmp-dir", str(workdir), cwd=workdir
        ).returncode
        == 0
    )
    result = run_sby("-f", str(workdir / "strategy0.sby"), cwd=workdir)
    assert result.returncode == 0, sby_output(result)
    main_log = (workdir / "strategy0__vc_main_top/model/design.log").read_text(
        encoding="utf-8"
    )
    # The proof of the top module leaves top assume and asserts, and converts submodules asserts to assumes
    assert (
        """Remaining assumes for this VC:
main/s1.subm_assert1
main/top_assumption1
Remaining asserts for this VC:
main/top_property1"""
        in main_log
    )
    s1_log = (workdir / "strategy0__vc_main_s1_/model/design.log").read_text(
        encoding="utf-8"
    )
    # The proof of the instance s1 removes top asserts, removes s1's asserts, and converts s1's assumes to assert
    assert (
        """Remaining assumes for this VC:
main/top_assumption1
Remaining asserts for this VC:
main/s1.subm_assume1"""
        in s1_log
    )


def test_cli_strategy2_ag_vc(workdir: Path):
    assert (
        run_main_program(
            "-f", "strategy2.json", "--tmp-dir", str(workdir), cwd=workdir
        ).returncode
        == 0
    )
    assert (
        run_main_program(
            "strategy2.json", "--tmp-dir", str(workdir), cwd=workdir
        ).returncode
        != 0
    )
    assert (
        run_main_program(
            "-f", "strategy2.json", "--tmp-dir", str(workdir), cwd=workdir
        ).returncode
        == 0
    )
    result = run_sby("-f", str(workdir / "strategy2.sby"), cwd=workdir)
    assert result.returncode == 0, sby_output(result)
    main_log = (workdir / "strategy2__vc_main_top/model/design.log").read_text(
        encoding="utf-8"
    )
    # The proof of the top module leaves top assume and asserts, and converts submodules asserts to assumes
    # The asserts and the top assume are anonymous in this case
    main_pattern = r"""
Remaining assumes for this VC:
main/\$flatten\\s2\.\$assert\$module_dep2\.sv:[^\n]*
main/\$flatten\\s1\.\$assert\$module_dep2\.sv:[^\n]*
main/\$assume\$module_dep2\.sv:[^\n]*
Remaining asserts for this VC:
main/top_assert
"""
    assert re.search(main_pattern, main_log), main_log
    s1_pattern = r"""Remaining assumes for this VC:
main/\$assume\$module_dep2\.sv:[^\n]*
Remaining asserts for this VC:
main/s1\.subm_assume1"""
    s1_log = (workdir / "strategy2__vc_main_s1_/model/design.log").read_text(
        encoding="utf-8"
    )
    assert re.search(s1_pattern, s1_log), s1_log

    # The proof of the instance s1 assumes top assumes and s1's asserts, and proves s2's assume
    s2_pattern = r"""Remaining assumes for this VC:
main/\$flatten\\s1\.\$assert\$module_dep2\.sv:[^\n]*
main/\$assume\$module_dep2\.sv:[^\n]*
Remaining asserts for this VC:
main/s2\.subm_assume1"""
    s2_log = (workdir / "strategy2__vc_main_s2_/model/design.log").read_text(
        encoding="utf-8"
    )
    assert re.search(s2_pattern, s2_log), s2_log


def test_cli_cyclic_dep_graph(workdir: Path):
    # The dependency graph is logged at debug level, so run with -vv.
    result = run_main_program("-vv", "-f", "cyclic.json", cwd=workdir)
    assert result.returncode == 0
    dep_graph = """
\\s1 depends on:
\t\\s2
\\s2 depends on:
\t\\s1"""
    assert dep_graph in result.stderr

    result = run_main_program("-vv", "-f", "strategy1.json", cwd=workdir)
    assert result.returncode == 0
    dep_graph = """
\\s1 depends on:
\\s2 depends on:
\t\\s1

"""
    assert dep_graph in result.stderr

    result = run_main_program("-vv", "-f", "strategy3.json", cwd=workdir)
    assert result.returncode == 0
    dep_graph = """
\\s1 depends on:
\\s2 depends on:
\t\\s1
\\s3 depends on:
\t\\s2

"""
    assert dep_graph in result.stderr


def test_cli_strategies_w_errors(workdir: Path):
    result = run_main_program("-f", "strategy_err0.json", cwd=workdir)
    assert result.returncode != 0
    assert (
        "s1 is an instance of module subm but there is no objective for this module"
        in result.stderr
    )
    result = run_main_program("-f", "strategy_err1.json", cwd=workdir)
    assert result.returncode != 0
    assert "No module, module instance, or assert found with name  s_" in result.stderr

    result = run_main_program("-f", "strategy_err2.json", cwd=workdir)
    assert result.returncode != 0
    "s1 is an instance of module subm but there is no objective for this module" in result.stderr

    result = run_main_program("-f", "ag_w_asserts_err0.json", cwd=workdir)
    assert result.returncode != 0
    assert (
        "No module, module instance, or assert found with name  top_assumption1"
        in result.stderr
    )
