"""Keep ``proof_strategy.schema.json`` in sync with :mod:`parser`.

The schema is the editor-facing description of a strategy file; the parser is
the implementation that actually accepts or rejects one.  These tests make sure
the two agree on every strategy file shipped in the repository, so a change to
the parser that is not mirrored in the schema (or vice versa) fails the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from parser import ProofStrategyError, parse_file

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "proof_strategy.schema.json"

KNOWN_INVALID = {}


def strategy_files() -> list[Path]:
    """Every strategy JSON file shipped in the repository."""
    files = sorted((REPO_ROOT / "tests").glob("*.json"))
    files += sorted((REPO_ROOT / "examples").glob("*.json"))
    return files


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def errors_for(path: Path) -> list:
    validator = Draft202012Validator(load_schema())
    return sorted(validator.iter_errors(json.loads(path.read_text())), key=str)


def test_schema_is_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(load_schema())


@pytest.mark.parametrize(
    "path",
    [path for path in strategy_files() if path.name not in KNOWN_INVALID],
    ids=lambda path: f"{path.parent.name}/{path.name}",
)
def test_shipped_strategy_validates(path: Path) -> None:
    parse_file(path)  # the parser is the reference implementation
    errors = errors_for(path)
    assert not errors, "\n".join(str(error) for error in errors[:5])


@pytest.mark.parametrize(
    "path",
    [path for path in strategy_files() if path.name in KNOWN_INVALID],
    ids=lambda path: f"{path.parent.name}/{path.name}",
)
def test_schema_rejects_stale_fixture(path: Path) -> None:
    with pytest.raises(ProofStrategyError):
        parse_file(path)
    assert errors_for(path)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            {"proof_strategy": {"files": [], "goal": {"module": "m"}}}, id="no-header"
        ),
        pytest.param(
            {"proof_strategy": {"header": [], "files": [], "goal": {}}},
            id="no-module",
        ),
        pytest.param(
            {
                "proof_strategy": {
                    "header": [],
                    "files": [],
                    "goal": {"module": "m", "tactic": {"name": "bogus"}},
                }
            },
            id="unknown-tactic",
        ),
        pytest.param(
            {
                "proof_strategy": {
                    "header": [],
                    "files": [],
                    "goal": {"module": "m", "tactic": {}},
                }
            },
            id="empty-tactic",
        ),
        pytest.param(
            {
                "proof_strategy": {
                    "header": [],
                    "files": [],
                    "goal": {
                        "module": "m",
                        "tactic": {
                            "name": "assume_guarantee",
                            "auto": False,
                        },
                    },
                }
            },
            id="manual-order-without-instances",
        ),
        pytest.param(
            {
                "proof_strategy": {
                    "header": [],
                    "files": [],
                    "goal": {
                        "module": "m",
                        "tactic": {
                            "name": "assume_guarantee",
                            "instances": [{"name": "s"}],
                            "inline": ["s"],
                        },
                    },
                }
            },
            id="instances-and-inline",
        ),
        pytest.param(
            {
                "proof_strategy": {
                    "header": [],
                    "files": [],
                    "goal": {
                        "module": "m",
                        "tactic": {"name": "abstract", "commands": ["select w"]},
                    },
                }
            },
            id="bad-abstract-command",
        ),
    ],
)
def test_schema_rejects_malformed_documents(document: dict) -> None:
    """The schema rejects the same structural mistakes as the parser."""
    validator = Draft202012Validator(load_schema())
    assert list(validator.iter_errors(document))
