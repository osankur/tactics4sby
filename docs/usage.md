# Tactics4sby Usage
The tool expects a proof strategy in .json format. A proof strategy focuses on proving a particular Verilog module.
All assertions of the flattened design become proof targets, and all assumptions are considered as assumptions during verification.

The simplest proof strategy is given in [sample1.json](sample1.json).

```json
{
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv"
    ],
    "files": [
      "fifo.sv"
    ],
    "goal": {
      "module": "fifo"
    }
  }
}
```
This strategy describes a direct proof of the module `fifo` in `fifo.sv` (this is a copy of the example from the `sby` repository with modified assertions).

Running `tactics4sby sample1.json` generates the file `sample1.sby` in the same directory as the given .json file,
runs the proof target, and displays the results:

```
┌─[❔] _vc_fifo
│    sby logs: sample1__vc_fifo
│  failing ASSERT: fifo.fifo_assert_decr at fifo.sv:140.7-147.59
│  trace: sample1__vc_fifo/engine_0/trace_induct.vcd
```

Here, there is only one verification condition (called `_vc_fifo`) which checks all asserts.
The k-induction algorithm applied by default failed to produce a proof. This can be inspected by looking inside the displayed sby logs directory `sample1__vc_fifo` (sby is run at the same directory as the .json and the produced .sby file so that is also where this log directory is).

To fix this, we can either increase the depth, or change the engine.
Let us use the `abc pdr` engine ([sample2.json](sample2.json))

```json
{
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv"
    ],
    "files": [
      "fifo.sv"
    ],
    "goal": {
      "module": "fifo",
      "engines" : ["abc pdr"]
    }
  }
}
```
You can add the `-f` option to overwrite the previously produced  `.sby` file when calling the tool again:

```
  tactics4sby -f sample2.json
```

Verification succeeds:
```
┌─[✅] _vc_fifo
│    engines: ['abc pdr']
│    sby logs: sample2__vc_fifo
```

> [!NOTE]
>In the generated file [sample2.sby](sample2.sby), notice that the `header` section was copied at the top of the `script` section;
>the `files` section was copied inside the `files` section, and similarly for `engines`.
>It is also possible to add an `options` field.

## Tactics
The previously shown strategies get simply translated to straightforward sby configuration files.
Let us now apply tactics, which is where tactics4sby becomes more interesting.

### Split Tactic
Assume that we want to split the proof into two cases: the case where the input `wdata=0` and the case where `wdata>0`. The wire `proof_case` defined in `fifo.sv` defines the latter case.
The tactic can be applied as follows ([sample3.json](sample3.json)).

```json
{
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv"
    ],
    "files": [
      "fifo.sv"
    ],
    "goal": {
      "module": "fifo",
      "engines": [
        "abc pdr"
      ],
      "tactic": {
        "name": "split",
        "split_wire": "proof_case1"
      }
    }
  }
}
```

This results in the following verification status.

```
┌┬[✅] _vc_fifo (by SplitTactic)
││   engines: ['abc pdr']
│├─ [✅] _vc_fifo_split0
││     sby logs: sample3__vc_fifo_split0
│└─ [✅] _vc_fifo_split1
│      sby logs: sample3__vc_fifo_split1
```

In fact, the main verification condition `_vc_fifo` is proven by the split tactic, through two child verification tasks
`_vc_fifo_split0` (`proof_case=0`) and `_vc_fifo_split1` (`proof_case=1`).

It is possible to chain other tactics when proving both verification conditions by specifying tactics for `case_true` and `case_false`.
For instance:
```json
{
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv"
    ],
    "files": [
      "fifo.sv"
    ],
    "goal": {
      "module": "fifo",
      "engines": [
        "abc pdr"
      ],
      "tactic": {
        "name": "split",
        "split_wire": "proof_case1",
        "case_true": {
          "name": "split",
          "split_wire": "proof_case2"
        }
      }
    }
  }
}
```

