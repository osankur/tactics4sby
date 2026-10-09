# Proof Strategy

Proof strategies are described in JSON files. These describe hierarchical proof techniques to be applied when proving the properties of an input Verilog design.

At the top level, a `proof_strategy` object describes the design under verification with the following subfields:

- `header` describing a list of strings that are Yosys commands to be executed (such as reading Verilog files, activating define macros). The commands are executed in a single Yosys session, in order, before any objective is processed. Relative paths are resolved against the directory containing the strategy file.
- `files`, a mandatory list of source files to be considered in the sby configuration scripts. It may be empty.
- `objectives`, a list of `objective` objects describing verification objectives. This list can be empty.
- Optional `early-assume` and `early-assert` Boolean fields (both default to `false`), which determine whether assume and assert cells inside processes must be activated in the initial step or delayed by one step. If `early-assume` is true then `early-assert` must be true as well. These are strategy-wide flags.
- Optional `options` and `engines` lists of strings. They default to `["mode prove"]` and `["smtbmc"]` and provide the SBY defaults.

Each objective is given by the following fields:

- `top` the name of the top module to be loaded. This module must exist after `header` has been executed.
- Optional `name` field, a user-supplied label for the objective (e.g. for logs and error messages). It has no semantic effect. Submodule entries are objectives, so they may be labelled the same way.
- An optional `tactic` field containing a tactic object. If absent, the objective is a leaf: it is proven directly, without decomposition.

The contract of an objective's `top` module is *all* of its assertions and assumptions. There is no way to select a subset: every assert and assume of the module is part of its contract. This always refers to properties of the `top` module, never to those of its submodules. Objectives are proven independently of one another: no assumption or intermediate result is shared between them.

A tactic object contains:
- A mandatory subfield `name`. We have `assume_guarantee` and `split` tactics allowed.

## Tactic: `assume_guarantee`

This tactic object contains an optional `submodules` field holding a non-empty list of `objective`s. A submodule is analysed exactly as a top-level objective, so its entry is an objective in its own right:

- a mandatory `top` field, the name of the submodule (it becomes the top module of the recursive analysis);
- an optional `tactic` field containing a tactic object, to specify recursively how the submodule's contract is proven.

The `early-assume` / `early-assert` flags are strategy-wide and cannot be specified on an objective or tactic.

If `submodules` is absent, then all modules instantiated inside the objective's `top` module are considered as submodules.

The `top`s of the `submodules` entries must be pairwise distinct.

### Instance ordering: `auto`, `instances` and `inline`

The tactic also decides which module instances take part in the assume-guarantee proof and in which order they are considered. This is controlled by three fields:

- `auto`, an optional Boolean (default `true`), selects whether the order of the instances is computed automatically or given by the user.
- `instances`, an optional non-empty list of instance names. Its meaning depends on `auto`:
  - when `auto` is `true` (the default), it may be given; the tactic then only considers these instances, but their ordering is computed automatically.
  - when `auto` is `false`, it is **required** and gives the order in which the instances are considered. Every instance *not* appearing in this list is inlined.
- `inline`, an optional list of instance names to inline. It is **only allowed when `auto` is `true`**; in manual mode, inlining is expressed by leaving an instance out of `instances`.

The names in `instances` (respectively `inline`) must be pairwise distinct.

The role of the submodule objectives and the instances is the following. When applying the assume-guarantee rule, one verification condition is generated for each submodule considered in the hierarchical proof: it consists in proving the contract of the submodule separately. Moreover, a separate verification condition must be proven to establish that the top module guarantees each module instantiation's assumptions (so that the submodule's guarantees can be obtained). The recursive structure of the proof strategy allows the user to specify further tactics to prove each verification condition to be generated.

## Tactic: `split`

The object must contain a `split_wire` field containing a Verilog expression, plus optional `case_false` and `case_true` subfields. Each of these, when present, must be a tactic object. An absent case means that the corresponding branch is proven directly, without further decomposition. (An empty object `{}` is not a tactic and is rejected; use the absence of the field to mean "prove directly".) One can thus for instance nest a secondary split tactic inside, say, `case_true`.

The `split_wire` is evaluated in the module owning the verification condition being split: in the objective's `top` module at the top level, and in the submodule of a submodule objective's tactic.

Each objective is proven independently of the others.

## Examples

- [tests/strategy1.json](tests/strategy1.json) illustrates the recursive structure with automatic instance ordering (its design references are illustrative, not the fixture).
- [tests/strategy2.json](tests/strategy2.json) is a complete assume-guarantee proof against the `tests/module_dep1.sv` fixture, with an explicit instance order.
- [tests/strategy3.json](tests/strategy3.json) shows automatic ordering with an inlined instance and a split nested inside a submodule objective.

