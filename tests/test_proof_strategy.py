"""Tests for the proof strategy parser."""

import json
from pathlib import Path

import pytest

from parser import (
    AssumeGuaranteeTactic,
    CutpointTactic,
    InductiveAssumeGuaranteeTactic,
    Instance,
    Goal,
    ProofStrategy,
    ProofStrategyError,
    SplitTactic,
    parse_dict,
    parse_file,
    parse_string,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADER = ["read_verilog -sv module_dep1.sv"]
FILES = ["module_dep1.sv"]


def strategy(goals: list[dict], proof_strategy_fields: dict | None = None) -> str:
    """A strategy document with the given goals and strategy fields."""
    fields = proof_strategy_fields or {}
    return json.dumps(
        {
            "proof_strategy": {
                "header": HEADER,
                "files": FILES,
                "goals": goals,
                **fields,
            }
        }
    )


def ag(**tactic_fields: object) -> dict:
    """An ``assume_guarantee`` tactic object.

    ``auto`` defaults to true, so a tactic needs no instance list; pass
    ``auto=False, instances=[...]`` for manual ordering.
    """
    return {"name": "assume_guarantee", **tactic_fields}


def iag(**tactic_fields: object) -> dict:
    """An ``inductive_assume_guarantee`` tactic object."""
    return {"name": "inductive_assume_guarantee", **tactic_fields}


def inst(name: object, **fields: object) -> dict:
    """An entry of the ``instances`` list."""
    return {"name": name, **fields}


def cutpoint(selection: object = "w", **fields: object) -> dict:
    """A ``cutpoint`` tactic object."""
    return {"name": "cutpoint", "selection": selection, **fields}


def split(expression: str = "x", **cases: object) -> dict:
    """A ``split`` tactic object."""
    return {"name": "split", "split_wire": expression, **cases}


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #


def test_leaf_goal():
    result = parse_string(strategy([{"module": "main"}]))
    assert isinstance(result, ProofStrategy)
    assert result.source is None
    assert result.header == tuple(HEADER)
    assert result.files == tuple(FILES)

    (goal,) = result.goals
    assert goal == Goal(module="main", tactic=None)
    assert not result.early_assume
    assert not result.early_assert


def test_defaults_are_none():
    (goal,) = parse_string(strategy([{"module": "main"}])).goals
    assert goal.tactic is None
    assert goal.name is None


def test_empty_goals_list_is_allowed():
    result = parse_string(strategy([]))
    assert result == ProofStrategy(header=tuple(HEADER), files=tuple(FILES), goals=())


def test_assertions_and_assumptions_are_gone():
    """The contract is all of a module's asserts/assumes; no selection exists."""
    for key in ("assertions", "assumptions"):
        with pytest.raises(ProofStrategyError, match=f"unknown key\\(s\\): '{key}'"):
            parse_string(strategy([{"module": "t", key: ["a"]}]))


def test_assertions_rejected_on_instance_entry():
    with pytest.raises(ProofStrategyError, match="unknown key\\(s\\): 'assertions'"):
        parse_string(
            strategy(
                [
                    {
                        "module": "t",
                        "tactic": ag(instances=[inst("s", assertions=["a"])]),
                    }
                ]
            )
        )


# --------------------------------------------------------------------------- #
# Goal label (name)
# --------------------------------------------------------------------------- #


def test_goal_optional_name():
    result = parse_string(strategy([{"module": "main", "name": "sanity"}]))
    (goal,) = result.goals
    assert goal.name == "sanity"
    assert goal.module == "main"


def test_goal_name_must_be_a_string():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"module": "main", "name": 42}]))


# --------------------------------------------------------------------------- #
# JSON path recorded on every node
# --------------------------------------------------------------------------- #


def test_json_path_on_goals():
    result = parse_string(
        strategy(
            [{"module": "a"}, {"module": "b", "tactic": ag(instances=[inst("s")])}]
        )
    )
    (first, second) = result.goals
    assert first.json_path == "proof_strategy.goals[0]"
    assert second.json_path == "proof_strategy.goals[1]"
    assert second.tactic is not None
    assert second.tactic.json_path == "proof_strategy.goals[1].tactic"
    assert isinstance(second.tactic, AssumeGuaranteeTactic)
    assert second.tactic.instances
    assert (
        second.tactic.instances[0].json_path
        == "proof_strategy.goals[1].tactic.instances[0]"
    )


