"""Tests for the proof strategy parser."""

import json
from pathlib import Path

import pytest

from proof_strategy import (
    AssumeGuaranteeTactic,
    Objective,
    ProofStrategy,
    ProofStrategyError,
    SplitTactic,
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
    """An ``assume_guarantee`` tactic object.

    ``auto`` defaults to true, so a tactic needs no instance list; pass
    ``auto=False, instances=[...]`` for manual ordering.
    """
    return {"name": "assume_guarantee", **tactic_fields}


def split(expression: str = "x", **cases: object) -> dict:
    """A ``split`` tactic object."""
    return {"name": "split", "split_expression": expression, **cases}


# --------------------------------------------------------------------------- #
# Objectives
# --------------------------------------------------------------------------- #


def test_leaf_objective():
    result = parse_string(strategy([{"top": "main"}]))
    assert isinstance(result, ProofStrategy)
    assert result.source is None
    assert result.header == tuple(HEADER)

    (objective,) = result.objectives
    assert objective == Objective(top="main", tactic=None)
    assert not objective.early_assume
    assert not objective.early_assert


def test_defaults_are_none():
    (objective,) = parse_string(strategy([{"top": "main"}])).objectives
    assert objective.tactic is None
    assert objective.name is None


def test_empty_objectives_list_is_allowed():
    result = parse_string(strategy([]))
    assert result == ProofStrategy(header=tuple(HEADER), objectives=())


def test_assertions_and_assumptions_are_gone():
    """The contract is all of a module's asserts/assumes; no selection exists."""
    for key in ("assertions", "assumptions"):
        with pytest.raises(ProofStrategyError, match=f"unknown key\\(s\\): '{key}'"):
            parse_string(strategy([{"top": "t", key: ["a"]}]))


def test_assertions_rejected_on_submodule_objective():
    with pytest.raises(ProofStrategyError, match="unknown key\\(s\\): 'assertions'"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": ag(submodules=[{"top": "s", "assertions": ["a"]}]),
                    }
                ]
            )
        )


# --------------------------------------------------------------------------- #
# Objective label (name)
# --------------------------------------------------------------------------- #


def test_objective_optional_name():
    result = parse_string(strategy([{"top": "main", "name": "sanity"}]))
    (objective,) = result.objectives
    assert objective.name == "sanity"
    assert objective.top == "main"


def test_submodule_objective_can_be_named():
    result = parse_string(
        strategy(
            [{"top": "main", "tactic": ag(submodules=[{"top": "subm", "name": "c1"}])}]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.submodules
    (sub,) = tactic.submodules.values()
    assert sub.name == "c1"
    assert sub.top == "subm"


def test_objective_name_must_be_a_string():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"top": "main", "name": 42}]))


# --------------------------------------------------------------------------- #
# JSON path recorded on every node
# --------------------------------------------------------------------------- #


def test_json_path_on_objectives():
    result = parse_string(
        strategy([{"top": "a"}, {"top": "b", "tactic": ag(submodules=[{"top": "s"}])}])
    )
    (first, second) = result.objectives
    assert first.json_path == "proof_strategy.objectives[0]"
    assert second.json_path == "proof_strategy.objectives[1]"
    assert second.tactic is not None
    assert second.tactic.json_path == "proof_strategy.objectives[1].tactic"
    assert isinstance(second.tactic, AssumeGuaranteeTactic)
    assert second.tactic.submodules
    assert (
        second.tactic.submodules["s"].json_path
        == "proof_strategy.objectives[1].tactic.submodules[0]"
    )


def test_json_path_on_nested_tactics():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "tactic": ag(
                        submodules=[
                            {"top": "subm", "tactic": split("x", case_true=split("y"))}
                        ]
                    ),
                }
            ]
        )
    )
    (objective,) = result.objectives
    assert objective.json_path == "proof_strategy.objectives[0]"
    ag_tactic = objective.tactic
    assert isinstance(ag_tactic, AssumeGuaranteeTactic)
    assert ag_tactic.submodules
    sub = ag_tactic.submodules["subm"]
    assert sub.json_path == "proof_strategy.objectives[0].tactic.submodules[0]"
    outer = sub.tactic
    assert isinstance(outer, SplitTactic)
    assert outer.json_path == (
        "proof_strategy.objectives[0].tactic.submodules[0].tactic"
    )
    inner = outer.case_true
    assert isinstance(inner, SplitTactic)
    assert inner.json_path == (
        "proof_strategy.objectives[0].tactic.submodules[0].tactic.case_true"
    )


