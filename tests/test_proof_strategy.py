"""Tests for the proof strategy parser."""

import json
from pathlib import Path

import pytest

from proof_strategy import (
    AssumeGuaranteeTactic,
    Instance,
    Objective,
    ProofStrategy,
    ProofStrategyError,
    SplitTactic,
    Submodule,
    parse_dict,
    parse_file,
    parse_string,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADER = ["read_verilog -sv module_dep1.sv"]


def strategy(objectives: list[dict]) -> str:
    """A strategy document with the given top-level ``objectives``."""
    return json.dumps({"proof_strategy": {"header": HEADER, "objectives": objectives}})


def ag(**tactic_fields: object) -> dict:
    """An ``assume_guarantee`` tactic object."""
    return {"name": "assume_guarantee", **tactic_fields}


def split(expression: str = "x", **cases: object) -> dict:
    """A ``split`` tactic object."""
    return {"name": "split", "split_expression": expression, **cases}


# --------------------------------------------------------------------------- #
# Objectives
# --------------------------------------------------------------------------- #


def test_leaf_objective():
    result = parse_string(
        strategy([{"top": "main", "assertions": ["a"], "assumptions": ["b"]}])
    )
    assert isinstance(result, ProofStrategy)
    assert result.source is None
    assert result.header == tuple(HEADER)

    (objective,) = result.objectives
    assert objective == Objective(
        top="main", assertions=("a",), assumptions=("b",), tactic=None
    )
    assert not objective.early_assume
    assert not objective.early_assert


def test_defaults_are_none():
    (objective,) = parse_string(strategy([{"top": "main"}])).objectives
    assert objective.assertions is None
    assert objective.assumptions is None
    assert objective.tactic is None


def test_empty_objectives_list_is_allowed():
    result = parse_string(strategy([]))
    assert result == ProofStrategy(header=tuple(HEADER), objectives=())


def test_early_flags_must_be_booleans():
    with pytest.raises(ProofStrategyError, match="expected a boolean"):
        parse_string(strategy([{"top": "t", "early-assert": "yes"}]))


def test_early_assume_requires_early_assert():
    with pytest.raises(ProofStrategyError, match="requires 'early-assert'"):
        parse_string(strategy([{"top": "t", "early-assume": True}]))
    # the converse is fine: early-assert alone is legal
    (objective,) = parse_string(
        strategy([{"top": "t", "early-assert": True}])
    ).objectives
    assert objective.early_assert and not objective.early_assume


def test_empty_allow_list_is_rejected():
    with pytest.raises(ProofStrategyError, match="must not be an empty array"):
        parse_string(strategy([{"top": "t", "assertions": []}]))


def test_unknown_key_is_rejected():
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(strategy([{"top": "t", "assertios": ["a"]}]))


def test_exclude_assertions_no_longer_exists():
    with pytest.raises(
        ProofStrategyError, match="unknown key\\(s\\): 'exclude_assertions'"
    ):
        parse_string(strategy([{"top": "t", "exclude_assertions": ["a"]}]))


def test_missing_top_is_rejected():
    with pytest.raises(ProofStrategyError, match="missing required key"):
        parse_string(strategy([{"assertions": ["a"]}]))


# --------------------------------------------------------------------------- #
# assume_guarantee tactic
# --------------------------------------------------------------------------- #


def test_assume_guarantee_with_submodules_and_instances():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "tactic": ag(
                        submodules=[
                            {
                                "name": "subm",
                                "assertions": ["out_ok"],
                                "assumptions": ["in_valid"],
                            }
                        ],
                        instances=[
                            {"name": "s1", "inline": True},
                            {"name": "s2", "tactic": split("y1 > 2")},
                        ],
                    ),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert(tactic.submodules)
    (sub,) = tactic.submodules
    assert sub == Submodule(
        name="subm", assertions=("out_ok",), assumptions=("in_valid",), tactic=None
    )
    s1, s2 = tactic.instances
    assert s1 == Instance(name="s1", inline=True, tactic=None)
    assert s2.name == "s2"
    assert isinstance(s2.tactic, SplitTactic)
    assert s2.tactic.split_expression == "y1 > 2"
    assert s2.tactic.case_false is None and s2.tactic.case_true is None


def test_assume_guarantee_without_submodules_means_all():
    result = parse_string(strategy([{"top": "main", "tactic": ag()}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.submodules is None
    assert tactic.instances == ()


def test_empty_submodules_is_rejected():
    with pytest.raises(ProofStrategyError, match="omit it for 'all'"):
        parse_string(strategy([{"top": "t", "tactic": ag(submodules=[])}]))


def test_empty_instances_is_allowed():
    result = parse_string(strategy([{"top": "t", "tactic": ag(instances=[])}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == ()


def test_submodule_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate submodule name 'subm'"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": ag(submodules=[{"name": "subm"}, {"name": "subm"}]),
                    }
                ]
            )
        )


def test_instance_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate instance name 's1'"):
        parse_string(
            strategy(
                [{"top": "t", "tactic": ag(instances=[{"name": "s1"}, {"name": "s1"}])}]
            )
        )


def test_inline_forbids_tactic():
    with pytest.raises(ProofStrategyError, match="inlined instance must not carry"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": ag(
                            instances=[
                                {"name": "s1", "inline": True, "tactic": split()}
                            ]
                        ),
                    }
                ]
            )
        )