def test_json_path_on_nested_tactics():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(
                        instances=[inst("s1", tactic=split("x", case_true=split("y")))]
                    ),
                }
            ]
        )
    )
    (goal,) = result.goals
    assert goal.json_path == "proof_strategy.goals[0]"
    ag_tactic = goal.tactic
    assert isinstance(ag_tactic, AssumeGuaranteeTactic)
    assert ag_tactic.instances
    (instance,) = ag_tactic.instances
    assert instance.json_path == "proof_strategy.goals[0].tactic.instances[0]"
    outer = instance.tactic
    assert isinstance(outer, SplitTactic)
    assert outer.json_path == ("proof_strategy.goals[0].tactic.instances[0].tactic")
    inner = outer.case_true
    assert isinstance(inner, SplitTactic)
    assert inner.json_path == (
        "proof_strategy.goals[0].tactic.instances[0].tactic.case_true"
    )


def test_json_path_excluded_from_equality():
    # two goals that differ only in provenance compare equal
    a = Goal(module="main", json_path="proof_strategy.goals[0]")
    b = Goal(module="main", json_path="somewhere.else")
    assert a == b
    # but any real field difference still distinguishes them
    assert a != Goal(module="other", json_path="proof_strategy.goals[0]")


def test_parsed_strategy_json_path_is_document_root():
    result = parse_string(strategy([{"module": "main"}]))
    assert result.json_path == "proof_strategy"


# --------------------------------------------------------------------------- #
# early flags
# --------------------------------------------------------------------------- #


def test_early_flags_must_be_booleans():
    with pytest.raises(ProofStrategyError, match="expected a boolean"):
        parse_string(strategy([], {"early-assert": "yes"}))


def test_early_assume_requires_early_assert():
    with pytest.raises(ProofStrategyError, match="requires 'early-assert'"):
        parse_string(strategy([], {"early-assume": True}))
    # the converse is fine: early-assert alone is legal
    result = parse_string(strategy([], {"early-assert": True}))
    assert result.early_assert and not result.early_assume


def test_early_flags_are_strategy_wide_and_rejected_on_goals():
    result = parse_string(strategy([{"module": "t"}], {"early-assert": True}))
    assert result.early_assert
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(strategy([{"module": "t", "early-assert": True}]))


def test_unknown_key_is_rejected():
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(strategy([{"module": "t", "assertios": ["a"]}]))


def test_missing_top_is_rejected():
    with pytest.raises(ProofStrategyError, match="missing required key"):
        parse_string(strategy([{"name": "x"}]))


# --------------------------------------------------------------------------- #
# assume_guarantee: instances
# --------------------------------------------------------------------------- #


def test_assume_guarantee_with_instances():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(instances=[inst("s1"), inst("s2")]),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == (Instance(name="s1"), Instance(name="s2"))


def test_instance_can_carry_a_tactic():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(instances=[inst("s1", tactic=cutpoint("w"))]),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances
    (instance,) = tactic.instances
    assert instance.name == "s1"
    assert instance.tactic == CutpointTactic(selection="w")


def test_instance_requires_a_name():
    with pytest.raises(ProofStrategyError, match="missing required key\\(s\\): 'name'"):
        parse_string(strategy([{"module": "t", "tactic": ag(instances=[{}])}]))


def test_instance_name_must_be_a_string():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"module": "t", "tactic": ag(instances=[inst(1)])}]))


def test_empty_instances_is_rejected():
    with pytest.raises(ProofStrategyError, match="must not be an empty array"):
        parse_string(strategy([{"module": "t", "tactic": ag(instances=[])}]))


def test_instance_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate instance name 's1'"):
        parse_string(
            strategy(
                [{"module": "t", "tactic": ag(instances=[inst("s1"), inst("s1")])}]
            )
        )