def test_json_path_excluded_from_equality():
    # two objectives that differ only in provenance compare equal
    a = Objective(top="main", json_path="proof_strategy.objectives[0]")
    b = Objective(top="main", json_path="somewhere.else")
    assert a == b
    # but any real field difference still distinguishes them
    assert a != Objective(top="other", json_path="proof_strategy.objectives[0]")


def test_parsed_strategy_json_path_is_document_root():
    result = parse_string(strategy([{"top": "main"}]))
    assert result.json_path == "proof_strategy"


# --------------------------------------------------------------------------- #
# early flags
# --------------------------------------------------------------------------- #


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


def test_unknown_key_is_rejected():
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(strategy([{"top": "t", "assertios": ["a"]}]))


def test_missing_top_is_rejected():
    with pytest.raises(ProofStrategyError, match="missing required key"):
        parse_string(strategy([{"name": "x"}]))


# --------------------------------------------------------------------------- #
# assume_guarantee: submodules
# --------------------------------------------------------------------------- #


def test_assume_guarantee_with_submodules():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "tactic": ag(submodules=[{"top": "subm"}]),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.submodules
    assert list(tactic.submodules) == ["subm"]
    (sub,) = tactic.submodules.values()
    assert sub == Objective(top="subm", tactic=None)


def test_assume_guarantee_without_submodules_means_all():
    result = parse_string(strategy([{"top": "main", "tactic": ag()}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.submodules is None


def test_empty_submodules_is_rejected():
    with pytest.raises(ProofStrategyError, match="omit it for 'all'"):
        parse_string(strategy([{"top": "t", "tactic": ag(submodules=[])}]))


def test_submodule_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate submodule name 'subm'"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": ag(submodules=[{"top": "subm"}, {"top": "subm"}]),
                    }
                ]
            )
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
                                "top": "subm",
                                "tactic": ag(submodules=[{"top": "subsubm"}]),
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
    assert tactic.submodules
    nested = tactic.submodules["subm"].tactic
    assert isinstance(nested, AssumeGuaranteeTactic)
    assert nested.submodules == {"subsubm": Objective(top="subsubm")}


# --------------------------------------------------------------------------- #
# assume_guarantee: auto / instances / inline
# --------------------------------------------------------------------------- #


