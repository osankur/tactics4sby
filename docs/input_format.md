## Proof Strategy Format
Proof strategies are described in JSON files.
These describe hierarchical proof techniques to be applied when proving the properties of an input Verilog design.

At the top level, a `proof_strategy` object describes the design under verification with the following subfields:

- `header` describing a list of strings that are Yosys commands to be executed (such as reading Verilog files, activating define macros). The commands are executed in a single Yosys session, in order, before any goal is processed. Relative paths are resolved against the directory containing the strategy file.
- `files`, a mandatory list of source files to be considered in the sby configuration scripts. It may be empty.
- `goal`, a mandatory `goal` object describing the main goal to be proved.
- `subgoals`, an optional list of `goal` objects describing additional goals that are required to prove the main goal. This list can be empty.
- Optional `assume_early` is a Boolean field (defaulting to `true`), which determines whether assume cells inside processes must read current values of signals or previous ones.
- Optional `options` and `engines` lists of strings. These are global options and engines that will be active for all tasks.

Each goal is given by the following fields:

- `module` the name of the module to be analyzed. This module must exist after `header` has been executed.
- An optional `tactic` field containing a tactic object. If absent, the goal is a leaf: it is proven directly, without decomposition.
- Optional `name`, a label used in logs and error messages; it has no semantic effect.
- Optional `options` and `engines` lists of strings, the sby defaults for this goal.

The contract of a goal's `module` module is *all* of its assertions and assumptions. There is no way to select a subset but macros can be used when loading a file to select a subset.
This always refers to properties of the `module`, never to those of its submodules. Goals are proven independently of one another: no assumption or intermediate result is shared between them.

A tactic object contains:
- A mandatory subfield `name`. We have the followings tactics allowed: `assume_guarantee`, `abstract`, `split`.
- Optional `options` and `engines` lists. These values, when given, override parent tactic's options and engines values. Note however that the global options and engines are never overridden.

### Tactic: `assume_guarantee`

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

An `assume_guarantee` (or `inductive_assume_guarantee`) tactic may not appear anywhere inside the subtree of another one, whether reached through the `tactic` field, an `instances` entry, or nested `split`/`abstract` tactics. To decompose a sub-goal assume-guarantee style, prove it separately as a `subgoal` instead.

### Tactic: `split`

The object must contain a `split_wire` field containing a width-1 wire, plus optional `case_false` and `case_true` subfields. Each of these, when present, must be a tactic object. An absent case means that the corresponding branch is proven directly, without further decomposition.

The `split_wire` is evaluated in the module owning the verification condition being split: in the goal's `module` at the top level.

### Tactic: `abstract`
Applies `abstract` or `cutpoint` commands to given wires or dffs.
The mandatory field `commands` is a non-empty list of strings; each command must start with `"abstract"` or `"cutpoint"` and will be added to the generated sby script.
This implements user-defined abstractions.

## Examples

- [tests/strategy1.json](tests/strategy1.json) illustrates the recursive structure with automatic instance ordering (its design references are illustrative, not the fixture).
- [tests/strategy2.json](tests/strategy2.json) is a complete assume-guarantee proof against the `tests/sample1.sv` fixture, with an explicit instance order.
- [tests/strategy3.json](tests/strategy3.json) shows automatic ordering with an inlined instance and a split nested inside a submodule goal.
- [tests/nested.json](tests/nested.json) illustrates nestings of various tactics.

## Validating strategy files

[`proof_strategy.schema.json`](../proof_strategy.schema.json) is a JSON Schema
describing the format above, as implemented by `parser.py`.

To get validation and completion in your editor, point the file at the schema:

```json
{
  "$schema": "../proof_strategy.schema.json",
  "proof_strategy": { }
}
```

To validate from the command line or from CI, one can use
[`check-jsonschema`](https://github.com/python-jsonschema/check-jsonschema) as follows.

```sh
check-jsonschema --schemafile proof_strategy.schema.json tests/strategy1.json
```

## Resulting Verification Conditions and Hierarchical Proof Structure
Tactics yield a tree structure that proves a given objective. This structure is displayed by the tool at the end of the call.

Verification conditions that are actually checked by the tool are the leaves of this tree of verification conditions, while intermediate nodes' status are derived from the status of child verification conditions.