def test_assume_guarantee_main_vc_tactic():
    result = parse_string(
        strategy([{"module": "t", "tactic": ag(tactic=cutpoint("w"))}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.tactic == CutpointTactic(selection="w")


def test_assume_guarantee_is_recursive_through_instance_tactics():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(
                        instances=[inst("s1", tactic=ag(instances=[inst("s2")]))]
                    ),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances
    nested = tactic.instances[0].tactic
    assert isinstance(nested, AssumeGuaranteeTactic)
    assert nested.instances == (Instance(name="s2"),)


# --------------------------------------------------------------------------- #
# assume_guarantee: auto / instances / inline
# --------------------------------------------------------------------------- #


def test_auto_defaults_to_true():
    """A bare assume_guarantee means automatic ordering, all instances."""
    result = parse_string(strategy([{"module": "t", "tactic": ag()}]))
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is True
    assert tactic.instances is None
    assert tactic.inline == ()


def test_manual_mode_is_opt_in():
    result = parse_string(
        strategy([{"module": "t", "tactic": ag(auto=False, instances=[inst("s1")])}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is False
    assert tactic.instances == (Instance(name="s1"),)
    assert tactic.inline == ()


def test_auto_must_be_a_boolean():
    with pytest.raises(ProofStrategyError, match="expected a boolean"):
        parse_string(strategy([{"module": "t", "tactic": ag(auto="yes")}]))


def test_manual_mode_requires_instances():
    with pytest.raises(ProofStrategyError, match="'instances' is required"):
        parse_string(strategy([{"module": "t", "tactic": ag(auto=False)}]))


def test_manual_mode_keeps_the_given_order():
    result = parse_string(
        strategy(
            [
                {
                    "module": "t",
                    "tactic": ag(auto=False, instances=[inst("s2"), inst("s1")]),
                }
            ]
        )
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == (Instance(name="s2"), Instance(name="s1"))


def test_auto_mode_allows_omitting_instances():
    result = parse_string(strategy([{"module": "t", "tactic": ag(auto=True)}]))
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.auto is True
    assert tactic.instances is None
    assert tactic.inline == ()


def test_auto_mode_instances_restrict_the_set():
    result = parse_string(
        strategy(
            [
                {
                    "module": "t",
                    "tactic": ag(auto=True, instances=[inst("s2"), inst("s3")]),
                }
            ]
        )
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == (Instance(name="s2"), Instance(name="s3"))


def test_auto_mode_inline_list():
    result = parse_string(
        strategy([{"module": "t", "tactic": ag(auto=True, inline=["s1"])}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.inline == ("s1",)


def test_inline_is_rejected_in_manual_mode():
    with pytest.raises(ProofStrategyError, match="'inline' is only allowed"):
        parse_string(
            strategy(
                [
                    {
                        "module": "t",
                        "tactic": ag(auto=False, instances=[inst("s1")], inline=["s2"]),
                    }
                ]
            )
        )


def test_empty_inline_is_allowed():
    result = parse_string(
        strategy([{"module": "t", "tactic": ag(auto=True, inline=[])}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.inline == ()


def test_inline_names_must_be_distinct():
    with pytest.raises(ProofStrategyError, match="duplicate inline instance name 's1'"):
        parse_string(
            strategy([{"module": "t", "tactic": ag(auto=True, inline=["s1", "s1"])}])
        )


def test_inline_names_must_be_strings():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"module": "t", "tactic": ag(auto=True, inline=[1])}]))


# --------------------------------------------------------------------------- #
# strategy-wide early flags
# --------------------------------------------------------------------------- #


def test_instance_tactics_do_not_store_strategy_early_flags():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(
                        instances=[inst("s1", tactic=ag(instances=[inst("s2")]))]
                    ),
                }
            ],
            {"early-assert": True, "early-assume": True},
        )
    )
    assert result.early_assume and result.early_assert
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances
    nested = tactic.instances[0].tactic
    assert isinstance(nested, AssumeGuaranteeTactic)
    assert nested.instances == (Instance(name="s2"),)


def test_early_flags_are_not_tactic_fields():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": ag(
                        instances=[inst("s1", tactic=ag(instances=[inst("s2")]))]
                    ),
                }
            ],
            {"early-assert": True},
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances
    nested = tactic.instances[0].tactic
    assert isinstance(nested, AssumeGuaranteeTactic)
    assert nested.instances == (Instance(name="s2"),)


def test_strategy_early_flags_apply_independently_of_split_cases():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": split("x", case_true=ag(instances=[inst("s1")])),
                }
            ],
            {"early-assert": True},
        )
    )
    assert result.early_assert and not result.early_assume
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, SplitTactic)
    assert isinstance(tactic.case_true, AssumeGuaranteeTactic)
    assert tactic.case_true.instances == (Instance(name="s1"),)


def test_early_flags_are_rejected_on_tactics():
    # Early flags are strategy-level only; tactics reject them.
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(
            strategy(
                [
                    {
                        "module": "main",
                        "tactic": ag(early_assert=True),
                    }
                ]
            )
        )


# --------------------------------------------------------------------------- #
# split tactic
# --------------------------------------------------------------------------- #