def test_auto_defaults_to_true():
    """A bare assume_guarantee means automatic ordering, all instances."""
    result = parse_string(strategy([{"top": "t", "tactic": ag()}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is True
    assert tactic.instances is None
    assert tactic.inline == ()


def test_manual_mode_is_opt_in():
    result = parse_string(
        strategy([{"top": "t", "tactic": ag(auto=False, instances=["s1"])}])
    )
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is False
    assert tactic.instances == ("s1",)
    assert tactic.inline == ()


def test_auto_must_be_a_boolean():
    with pytest.raises(ProofStrategyError, match="expected a boolean"):
        parse_string(strategy([{"top": "t", "tactic": ag(auto="yes")}]))


def test_manual_mode_requires_instances():
    with pytest.raises(ProofStrategyError, match="'instances' is required"):
        parse_string(strategy([{"top": "t", "tactic": ag(auto=False)}]))


def test_manual_mode_keeps_the_given_order():
    result = parse_string(
        strategy([{"top": "t", "tactic": ag(auto=False, instances=["s2", "s1"])}])
    )
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == ("s2", "s1")


def test_auto_mode_allows_omitting_instances():
    result = parse_string(strategy([{"top": "t", "tactic": ag(auto=True)}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is True
    assert tactic.instances is None
    assert tactic.inline == ()


def test_auto_mode_instances_restrict_the_set():
    result = parse_string(
        strategy([{"top": "t", "tactic": ag(auto=True, instances=["s2", "s3"])}])
    )
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == ("s2", "s3")


def test_auto_mode_inline_list():
    result = parse_string(
        strategy([{"top": "t", "tactic": ag(auto=True, inline=["s1"])}])
    )
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.inline == ("s1",)


def test_inline_is_rejected_in_manual_mode():
    with pytest.raises(ProofStrategyError, match="'inline' is only allowed"):
        parse_string(
            strategy(
                [
                    {
                        "top": "t",
                        "tactic": ag(auto=False, instances=["s1"], inline=["s2"]),
                    }
                ]
            )
        )


def test_empty_instances_is_rejected():
    with pytest.raises(ProofStrategyError, match="must not be an empty array"):
        parse_string(strategy([{"top": "t", "tactic": ag(auto=True, instances=[])}]))


def test_empty_inline_is_allowed():
    result = parse_string(strategy([{"top": "t", "tactic": ag(auto=True, inline=[])}]))
    (tactic,) = [o.tactic for o in result.objectives]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.inline == ()


def test_instance_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate instance name 's1'"):
        parse_string(
            strategy([{"top": "t", "tactic": ag(auto=True, instances=["s1", "s1"])}])
        )


def test_inline_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate inline instance name 's1'"):
        parse_string(
            strategy([{"top": "t", "tactic": ag(auto=True, inline=["s1", "s1"])}])
        )


def test_instances_must_be_strings():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"top": "t", "tactic": ag(auto=True, instances=[1])}]))


# --------------------------------------------------------------------------- #
# early-flag inheritance
# --------------------------------------------------------------------------- #


def test_submodule_objective_inherits_early_flags():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "early-assert": True,
                    "early-assume": True,
                    "tactic": ag(submodules=[{"top": "subm"}]),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.submodules
    (sub,) = tactic.submodules.values()
    assert sub.early_assume and sub.early_assert


def test_early_flags_inherit_through_deeply_nested_objectives():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "early-assert": True,
                    "tactic": ag(
                        submodules=[
                            {
                                "top": "subm",
                                "tactic": ag(submodules=[{"top": "subsubm"}]),
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
    assert tactic.submodules
    sub = tactic.submodules["subm"]
    assert sub.early_assert and not sub.early_assume
    assert isinstance(sub.tactic, AssumeGuaranteeTactic)
    assert sub.tactic.submodules
    (leaf,) = sub.tactic.submodules.values()
    assert leaf.early_assert and not leaf.early_assume


def test_early_flags_inherit_through_split_cases():
    result = parse_string(
        strategy(
            [
                {
                    "top": "main",
                    "early-assert": True,
                    "tactic": split("x", case_true=ag(submodules=[{"top": "subm"}])),
                }
            ]
        )
    )
    (objective,) = result.objectives
    tactic = objective.tactic
    assert isinstance(tactic, SplitTactic)
    assert isinstance(tactic.case_true, AssumeGuaranteeTactic)
    assert tactic.case_true.submodules
    (sub,) = tactic.case_true.submodules.values()
    assert sub.early_assert and not sub.early_assume


def test_early_flags_forbidden_on_submodule_objective():
    with pytest.raises(
        ProofStrategyError, match="only be set on a top-level objective"
    ):
        parse_string(
            strategy(
                [
                    {
                        "top": "main",
                        "tactic": ag(
                            submodules=[{"top": "subm", "early-assert": True}]
                        ),
                    }
                ]
            )
        )


def test_early_flags_forbidden_under_split_case():
    with pytest.raises(
        ProofStrategyError, match="only be set on a top-level objective"
    ):
        parse_string(
            strategy(
                [
                    {
                        "top": "main",
                        "tactic": split(
                            "x",
                            case_true=ag(
                                submodules=[{"top": "subm", "early-assume": True}]
                            ),
                        ),
                    }
                ]
            )
        )


def test_submodule_entry_rejects_early_assume_alone():
    # the early-assume => early-assert rule is not re-checkable on a nested
    # objective (it is rejected outright), so the error mentions inheritance
    with pytest.raises(ProofStrategyError) as excinfo:
        parse_string(
            strategy(
                [
                    {
                        "top": "main",
                        "tactic": ag(submodules=[{"top": "s", "early-assume": True}]),
                    }
                ]
            )
        )
    assert "early-assume" in str(excinfo.value)


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
                            "auto": True,
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
                        "tactic": ag(submodules=[{"top": "s"}, {"top": 42}]),
                    },
                ]
            )
        )
    assert "proof_strategy.objectives[1].tactic.submodules[1].top" in str(excinfo.value)


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
