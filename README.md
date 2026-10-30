# Tactics4sby
Tactics4sby is a helper tool that helps structure proof strategies in a reproducible way when applying for formal verification of hardware designs
with [Yosys](https://github.com/YosysHQ/yosys/)/[sby](https://github.com/YosysHQ/sby/).
One specifies a set of tactics to be applied to prove a given design. Each tactic generates one or more verification conditions, which can be refined with further tactics.

The tool can be seen as a generator for .sby files.
Given a proof strategy as a .json file, it generates an .sby configuration file which would be error-prone to do manually; it runs `sby`, and reports back the results of the verification condition tree.

```
                tactics4sby                   sby
+---------------+          +--------------+         +-------------------------+
| strategy.json | -------> | strategy.sby | ------> | reporting               |
+---------------+          +--------------+         | PASS / FAIL / UNKNOWN   |
                                                    +-------------------------+
```

The currently supported tactics are the following
- `split`: Case splitting on a Boolean value
- `abstract`: Abstraction and cutpoint (Yosys `cutpoint` and `abstsract` commands)
- `assume_guarantee`: Assume-guarantee reasoning on submodules and asserts
- `inductive_assume_guarantee`: Circular assume-guarantee reasoning (with induction over time)

For example, the file below specifies a split tactic producing two verification conditions: one assumes that the wire `x` is true, and the second one assumes that it is false.
```json
{
  "proof_strategy": {
    "header": [
      "read_verilog -sv design.sv"
    ],
    "files": [
      "design.sv"
    ],
    "goal": {
      "module": "top",
      "tactic": {
        "name": "split",
        "split_wire": "x"
      }
    }
  }
}
```

Below is an example of reporting where the first case succeeds and the other one fails:

```sh
┌┬[❌] _vc_top (by SplitTactic)
│├─ [✅] _vc_top_split0
││     sby logs: design__vc_top_split0
│└─ [❌] _vc_top_split1
│      sby logs: design__vc_top_split1
│    failing ASSERT: top._witness_.check_assert_design_sv_7_2 at design.sv:7.5-7.15
│    trace: design__vc_top_split1/engine_0/trace.vcd
```

See [docs/usage.md](docs/usage.md) for more examples of usage and details on these tactics.

See [docs/input_format.md](docs/input_format.md) for the input format.

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
pipx install --python /usr/bin/python3 .
scripts/install_yosys.sh --pipx tactics4sby
```

### With a virtual environment

```sh
git clone --recurse-submodules git@gitlab.inria.fr:osankur/tactics4sby.git
cd tactics4sby
python3 -m venv .venv                  # or: uv venv --seed --python /usr/bin/python3
scripts/install_yosys.sh               # installs pyosys into .venv
.venv/bin/python -m pip install .
```

`scripts/install_yosys.sh` builds the pinned Yosys (in `.build/yosys` by
default) and installs the pyosys bindings into `.venv/bin/python`, or into the
pipx environment with `--pipx <app>`.  This takes tens of minutes, use `--jobs N` to change the parallelism.

Both variants write `.yosys-env`, which selects the freshly built `yosys` and
points `sby` at it:

```sh
source .yosys-env
tactics4sby tests/strategy0.json
```

Without it the tool uses whichever `yosys` comes first on `PATH`, which may
not support `add -not`.