def test_split_with_nested_cases():
    result = parse_string(
        strategy(
            [
                {
                    "module": "main",
                    "tactic": split(
                        "x",
                        case_true=split("y < 3", case_false=split("z")),
                    ),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, SplitTactic)
    assert tactic.case_false is None
    inner = tactic.case_true
    assert isinstance(inner, SplitTactic) and inner.split_wire == "y < 3"
    assert isinstance(inner.case_false, SplitTactic)
    assert inner.case_true is None


def test_split_tactic_defaults_to_none():
    result = parse_string(strategy([{"module": "t", "tactic": split("x")}]))
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, SplitTactic)


def test_empty_case_object_is_rejected():
    with pytest.raises(ProofStrategyError, match="an empty object is not a tactic"):
        parse_string(strategy([{"module": "t", "tactic": split("x", case_false={})}]))


def test_split_requires_expression():
    with pytest.raises(
        ProofStrategyError, match="missing required key\\(s\\): 'split_wire'"
    ):
        parse_string(strategy([{"module": "t", "tactic": {"name": "split"}}]))


def test_tactic_rejects_keys_of_the_other_tactic():
    with pytest.raises(ProofStrategyError, match="unknown key"):
        parse_string(
            strategy(
                [
                    {
                        "module": "t",
                        "tactic": {
                            "name": "assume_guarantee",
                            "auto": True,
                            "split_wire": "x",
                        },
                    }
                ]
            )
        )


def test_unknown_tactic_name_is_rejected():
    with pytest.raises(ProofStrategyError, match="unknown tactic 'nope'"):
        parse_string(strategy([{"module": "t", "tactic": {"name": "nope"}}]))


def test_tactic_missing_name_is_rejected():
    with pytest.raises(ProofStrategyError, match="missing required key: 'name'"):
        parse_string(strategy([{"module": "t", "tactic": {"submodules": []}}]))


# --------------------------------------------------------------------------- #
# cutpoint tactic
# --------------------------------------------------------------------------- #


def test_cutpoint_requires_selection():
    with pytest.raises(
        ProofStrategyError, match="missing required key\\(s\\): 'selection'"
    ):
        parse_string(strategy([{"module": "t", "tactic": {"name": "cutpoint"}}]))


def test_cutpoint_selection_must_be_a_string():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"module": "t", "tactic": cutpoint(selection=1)}]))