def test_instance_field_is_name_not_instance():
    with pytest.raises(ProofStrategyError, match="unknown key\\(s\\): 'instance'"):
        parse_string(
            strategy([{"top": "t", "tactic": ag(instances=[{"instance": "s1"}])}])
        )


def test_assume_guarantee_is_recursive_through_submodules():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "tactic": ag(
                        submodules=[
                            {
                                "name": "subm",
                                "tactic": ag(submodules=[{"name": "subsubm"}]),
                            }
                        ]
                    ),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert(tactic.submodules)
    nested = tactic.submodules[0].tactic
    assert isinstance(nested, AssumeGuaranteeTactic)
    assert nested.submodules == (Submodule(name="subsubm"),)


# --------------------------------------------------------------------------- #
# split tactic
# --------------------------------------------------------------------------- #


def test_split_with_nested_cases():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "tactic": split(
                        "x",
                        case_true=split("y < 3", case_false=split("z")),
                    ),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, SplitTactic)
    assert tactic.case_false is None
    inner = tactic.case_true
    assert isinstance(inner, SplitTactic) and inner.split_expression == "y < 3"
    assert isinstance(inner.case_false, SplitTactic)
    assert inner.case_true is None


def test_empty_case_object_is_rejected():
    with pytest.raises(ProofStrategyError, match="an empty object is not a tactic"):
        parse_string(strategy([{"top": "t", "tactic": split("x", case_false={})}]))


def test_split_requires_expression():
    with pytest.raises(
        ProofStrategyError, match="missing required key\\(s\\): 'split_expression'"
    ):
        parse_string(strategy([{"top": "t", "tactic": {"name": "split"}}]))


def test_tactic_rejects_keys_of_the_other_tactic():
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": {
                            "name": "assume_guarantee",
                            "instances": [{"name": "s"}],
                            "split_expression": "x",
                        },
                    }
                ]
            )
        )


def test_unknown_tactic_name_is_rejected():
    with pytest.raises(ProofStrategyError, match="unknown tactic 'nope'"):
        parse_string(strategy([{"top": "t", "tactic": {"name": "nope"}}]))


def test_tactic_missing_name_is_rejected():
    with pytest.raises(ProofStrategyError, match="missing required key: 'name'"):
        parse_string(strategy([{"top": "t", "tactic": {"submodules": []}}]))


# --------------------------------------------------------------------------- #
# Documents and error reporting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "document",
    [
        '{"proof_strategy": {"header": [] "objectives": []}}',
        "",
        "null",
        "[]",
        '{"context": {"header": [], "objectives": []}}',  # old root key
        '{"proof_strategy": {"header": [], "objectives": []}, "extra": 1}',
    ],
)
def test_malformed_documents_raise(document):
    with pytest.raises(ProofStrategyError):
        parse_string(document)


def test_error_messages_carry_the_json_path():
    with pytest.raises(ProofStrategyError) as excinfo:
        parse_string(
            strategy(
                [
                    {"top": "t"},
                    {
                        "top": "t",
                        "tactic": ag(submodules=[{"name": "s"}, {"name": 42}]),
                    },
                ]
            )
        )
    assert "proof_strategy.objectives[1].tactic.submodules[1].name" in str(
        excinfo.value
    )


def test_bad_json_reports_line_and_column():
    with pytest.raises(ProofStrategyError, match="line 1 column 34"):
        parse_string('{"proof_strategy": {"header": [] "objectives": []}}')


# --------------------------------------------------------------------------- #
# File I/O and the shipped examples
# --------------------------------------------------------------------------- #


def test_parse_file_records_the_source(tmp_path: Path):
    path = tmp_path / "strategy.json"
    path.write_text(strategy([{"top": "main"}]), encoding="utf-8")

    result = parse_file(path)
    assert result.source == path
    assert result.objectives[0].top == "main"
    # source is excluded from equality, so two reads compare equal
    assert result == parse_file(path)


def test_parse_file_missing_file_raises(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(
        ProofStrategyError, match="cannot read proof strategy"
    ) as excinfo:
        parse_file(missing)
    assert str(missing) in str(excinfo.value)


def test_parse_dict_accepts_decoded_json():
    text = strategy([{"top": "main"}])
    assert parse_dict(json.loads(text)) == parse_string(text)


@pytest.mark.parametrize(
    "name",
    ["strategy1.json", "strategy2.json", "strategy3.json"],
)
def test_shipped_examples_parse(name: str):
    strategy_path = REPO_ROOT / "tests" / name
    result = parse_file(strategy_path)
    assert result.source == strategy_path
    assert result.header, "examples must have a non-empty header"
    assert all(isinstance(o, Objective) for o in result.objectives)
