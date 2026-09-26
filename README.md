# TODO List
- Add a cycle detection to CellGraph class: the dependency graph with cycles must be either rejected or rendered acyclic either with user-provided edge removals, or automatically
- Check that instance names are instances of submodules in a assume_guarantee tactic
- Add engines section to all objectives (an engines field at a lower level overrides the engine inherited by parent)
- Add options section to allow bmc (with options such as depth) and prove modes with the same inheritance rules
- Avoid reproving the same submodules in different tactic instances
- an assume guarantee VC cannot use a further assume_guarantee tactic. it can only contain split tactics.
- allow further cutpoint scripts inside objectives
- maybe disallow inout
# Proof Strategy

Proof strategies are described in JSON files. These describe hierarchical proof techniques to be applied when proving the properties of an input Verilog design.

At the top level, a `proof_strategy` object describes the design under verification with the following subfields:

- `header` describing a list of strings that are Yosys commands to be executed (such as reading Verilog files, activating define macros). The commands are executed in a single Yosys session, in order, before any objective is processed. Relative paths are resolved against the directory containing the strategy file.
- `objectives`, a list of `objective` objects describing verification objectives. This list can be empty.

Each objective is given by the following fields:

- `top` the name of the top module to be loaded. This module must exist after `header` has been executed.
- Optional `name` field, a user-supplied label for the objective (e.g. for logs and error messages). It has no semantic effect. Submodule entries are objectives, so they may be labelled the same way.
- Optional `early-assume` and `early-assert` Boolean fields (both default to `false`), which determine whether assume and assert cells inside processes must be activated in the initial step or delayed by one step. If `early-assume` is true then `early-assert` must be true as well. These fields may only be given on a top-level objective; nested objectives (submodule contracts and objectives reached through tactics) inherit their values, and it is an error to specify them there.
- The optional `assertions` field. If given, only these assertions of the top module are to be proven; otherwise all assertions are to be proven. When given, the list must not be empty.
- The optional `assumptions` field. If given, only these assumptions of the top module are considered; otherwise all assumptions are considered. When given, the list must not be empty.
- An optional `tactic` field containing a tactic object. If absent, the objective is a leaf: it is proven directly, without decomposition.

An objective's assertion and assumption selection always refers to properties of the `top` module. It never refers to the properties of that module's submodules. Objectives are proven independently of one another: no selection, assumption or intermediate result is shared between them.

A tactic object contains:
- A mandatory subfield `name`. We have `assume_guarantee` and `split` tactics allowed.

## Tactic: `assume_guarantee`

This tactic object contains an optional `submodules` field holding a non-empty list of `objective`s. A submodule is analysed exactly as a top-level objective, so its entry is an objective in its own right:

- a mandatory `top` field, the name of the submodule (it becomes the top module of the recursive analysis);
- optional `assertions` and `assumptions` fields, with the same meaning as on an objective: they select the properties that form the submodule's contract, and always refer to properties of the submodule itself. If absent, all assertions (respectively assumptions) appearing in the submodule are taken. When given, a list must not be empty;
- an optional `tactic` field containing a tactic object, to specify recursively how the submodule's contract is proven.

The `early-assume` / `early-assert` flags are *not* allowed on a submodule objective; they are inherited from the enclosing top-level objective.

If `submodules` is absent, then all modules instantiated inside the objective's `top` module are considered as submodules.

The object can moreover contain an `instances` field, a list of `Instance`s made of:

- a mandatory `name` field, the name of a module instance (the instance's module must appear in the list of submodules);
- an optional Boolean flag `inline` (default `false`). If `inline` is true, the instance is inlined and does not participate in the assume-guarantee proof; a tactic is then forbidden on this `Instance`;
- an optional `tactic` field containing a tactic object, to specify recursively how this verification condition is proven.

The `top`s of the `submodules` entries (respectively the `name`s of the `instances` entries) must be pairwise distinct.

The role of the submodule objectives and `Instance`s is the following. When applying the assume-guarantee rule, one verification condition is generated for each submodule considered in the hierarchical proof: it consists in proving the contract of the submodule separately. Moreover, a separate verification condition must be proven to establish that the top module guarantees each module instantiation's assumptions (so that the submodule's guarantees can be obtained): these are the `Instance`s. The recursive structure of the proof strategy allows the user to specify further tactics to prove each verification condition to be generated.

## Tactic: `split`

The object must contain a `split_expression` field containing a Verilog expression, plus optional `case_false` and `case_true` subfields. Each of these, when present, must be a tactic object. An absent case means that the corresponding branch is proven directly, without further decomposition. (An empty object `{}` is not a tactic and is rejected; use the absence of the field to mean "prove directly".) One can thus for instance nest a secondary split tactic inside, say, `case_true`.

The `split_expression` is evaluated in the module owning the verification condition being split: in the objective's `top` module at the top level; in the submodule of a submodule objective's tactic; and in the *parent* (top) module of an `Instance`'s tactic — since an `Instance` proves a property of the top module's environment, so the expression may refer to the top module's signals (hierarchical references such as `s1.y` are allowed).

Each objective is proven independently of the others.

## Examples

- [tests/strategy1.json](tests/strategy1.json) illustrates the recursive structure (its design references are illustrative, not the fixture).
- [tests/strategy2.json](tests/strategy2.json) is a complete assume-guarantee proof against the `tests/module_dep1.sv` fixture.
- [tests/strategy3.json](tests/strategy3.json) shows an inlined instance and a split nested inside an `Instance`.
