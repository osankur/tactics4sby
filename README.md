# Proof Strategy

Proof strategies are described in JSON files.
These describe hierarchical proof techniques to be applied when proving the properties of an input Verilog design.

At the top level, a `proof_strategy` object describes the design under verification with the following subfields:

- `header` describing a list of strings that are Yosys commands to be executed (such as reading Verilog files, activating define macros). The commands are executed in a single Yosys session, in order, before any goal is processed. Relative paths are resolved against the directory containing the strategy file.
- `files`, a mandatory list of source files to be considered in the sby configuration scripts. It may be empty.
- `top`, a mandatory string naming the top module to be considered when synthesizing the design for any of the goals.
- `goal`, a mandatory `goal` object describing the main goal to be proved.
- `subgoals`, a mandatory list of `goal` objects describing additional goals that are required to prove the main goal. This list can be empty.
- Optional `early-assume` and `early-assert` Boolean fields (both default to `false`), which determine whether assume and assert cells inside processes must be activated in the initial step or delayed by one step. If `early-assume` is true then `early-assert` must be true as well. These are strategy-wide flags.
- Optional `options` and `engines` lists of strings. They default to `["mode prove"]` and `["smtbmc"]`.

Each goal is given by the following fields:

- `module` the name of the module to be analyzed. This module must exist after `header` has been executed.
- An optional `tactic` field containing a tactic object. If absent, the goal is a leaf: it is proven directly, without decomposition.

The contract of a goal's `module` module is *all* of its assertions and assumptions. There is no way to select a subset but macros can be used when loading a file to select a subset.
This always refers to properties of the `module`, never to those of its submodules. Goals are proven independently of one another: no assumption or intermediate result is shared between them.

A tactic object contains:
- A mandatory subfield `name`. We have the followings tactics allowed: `assume_guarantee`, `cutpoint`, `split`.
- Optional `options` and `engines` lists. These values, when given, override parents' options and engines values.

## Tactic: `assume_guarantee`

The tactic decides which module instances take part in the assume-guarantee proof and in which order they are considered. This is controlled by three fields:

- `auto`, an optional Boolean (default `true`), selects whether the order of the instances is computed automatically or given by the user.
- `instances`, an optional non-empty list of objects containing the `name` of an instance or a module name. When defined, all instances whose names are given, and all instances of whose module name is given participate in the assume-guarantee decomposition. The order in which the assume-guarantee rule is applied depends on `auto`:
  - when `auto` is `true` (the default), the ordering is computed automatically (by attempting to compute a topological ordering);
  - when `auto` is `false`, the `instances` field is **required** and gives the order in which the instances are considered. Every instance *not* appearing in this list is inlined.
- `inline`, an optional list of instance names to inline. It is **only allowed when `instances` is not given, and thus when `auto` is `true`**. In this case all submodule instances but those that appear in this list participate in the assume-guarantee decomposition.

The names in `instances` (respectively `inline`) must be pairwise distinct.

The following verification conditions (VC) are generated:
- Proving the present module by cutting participating submodule instances, and assuming their guarantees. Further tactics can be applied on this VC with the `tactic` field.
- For each participating submodule instance, proving that the present module ensures the assumptions of the instance. Further tactics can be applied by adding a `tactic` field inside the `instances` list in the instance' object.

## Tactic: `split`

The object must contain a `split_wire` field containing a width-1 wire, plus optional `case_false` and `case_true` subfields. Each of these, when present, must be a tactic object. An absent case means that the corresponding branch is proven directly, without further decomposition.

The `split_wire` is evaluated in the module owning the verification condition being split: in the goal's `module` at the top level.

## Tactic: `cutpoint`
Applies cutpoint to a given wire. The mandatory `wire` field is a Yosys select expression referring to the top module's wires.
This implements user-defined abstractions.

## Examples

- [tests/strategy1.json](tests/strategy1.json) illustrates the recursive structure with automatic instance ordering (its design references are illustrative, not the fixture).
- [tests/strategy2.json](tests/strategy2.json) is a complete assume-guarantee proof against the `tests/sample1.sv` fixture, with an explicit instance order.
- [tests/strategy3.json](tests/strategy3.json) shows automatic ordering with an inlined instance and a split nested inside a submodule goal.
- [tests/nested.json](tests/nested.json) illustrates nestings of various tactics.

## Resulting Verification Conditions and Hierarchical Proof Structure
Tactics yield a tree structure that proves a given objective. This structure is displayed by the tool at the end of the call.

Verification conditions that are actually checked by the tool are the leaves of this tree of verification conditions, while intermediate nodes' status are derived from the status of child verification conditions.

## Installation

The tool needs the Yosys Python bindings (`pyosys`), which are built locally
and installed system-wide.  They have no pip metadata, so they cannot be
declared as a dependency; instead, whatever environment runs the tool must be
able to see the system site packages.

With [pipx](https://pipx.pypa.io/):

```sh
pipx install --system-site-packages .
```

`--system-site-packages` is required.  Without it pipx creates an isolated
venv that cannot import `pyosys`, and the tool fails with
`ModuleNotFoundError: No module named 'pyosys'`.  To reinstall an existing
installation, add `--force`.

With plain `pip`, use a venv created with the same flag:

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install .
```

Either way this installs a `tactics4sby` executable:

```sh
tactics4sby tests/strategy0.json
```

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
- `tests/test_tactics4sby.py` — unit tests for the cell/dependency graph.
- `tests/test_cli.py` — end-to-end tests that invoke the command line
  (`python tactics4sby.py -f tests/strategy0.json`) in a subprocess and compare the
  generated `.sby` against the golden files in `tests/golden/`.

The end-to-end tests contribute to the same coverage report as the unit tests:
`[tool.coverage.run] patch = ["subprocess"]` makes coverage start in the child
processes, and pytest-cov combines their data files at the end of the run.

### Updating the golden files

When a change to the generator is intentional, regenerate the expected outputs:

```sh
for s in 0 1 2; do .venv/bin/python tactics4sby.py -f tests/strategy$s.json; \
  cp tests/strategy$s.sby tests/golden/strategy$s.sby; done
```

Then review the diff in `tests/golden/` before committing it.
