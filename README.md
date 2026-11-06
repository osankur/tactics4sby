# tactics4sby

tactics4sby provides reproducible proof strategies for [sby](https://github.com/YosysHQ/sby)/[Yosys](https://github.com/YosysHQ/yosys): you describe a verification plan
in JSON, get one `.sby` task per verification condition, and the tool returns readable verification results.

Here is how to apply a case-split strategy on the value of wire `x`:
```json
{
  "proof_strategy": {
    "header": ["read_verilog -sv split_example.sv"],
    "files": ["split_example.sv"],
    "goal": { "module": "top", "tactic": { "name": "split", "split_wire": "x" } }
  }
}
```

```console
$ tactics4sby docs/examples/split_example.json
┌┬[❌] _vc_top (by SplitTactic)
│├─ [❌] _vc_top_split0
││     sby logs: docs/examples/split_example__vc_top_split0
││   failing ASSERT: top._witness_.check_assert_split_example_sv_11_2 at split_example.sv:11.5-11.15
││   trace: docs/examples/split_example__vc_top_split0/engine_0/trace.vcd
│└─ [✅] _vc_top_split1
│      sby logs: docs/examples/split_example__vc_top_split1
```

The currently supported tactics are the following
- `split`: Case splitting on a Boolean value
- `abstract`: Abstraction and cutpoint (Yosys `cutpoint` and `abstract` commands)
- `assume_guarantee`: Assume-guarantee reasoning on submodules and asserts
- `inductive_assume_guarantee`: Circular assume-guarantee reasoning (with induction over time)

Each tactic yields sub-goals that can be refined with further tactics, which results in a tree of verification conditions.

See [usage](docs/usage.md) ·
[input format](docs/input_format.md) for more information and examples.

> **Yosys note:** requires a pinned Yosys revision due to minor added features not available upstream.

The tool can be seen as a generator for .sby files.
Given a proof strategy as a .json file, it generates an .sby configuration file which would be error-prone to do manually; it runs `sby`, and reports back the results of the verification condition tree.

```
                tactics4sby                   sby
+---------------+          +--------------+         +-------------------------+
| strategy.json | -------> | strategy.sby | ------> | reporting               |
+---------------+          +--------------+         | PASS / FAIL / UNKNOWN   |
                                                    +-------------------------+
```

## Installation

The tool relies on two features that are not in upstream Yosys yet: the
`add -not` command and the pyosys `SigMap` bindings.  The required Yosys
revision is therefore pinned as the `vendor/yosys` submodule, and the PyPI
`pyosys` wheel cannot be used instead.

### Prerequisites

- [`sby`](https://github.com/YosysHQ/sby) on `PATH` (for example
  `make install` from its repository, or the OSS CAD Suite).  The tool runs
  both `sby` and `yosys` as external commands.
- Python >= 3.10 with development headers.
- Yosys requirements (see [vendor/yosys](vendor/yosys))

### With pipx

```sh
git clone --recurse-submodules https://github.com/osankur/tactics4sby.git
cd tactics4sby
pipx install --python /usr/bin/python3 .
scripts/install_yosys.sh --pipx tactics4sby
```

### With a virtual environment

```sh
git clone --recurse-submodules https://github.com/osankur/tactics4sby.git
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