## Update
The structure changes as follows.
- Assume-guarantee tactics no longer have a submodules field. Instead, all objectives now appear in the top level. For each instance appearing in an assume-guarantee tactic, there must be a top level objective for its module.
- The `instances` field of assume-guarantee tactic is now a list of objects containing a `name` field, which is the name of the instance cell, and an optional `tactic` field which can contain further tactics. When defined, this determines the tactic to use to prove the verification condition for this particular instance.
- The assume-guarantee tactic itself can also contain an optional `tactic` field which determines the tactic to use for proving the main verification condition for this objective.

- The strategy and each objective can contain optional `options` and `engines` lists. Strategy values default to `["mode prove"]` and `["smtbmc"]`; objective values retain those defaults unless specified.
- Each tactic can also contain `options` and `engines` lists. Tactic values are local and are never inherited; omitted values are empty lists.

- We have two new tactics:
  - `cutpoint` which applies cutpoint to a given wire. The mandatory `wire` field is a Yosys select expression referring to the top module's wires.
  This implements user-defined abstractions.
  An optional `tactic` field can be used to further apply other tactics.
  - `inductive_assume_guarantee` which has a structure identical to assume_guarantee. This rule is interesting for proofs that require apparently circular reasoning. In this case, we attempt to prove the assumptions of each instance at time t, by assuming the assertions of other modules up to time t-1.

The file `tests/nested.json` illustrates an example with these new features.

## Development

### Environment

The tool needs the Yosys Python bindings (`pyosys`), which are normally
installed system-wide.  Create a virtual environment that can see them and
install the test dependencies:

```sh
uv venv --python /usr/bin/python3 --system-site-packages .venv
uv pip install --python .venv/bin/python pytest pytest-cov
```

(`--system-site-packages` is required: `pyosys` lives in the system/user site
packages, not in the venv.)

### Running the tests

From the repository root:

```sh
.venv/bin/python -m pytest
```

Coverage is reported automatically at the end of every run (configured in
`pyproject.toml`).  Useful variants:

```sh
.venv/bin/python -m pytest -q                 # quiet
.venv/bin/python -m pytest --no-cov           # skip coverage
.venv/bin/python -m pytest --cov-report=html  # htmlcov/index.html
.venv/bin/python -m pytest -k cli             # only the end-to-end tests
```

### Pre-commit hooks

The repository ships a [pre-commit](https://pre-commit.com/) configuration
(`.pre-commit-config.yaml`).  Install it once per clone:

```sh
pre-commit install --install-hooks          # commit-stage hooks
pre-commit install --hook-type pre-push     # also install the pre-push hook
```

The hooks are:

| Hook                                                                                         | Stage        | What it does                                   |
| -------------------------------------------------------------------------------------------- | ------------ | ---------------------------------------------- |
| `trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending`                              | commit       | File hygiene.                                  |
| `check-yaml`, `check-toml`, `check-json`                                                     | commit       | Validate config and fixture syntax.            |
| `check-merge-conflict`, `check-case-conflict`, `check-added-large-files`, `debug-statements` | commit       | Common mistakes.                               |
| `ruff-check` (`--fix`)                                                                       | commit       | Lint, using `[tool.ruff]` in `pyproject.toml`. |
| `ruff-format`                                                                                | commit       | Formatting.                                    |
| `ty`                                                                                         | commit       | Type checking (whole project).                 |
| `pytest`                                                                                     | **pre-push** | Runs the test suite.                           |

Run everything manually with:

```sh
pre-commit run --all-files                  # commit-stage hooks
pre-commit run pytest --hook-stage pre-push # the test suite
```

The `pytest` hook is attached to `pre-push` rather than `pre-commit` because the
suite takes about a minute; move it to the commit stage by changing its `stages`
entry if you prefer.  It uses `language: system` and the project venv
(`.venv/bin/python`) because the tests import `pyosys`, which is installed
system-wide and cannot be installed into an isolated pre-commit environment.

### Test layout

- `tests/test_proof_strategy.py` — unit tests for the JSON parser.
- `tests/test_ag4sby.py` — unit tests for the cell/dependency graph.
- `tests/test_cli.py` — end-to-end tests that invoke the command line
  (`python ag4sby.py -f tests/strategy0.json`) in a subprocess and compare the
  generated `.sby` against the golden files in `tests/golden/`.

The end-to-end tests contribute to the same coverage report as the unit tests:
`[tool.coverage.run] patch = ["subprocess"]` makes coverage start in the child
processes, and pytest-cov combines their data files at the end of the run.

### Updating the golden files

When a change to the generator is intentional, regenerate the expected outputs:

```sh
for s in 0 1 2; do .venv/bin/python ag4sby.py -f tests/strategy$s.json; \
  cp tests/strategy$s.sby tests/golden/strategy$s.sby; done
```

Then review the diff in `tests/golden/` before committing it.