This results in 3 successful verification conditions:
```
┌┬[✅] _vc_fifo (by SplitTactic)
││   engines: ['abc pdr']
│├─ [✅] _vc_fifo_split0
││     sby logs: sample4__vc_fifo_split0
│└─┬[✅] _vc_fifo_split1 (by SplitTactic)
│  ├─ [✅] _vc_fifo_split1_split0
│  │     sby logs: sample4__vc_fifo_split1_split0
│  └─ [✅] _vc_fifo_split1_split1
│        sby logs: sample4__vc_fifo_split1_split1
```


> [!NOTE]
>Verification conditions that are actually checked by the tool are the leaves of this tree of verification conditions, while intermediate nodes' status are derived from the status of child verification conditions.

> [!NOTE]
> Because unused wires can be optimized out by Yosys, it is a good idea to add a `(* keep *)` attribute for Boolean wires defining a case split;
> See  [fifo.sv](fifo.sv).

### Abstract Tactic
This tactic simply consists in applying a list of `abstract` and `cutpoint` commands to make the design more abstract. Here, the user has the freedom of applying these commands since they are all sound (if the proof passes, non-abstracted design is also correct).

Let us abstract away the outputs of `data` which maps to a memory cell, when proving the case `proof_case1=1` ([sample5.json](sample5.json)):

```json
{
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv"
    ],
    "files": [
      "fifo.sv"
    ],
    "goal": {
      "module": "fifo",
      "engines": [
        "abc pdr"
      ],
      "tactic": {
        "name": "split",
        "split_wire": "proof_case1",
        "case_true": {
          "name": "abstract",
          "commands": [
            "cutpoint r:MEMID=\\data"
          ]
        }
      }
    }
  }
}
```
In fact, none of the assertions of `fifo.sv` really depends on the content of `data`; they only talk about the size of the fifo:

```
┌┬[✅] _vc_fifo (by SplitTactic)
││   engines: ['abc pdr']
│├─ [✅] _vc_fifo_split0
││     sby logs: sample5__vc_fifo_split0
│└─┬[✅] _vc_fifo_split1 (by AbstractTactic)
│  └─ [✅] _vc_fifo_split1_abs
│        sby logs: sample5__vc_fifo_split1_abs
```

Here, we applied cutpoint to cells that has the parameter `MEMID=\data` which corresponds to `$memrd` and `$memwr` cells at this point in synthesis.

> [!NOTE] The logs of the first pass of sby can be inspected in `sample5__vc_fifo_split1_abs/model/design.log` and the intermediate design produced at the end in `sample5__vc_fifo_split1_abs/model/design.il`. It is useful to inspect these logs and the design to inspect the result of the tactics.

> [!NOTE] The `--dump-dot-circuits` option dumps an .svg depiction of the circuits inside `src/` in the log directory.

However, the `count` signal is important for proving the assertions, and abstracting it leads to a failure:

```
┌┬[❌] _vc_fifo (by SplitTactic)
││   engines: ['abc pdr']
│├─ [✅] _vc_fifo_split0
││     sby logs: sample6__vc_fifo_split0
│└─┬[❌] _vc_fifo_split1 (by AbstractTactic)
│  └─ [❌] _vc_fifo_split1_abs
│        sby logs: sample6__vc_fifo_split1_abs
│      failing ASSERT: fifo.fifo_after_rst at fifo.sv:152.7-152.82
│      trace: ~/tactics4sby/docs/examples/sample6__vc_fifo_split1_abs/engine_0/trace.vcd
```

All failing verification conditions are recursively marked with ❌, and the counterexample trace .vcd file is displayed.

### Assume-Guarantee Tactic
Assume-guarantee reasoning proves a module from the contracts of its submodule instances rather than from their implementation: the `assume` cells of an instance are its assumptions (what it expects in its inputs), its `assert` cells are its guarantees (what it promises in its outputs).
All assume and asserts cells that appear in a module are considered to be its contract. Use macros to remove select relevant formal cells.

