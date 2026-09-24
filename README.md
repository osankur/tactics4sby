# Proof Strategy

Proof strategies are described in JSON files. These describe hierarchical proof techniques to be applied when proving the properties of an input Verilog design.

At the top level, a `proof_strategy` object describes the design under verification with the following subfields:

- `header` describing a list of strings that are Yosys commands to be executed (such as reading Verilog files, activating define macros). The commands are executed in a single Yosys session, in order, before any objective is processed. Relative paths are resolved against the directory containing the strategy file.
- `objectives`, a list of `objective` objects describing verification objectives. This list can be empty.

Each objective is given by the following fields:

- `top` the name of the top module to be loaded. This module must exist after `header` has been executed.
- Optional `early-assume` and `early-assert` Boolean fields (both default to `false`), which determine whether assume and assert cells inside processes must be activated in the initial step or delayed by one step. If `early-assume` is true then `early-assert` must be true as well.
- The optional `assertions` field. If given, only these assertions of the top module are to be proven; otherwise all assertions are to be proven. When given, the list must not be empty.
- The optional `assumptions` field. If given, only these assumptions of the top module are considered; otherwise all assumptions are considered. When given, the list must not be empty.
- An optional `tactic` field containing a tactic object. If absent, the objective is a leaf: it is proven directly, without decomposition.

An objective's assertion and assumption selection always refers to properties of the `top` module. It never refers to the properties of that module's submodules. Objectives are proven independently of one another: no selection, assumption or intermediate result is shared between them.

A tactic object contains:
- A mandatory subfield `name`. We have `assume_guarantee` and `split` tactics allowed.

## Tactic: `assume_guarantee`

This tactic object contains an optional `submodules` field holding a non-empty list of `SubmoduleVC`s. Each `SubmoduleVC` is made of:

- a mandatory `name` field, the name of the submodule;
- optional `assertions` and `assumptions` fields, with the same meaning as on an objective: they select the properties that form the submodule's contract, and always refer to properties of the submodule itself. If absent, all assertions (respectively assumptions) appearing in the submodule are taken. When given, a list must not be empty;
- an optional `tactic` field containing a tactic object, to specify recursively how the submodule's contract is proven.

If `submodules` is absent, then all modules instantiated inside the objective's `top` module are considered as submodules.

The object can moreover contain an `instances` field, a list of `InstanceVC`s made of:

- a mandatory `name` field, the name of a module instance (the instance's module must appear in the list of submodules);
- an optional Boolean flag `inline` (default `false`). If `inline` is true, the instance is inlined and does not participate in the assume-guarantee proof; a tactic is then forbidden on this `InstanceVC`;
- an optional `tactic` field containing a tactic object, to specify recursively how this verification condition is proven.

The `name`s of the `submodules` (respectively `instances`) entries must be pairwise distinct.

The role of the `SubmoduleVC`s and `InstanceVC`s is the following. When applying the assume-guarantee rule, one `SubmoduleVC` verification condition is generated for each submodule considered in the hierarchical proof: it consists in proving the contract of the submodule separately. Moreover, a separate verification condition must be proven to establish that the top module guarantees each module instantiation's assumptions (so that the submodule's guarantees can be obtained): these are the `InstanceVC`s. The recursive structure of the proof strategy allows the user to specify further tactics to prove each verification condition to be generated.

## Tactic: `split`

The object must contain a `split_expression` field containing a Verilog expression, plus optional `case_false` and `case_true` subfields. Each of these, when present, must be a tactic object. An absent case means that the corresponding branch is proven directly, without further decomposition. (An empty object `{}` is not a tactic and is rejected; use the absence of the field to mean "prove directly".) One can thus for instance nest a secondary split tactic inside, say, `case_true`.

The `split_expression` is evaluated in the module owning the verification condition being split: in the objective's `top` module at the top level; in the submodule of a `SubmoduleVC`'s tactic; and in the *parent* (top) module of an `InstanceVC`'s tactic — since an `InstanceVC` proves a property of the top module's environment, so the expression may refer to the top module's signals (hierarchical references such as `s1.y` are allowed).

Each objective is proven independently of the others.

## Examples

- [tests/strategy1.json](tests/strategy1.json) illustrates the recursive structure (its design references are illustrative, not the fixture).
- [tests/strategy2.json](tests/strategy2.json) is a complete assume-guarantee proof against the `tests/module_dep1.sv` fixture.
- [tests/strategy3.json](tests/strategy3.json) shows an inlined instance and a split nested inside an `InstanceVC`.