def test_cutpoint_with_nested_tactic():
    result = parse_string(
        strategy([{"module": "t", "tactic": cutpoint("w", tactic=split("x"))}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, CutpointTactic)
    assert tactic.selection == "w"
    assert isinstance(tactic.tactic, SplitTactic)


def test_cutpoint_without_nested_tactic():
    result = parse_string(strategy([{"module": "t", "tactic": cutpoint("w")}]))
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, CutpointTactic)
    assert tactic.tactic is None


# --------------------------------------------------------------------------- #
# inductive_assume_guarantee tactic
# --------------------------------------------------------------------------- #


def test_inductive_assume_guarantee_is_parsed():
    result = parse_string(
        strategy([{"module": "t", "tactic": iag(instances=[inst("s1")])}])
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, InductiveAssumeGuaranteeTactic)
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.instances == (Instance(name="s1"),)


def test_inductive_assume_guarantee_has_the_same_fields():
    result = parse_string(
        strategy(
            [
                {
                    "module": "t",
                    "tactic": iag(
                        auto=False,
                        instances=[inst("s1")],
                        tactic=cutpoint("w"),
                    ),
                }
            ]
        )
    )
    (tactic,) = [o.tactic for o in result.goals]
    assert isinstance(tactic, InductiveAssumeGuaranteeTactic)
    assert tactic.auto is False
    assert tactic.tactic == CutpointTactic(selection="w")


# --------------------------------------------------------------------------- #
# options / engines defaults and scope
# --------------------------------------------------------------------------- #
def test_options_and_engines_on_proof_strategy():
    result = parse_string(
        strategy(
            [],
            {"options": ["mode bmc"], "engines": ["abc"]},
        )
    )
    assert result.options == ("mode bmc",)
    assert result.engines == ("abc",)


def test_options_and_engines_on_goal():
    (goal,) = parse_string(
        strategy([{"module": "t", "options": ["mode bmc"], "engines": ["abc"]}])
    ).goals
    assert goal.options == ("mode bmc",)
    assert goal.engines == ("abc",)


def test_options_and_engines_are_not_inherited_by_tactic():
    result = parse_string(
        strategy(
            [
                {
                    "module": "t",
                    "options": ["mode bmc"],
                    "engines": ["abc"],
                    "tactic": ag(instances=[inst("s1", tactic=cutpoint("w"))]),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.options == ()
    assert tactic.engines == ()
    assert tactic.instances
    nested = tactic.instances[0].tactic
    assert isinstance(nested, CutpointTactic)
    assert nested.options == ()
    assert nested.engines == ()


def test_tactic_options_override_goal():
    result = parse_string(
        strategy(
            [
                {
                    "module": "t",
                    "options": ["mode bmc"],
                    "tactic": ag(options=["mode prove"], engines=["smtbmc"]),
                }
            ]
        )
    )
    (goal,) = result.goals
    tactic = goal.tactic
    assert isinstance(tactic, AssumeGuaranteeTactic)
    assert tactic.options == ("mode prove",)
    assert tactic.engines == ("smtbmc",)
    # the goal keeps its own values
    assert goal.options == ("mode bmc",)


def test_options_must_be_an_array_of_strings():
    with pytest.raises(ProofStrategyError, match="expected an array of strings"):
        parse_string(strategy([{"module": "t", "options": "mode bmc"}]))


def test_engines_must_be_an_array_of_strings():
    with pytest.raises(ProofStrategyError, match="expected a string"):
        parse_string(strategy([{"module": "t", "engines": [1]}]))


# --------------------------------------------------------------------------- #
# The mandatory `files` field
# --------------------------------------------------------------------------- #


def test_files_is_required():
    document = json.dumps({"proof_strategy": {"header": HEADER, "goals": []}})
    with pytest.raises(
        ProofStrategyError, match="missing required key\\(s\\): 'files'"
    ):
        parse_string(document)


def test_files_must_be_an_array_of_strings():
    document = json.dumps(
        {"proof_strategy": {"header": HEADER, "files": "a.sv", "goals": []}}
    )
    with pytest.raises(ProofStrategyError, match="expected an array of strings"):
        parse_string(document)


def test_files_entries_must_be_strings():
    document = json.dumps(
        {"proof_strategy": {"header": HEADER, "files": [1], "goals": []}}
    )
    with pytest.raises(ProofStrategyError, match="proof_strategy.files\\[0\\]"):
        parse_string(document)


def test_files_may_be_empty():
    document = json.dumps(
        {"proof_strategy": {"header": HEADER, "files": [], "goals": []}}
    )
    assert parse_string(document).files == ()


def test_files_is_parsed_in_order():
    document = json.dumps(
        {
            "proof_strategy": {
                "header": HEADER,
                "files": ["b.sv", "a.sv"],
                "goals": [],
            }
        }
    )
    assert parse_string(document).files == ("b.sv", "a.sv")


# --------------------------------------------------------------------------- #
# Documents and error reporting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "document",
    [
        '{"proof_strategy": {"header": [] "files": [], "goals": []}}',
        "",
        "null",
        "[]",
        '{"context": {"header": [], "files": [], "goals": []}}',  # old root key
        '{"proof_strategy": {"header": [], "files": [], "goals": []}, "extra": 1}',
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
                    {"module": "t"},
                    {
                        "module": "t",
                        "tactic": ag(instances=[inst("s"), inst(42)]),
                    },
                ]
            )
        )
    assert "proof_strategy.goals[1].tactic.instances[1].name" in str(excinfo.value)


def test_bad_json_reports_line_and_column():
    with pytest.raises(ProofStrategyError, match="line 1 column 34"):
        parse_string('{"proof_strategy": {"header": [] "files": [], "goals": []}}')


# --------------------------------------------------------------------------- #
# File I/O and the shipped examples
# --------------------------------------------------------------------------- #


def test_parse_file_records_the_source(tmp_path: Path):
    path = tmp_path / "strategy.json"
    path.write_text(strategy([{"module": "main"}]), encoding="utf-8")

    result = parse_file(path)
    assert result.source == path
    assert result.goals[0].module == "main"
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
    text = strategy([{"module": "main"}])
    assert parse_dict(json.loads(text)) == parse_string(text)


@pytest.mark.parametrize(
    "name",
    ["strategy1.json", "strategy2.json", "strategy3.json", "nested.json"],
)
def test_shipped_examples_parse(name: str):
    strategy_path = REPO_ROOT / "tests" / name
    result = parse_file(strategy_path)
    assert result.source == strategy_path
    assert result.header, "examples must have a non-empty header"
    assert all(isinstance(o, Goal) for o in result.goals)