The tactic generates one verification condition proving the assumptions of each participating submodule instance from the guarantees of the instances ordered before it, plus a top-level verification condition proving the assertions of the enclosing module from the guarantees of all participating instances.
The participating instances are flattened and their outputs cutpointed, so each verification condition may rely only on the guarantees it is explicitly given. With `auto` (the default) this order is computed automatically.
But it is also possible to provide it manually by setting `auto` to false.

With the top-level assumptions `A` and assertions `P` of module `M`, and participating instances `I_1, …, I_n` of respective modules `M_1, …, M_n`, the following inference rule is used, where `A_i` and `G_i` are the assumptions and guarantees of `M_i`:

```
M_i ⊨ A_i -> G_i                              for each i ∈ {1, …, n}   (module subgoals)
  M ⊨ A, G_1, …, G_{i-1} -> A_i               for each i ∈ {1, …, n}   (instance VCs)
  M ⊨ A, G_1, …, G_n -> P                                              (parent VC)
──────────────────────────────────────────────────────────────
M ⊨ A -> P
```

A description of this rule and its use with sby (without tactics4sby) can be found on [this blog post](https://osankur.github.io/formal-verification-blog/sby-ag.html).

The example [sender_receiver.json](examples/sender_receiver.json) applies the tactic to the `protocol` module of [sender_receiver.sv](examples/sender_receiver.sv), which instantiates two FIFOs from [fifo.sv](examples/fifo.sv):

```json
{
  "$schema": "../proof_strategy.schema.json",
  "proof_strategy": {
    "header": [
      "read -define FORMAL=1",
      "read_verilog -sv fifo.sv",
      "read_verilog -sv sender_receiver.sv"
    ],
    "files": [
      "fifo.sv",
      "sender_receiver.sv"
    ],
    "goal": {
      "module": "protocol",
      "tactic": {
        "name": "assume_guarantee"
      }
    },
    "subgoals": [
      {
        "module": "fifo",
        "engines": [
          "abc pdr"
        ]
      }
    ]
  }
}
```

The `fifo` instances `receiver` and `sender` both take part, and automatic ordering puts `receiver` first because `sender` reads `receiver_rdata`.
The parent verification condition (`_vc_protocol_ag_top`) proves `protocol_assert1` from the two FIFO guarantees, the two instance verification conditions (`_vc_protocol_ag_receiver`, `_vc_protocol_ag_sender`) prove the FIFOs' assumptions hold inside (there are actually none so they are trivial),
and the `fifo` subgoal proves the FIFO module's guarantees.

When the `subgoals` field is ommitted, the submodules are proven with default engine and options (which is `smtbmc` engine and `mode prove`).
It is possible to specify a tactic inside each subgoal.

Running `tactics4sby -f sender_receiver.json` succeeds:

```
┌┬[✅] _vc_protocol (by AssumeGuaranteeTactic)
│├─ [✅] _vc_protocol_ag_top
││     sby logs: sender_receiver__vc_protocol_ag_top
│├─ [✅] _vc_protocol_ag_receiver
││     sby logs: sender_receiver__vc_protocol_ag_receiver
│└─ [✅] _vc_protocol_ag_sender
│      sby logs: sender_receiver__vc_protocol_ag_sender
├─[✅] _vc__paramod_621e6fdc67855e575f34c361ae88af9f59b87b7c_fifo
│    engines: ['abc pdr']
│    sby logs: sender_receiver__vc__paramod_621e6fdc67855e575f34c361ae88af9f59b87b7c_fifo
└[✅] _vc__paramod_502e203e307143fc86ef5f601ed091f05a4c3cfd_fifo
     engines: ['abc pdr']
     sby logs: sender_receiver__vc__paramod_502e203e307143fc86ef5f601ed091f05a4c3cfd_fifo
```

> [!NOTE]
> The two `$paramod` names are the two parameterizations of `fifo` used by `protocol`. These names are given by Yosys during the hierarchy pass. Both modules are proven using the options and tactics given in the `fifo` subgoal.

By default, all submodule instances participate in the assume-guarantee rule.
To select only some of them, use the `instances` field ([sample7.json](sample7.json)):

```json
  {
    "proof_strategy": {
      "header": [
        "read -define FORMAL=1",
        "read_verilog -sv fifo.sv",
        "read_verilog -sv sender_receiver.sv"
      ],
      "files": [
        "fifo.sv",
        "sender_receiver.sv"
      ],
      "goal": {
        "module": "protocol",
        "tactic": {
          "name": "assume_guarantee",
          "instances": [
            {
              "name": "receiver",
              "tactic": {
                "name": "abstract",
                "commands": [
                  "cutpoint r:MEMID=\\data"
                ]
              }
            }
          ]
        }
      },
      "subgoals": [
        {
          "module": "fifo",
          "engines": [
            "abc pdr"
          ]
        }
      ]
    }
  }
```

Here, only `receiver` will be decomposed for the assume-guarantee rule.
Moreover, we specified here an abstraction tactic to prove the verification condition for the instance receiver.

One can also add a tactic to prove the parent goal (`_vc_protocol_ag_top`) with a tactic:
```json
...
  "goal": {
      "module": "protocol",
      "tactic": {
        "name": "assume_guarantee",
        "tactic" : { ... }
      }
    },
...
```
This tactic is only applied to proving `_vc_protocol_ag_top`, while tactics for instance VCs must be specified inside the `instances` field.

It is also possible to include all but some given instances in assume-guarantee with the `inline` field:

```json
...
  "goal": {
      "module": "protocol",
      "tactic": {
        "name": "assume_guarantee",
        "inline" : ["sender"]
      }
    },
...
```
which has the effect of inlining `sender` but decomposing `receiver` by the assume-guarantee rule.

Last, both `instances` and `inline` fields accept the name of a module rather than instance names.
For instance, `"instances" : { "name" : "subm" }` means including all instances of the module `subm` in the assume-guarantee decomposition.

### Inductive Assume-Guarantee Tactic
The inductive variant removes the acyclicity requirement of the previous tactic. There is no order between the instances: to prove the assumptions `A_i` of an instance `I_i` at time `t`, the top-level assumptions `A` are used together with the guarantees `G_j` of the instances, but every `G_j` is only assumed up to time `t-1`. Since the module subgoals prove `A_i -> G_i`, establishing all `A_i` at time `t` establishes all `G_i` at time `t`, and these become the induction hypotheses at time `t+1`.

By induction over time, the rule is therefore sound even when the instance dependencies form a cycle. At the initial time step there is no previous guarantee, so the instance verification conditions reduce to proving the assumptions from the top-level assumptions. The tactic requires `assume_early` to be `false` and only runs in automatic mode; `instances` restricts which instances participate, but their order does not matter.

With the same notation as above, the inference rule is:

```
M_i ⊨ A_i -> G_i                              for each i ∈ {1, …, n}   (module subgoals)
M ⊨ A, G_1^{t-1}, …, G_n^{t-1} -> A_i^t       for each i ∈ {1, …, n}   (instance VCs)
M ⊨ A, G_1, …, G_n -> P                                                (parent VC)
──────────────────────────────────────────────────────────────
M ⊨ A -> P
```

A description of this rule and its use with sby (without tactics4sby) can be found on [this blog post](https://osankur.github.io/formal-verification-blog/sby-ag.html) (see the circular assume-guarantee rule).

> [!NOTE]
> Here, assume_early must be set to false due to sby that applies `chformal -early -remove` during synthesis. In fact, in order to encode G_i^{t-1}, tactics4sby introduces $ff cells to delay the assumptions, but these are then removed by the above chformal command.

Consider the following design [ind.sv](ind.sv).
```verilog
module main (
    clk
);
  input clk;
  logic [4:0] y1, y2, y, s1y, s2y;
  initial begin
    y  = 1;
    y1 = 1;
    y2 = 1;
  end
  subm s1 (
      .clk(clk),
      .x  (y2),
      .y  (s1y)
  );
  subm s2 (
      .clk(clk),
      .x  (y1),
      .y  (s2y)
  );
  always_ff @(posedge clk) begin
    y  <= (y1 < y2) ? y2 : y1;
    y1 <= s1y;
    y2 <= s2y;
    top_assert : assert (y[0]);
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  initial y = 1;
  always_ff @(posedge clk) begin
    y <= (x + 2 < 13) ? x + 2 : 5'd3;
    subm_assume1 : assume (x[0]);
    subm_assert1 : assert (y[0]);
  end
endmodule
```

The assume-guarantee tactic fails here. In fact, both instances `s1` and `s2` symmetrically depends on each other: each `si` returns an odd number provided that `s{i-1}` returns an odd number.
The inductive assume guarantee tactic can be successfully used with the following strategy file [ind.json](ind.json).

```json
{
  "proof_strategy": {
    "header": [
      "read_verilog -sv ind.sv"
    ],
    "files": [
      "ind.sv"
    ],
    "assume_early": false,
    "goal": {
      "module": "main",
      "tactic": {
        "name": "inductive_assume_guarantee"
      }
    }
  }
}
```

This gives

```
┌┬[✅] _vc_main (by InductiveAssumeGuaranteeTactic)
│├─ [✅] _vc_main_ag_top
││     sby logs: ind__vc_main_ag_top
│├─ [✅] _vc_main_ag_s2
││     sby logs: ind__vc_main_ag_s2
│└─ [✅] _vc_main_ag_s1
│      sby logs: ind__vc_main_ag_s1
└[✅] _vc__subm
     sby logs: ind__vc__subm
```

As in the assume-guarantee rule, one parent VC is generated that proves the top-level assertions (assertions of `main` here) by assuming top-level assumptions and and the assertions of the submodules. Here this means proving `assert (y[0]);` assuming `s1y[0];` and `s2y[0]` (which are the assertions of the submodules).

Then for each submodule instance, there is a VC. For `s1`, the task `_vc_main_ag_s1` assumes the top-level assumptions, and the assertion of `s2` up to time `t-1` and proves the assumption of `s1`. This means `assume ($past(s2y[0]));` and `assert (s1y[0]);` here.

Counterexamples are perhaps more tricky to understand due to this. For example, if we connect directly the output of `s1` to the input of `s2`, and vice versa,
then the assumptions at time `t-1` are not strong enough to prove the instance VCs:

```verilog
module main (
    clk
);
  input clk;
  logic [4:0] y1, y2, y;
  initial begin
    y  = 1;
  end
  subm s1 (
      .clk(clk),
      .x  (y2),
      .y  (y1)
  );
  subm s2 (
      .clk(clk),
      .x  (y1),
      .y  (y2)
  );
  always_ff @(posedge clk) begin
    y  <= (y1 < y2) ? y2 : y1;
    y1 <= s1y;
    y2 <= s2y;
    top_assert : assert (y[0]);
  end
endmodule
...
```
This gives

```
┌┬[❌] _vc_main (by InductiveAssumeGuaranteeTactic)
│├─ [✅] _vc_main_ag_top
││     sby logs: ind2__vc_main_ag_top
│├─ [❌] _vc_main_ag_s2
││     sby logs: ind2__vc_main_ag_s2
││   failing ASSERT: main.s2.subm_assume1 at ind2.sv:33.5-33.33
││   trace: ind2__vc_main_ag_s2/engine_0/trace.vcd
│└─ [❌] _vc_main_ag_s1
│      sby logs: ind2__vc_main_ag_s1
│    failing ASSERT: main.s1.subm_assume1 at ind2.sv:33.5-33.33
│    trace: ind2__vc_main_ag_s1/engine_0/trace.vcd
└[✅] _vc__subm
     sby logs: ind2__vc__subm
```

So the parent VC succeeds as the assertions of the submodules are sufficient to prove it.
However, instance VCs cannot be proven with this inference rule: either stronger contracts must be chosen for the submodule or other tactics must be used.