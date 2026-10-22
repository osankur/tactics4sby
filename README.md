# Tactics4sby
Tactics4sby is a helper tool that helps structure proof strategies to be used for formal verification of hardware designs
with [Yosys](https://github.com/YosysHQ/yosys/)/[sby](https://github.com/YosysHQ/sby/).
One specifies a set of tactics to be applied to prove a given design. Each tactic generates one or more verification conditions, which can be refined with further tactics.

The supported tactics are the following
- `abstract`: Abstraction and cutpoint (Yosys `cutpoint` and `abstsract` commands)
- `split`: Case splitting on a Boolean value
- `assume_guarantee`: Assume-guarantee reasoning on submodules and asserts
- `inductive_assume_guarantee`: Circular assume-guarantee reasoning (with induction over time)

Given a proof strategy as a .json file, the tool generates an .sby configuration file, runs `sby`, and reports back the results of verification condition tree.


See [docs/getting_started.md](docs/getting_started.md) for examples of usage and details on these tactics.

## Installation

The tool relies on two features that are not in upstream Yosys yet: the
`add -not` command and the pyosys `SigMap` bindings.  The required Yosys
revision is therefore pinned as the `vendor/yosys` submodule, and the PyPI
`pyosys` wheel cannot be used instead.

### Prerequisites

- [`sby`](https://github.com/YosysHQ/sby) on `PATH` (for example
  `make install` from its repository, or the OSS CAD Suite).  The tool runs
  both `sby` and `yosys` as external commands.
- `git`, CMake >= 3.28, a C++20 compiler, and Python >= 3.10 with development
  headers.  `ccache` is used when available.

### With pipx

```sh
git clone --recurse-submodules git@gitlab.inria.fr:osankur/tactics4sby.git
cd tactics4sby
pipx install .
scripts/install_yosys.sh --pipx tactics4sby
```

### With a virtual environment

```sh
git clone --recurse-submodules git@gitlab.inria.fr:osankur/tactics4sby.git
cd tactics4sby
python3 -m venv .venv                  # or: uv venv --seed
scripts/install_yosys.sh               # installs pyosys into .venv
.venv/bin/python -m pip install .
```

If you cloned without `--recurse-submodules`, run
`git submodule update --init --recursive` first.

`scripts/install_yosys.sh` builds the pinned Yosys (in `.build/yosys` by
default) and installs the pyosys bindings into `.venv/bin/python`, or into the
pipx environment with `--pipx <app>`.  The first run takes tens of minutes:
the sources are built once for the `yosys` binary and once more for the Python
bindings.  Later runs finish in seconds unless the submodule commit changes.
Use `--jobs N` to change the parallelism.

Both variants write `.yosys-env`, which selects the freshly built `yosys` and
points `sby` at it:

```sh
source .yosys-env
tactics4sby tests/strategy0.json
```

Without it the tool uses whichever `yosys` comes first on `PATH`, which may
not support `add -not`.

pipx installs a copy of the sources, so after changing them reinstall with
`pipx install --force .`.  In a venv, use
`.venv/bin/python -m pip install -e .` instead.
