from __future__ import annotations
import io
import json
from pathlib import Path

import pytest

import configuration
import sby_generator
from parser import parse_string

#: Two instances in a chain: ``s2`` reads ``s1``'s output.
CHAIN_SV = """\
module main (input clk, input logic [3:0] x, output logic [3:0] z);
  logic [3:0] y1, y2;
  logic case1;
  assign case1 = y1[0];
  subm s1 (.clk(clk), .x(x),  .y(y1));
  subm s2 (.clk(clk), .x(y1), .y(y2));
  always_comb begin
    top_assert : assert (y2 >= 1);
    z = y2;
  end
endmodule

module subm (input clk, input logic [3:0] x, output logic [3:0] y);
  always_comb begin
    subm_assume1 : assume (x > 0);
    y = x;
  end
endmodule
"""


@pytest.fixture
def make_design(tmp_path: Path):
    def _make(sv: str, top: str = "main", *, multiclock: bool = False):
        src = tmp_path / "design.sv"
        src.write_text(sv, encoding="utf-8")
        cfg = configuration.Configuration(
            tmp_path, verbosity=2, tmpdir=tmp_path, verbose_yosys=True
        )
        return cfg

    return _make


def top_module(design, name: str = "main"):
    """The module ``name`` of ``design`` (yosys stores names with a backslash)."""
    return design.module(f"\\{name}")


# --------------------------------------------------------------------------- #
# Strategy tests (parsed straight from a string, no temp file)
# --------------------------------------------------------------------------- #


def test_inline_strategy_parses(make_design, monkeypatch):
    cfg = make_design(CHAIN_SV)
    # The CLI does ``os.chdir(cfg.basedir)`` before building, which is what makes
    # the relative paths in ``header`` resolve. Mirror that here.
    monkeypatch.chdir(cfg.basedir)
    strategy_json = json.dumps(
        {
            "proof_strategy": {
                "header": ["read_verilog -sv design.sv"],
                "files": ["design.sv"],
                "top": "main",
                "goal": {
                    "module": "main",
                    "tactic": {"name": "split", "split_wire": "y1"},
                },
                "subgoals": [],
            }
        }
    )
    strategy = parse_string(strategy_json)
    sby_file = cfg.basedir / "dummy.sby"
    # y1 is 4 bits wide, so the split tactic must reject it.
    with pytest.raises(Exception, match=r"width of the split_wire 'y1' is not 1"):
        sby_generator.SbyGenerator(strategy, cfg).get_sby_script(sby_file)

    strategy_json = json.dumps(
        {
            "proof_strategy": {
                "header": ["read_verilog -sv design.sv"],
                "files": ["design.sv"],
                "top": "main",
                "goal": {
                    "module": "main",
                    "tactic": {"name": "split", "split_wire": "y3"},
                },
                "subgoals": [],
            }
        }
    )
    strategy = parse_string(strategy_json)
    sby_file = cfg.basedir / "dummy.sby"
    # No y2 so reject
    with pytest.raises(Exception, match=r"Could not find wire 'y3' in module 'main'"):
        sby_generator.SbyGenerator(strategy, cfg).get_sby_script(sby_file)

    strategy_json = json.dumps(
        {
            "proof_strategy": {
                "header": ["read_verilog -sv design.sv"],
                "files": ["design.sv"],
                "top": "main",
                "goal": {
                    "module": "main",
                    "tactic": {"name": "split", "split_wire": "case1"},
                },
                "subgoals": [],
            }
        }
    )
    strategy = parse_string(strategy_json)
    script = """[script]
_vc_main:
read_verilog -sv design.sv
hierarchy -top main
proc
chformal -remove -cover -live
--
_vc_main_split0:
select -module main
add -assume case1 -not
--
_vc_main_split1:
select -module main
add -assume case1
--

"""
    options_and_engines = """[options]
_vc_main_split0: mode prove
_vc_main_split1: mode prove

[engines]
_vc_main_split0: smtbmc
_vc_main_split1: smtbmc
"""
    buf = io.StringIO()
    sby_file = cfg.basedir / "dummy.sby"
    sby = sby_generator.SbyGenerator(strategy, cfg).get_sby_script(sby_file)
    sby.dump(buf)
    output = buf.getvalue()
    assert script in output
    assert options_and_engines in output

    strategy_json = json.dumps(
        {
            "proof_strategy": {
                "header": ["read_verilog -sv design.sv"],
                "files": ["design.sv"],
                "top": "main",
                "goal": {
                    "module": "main",
                    "tactic": {
                        "name": "split",
                        "split_wire": "case1",
                        "case_false": {"name": "none", "options": ["mode bmc"]},
                    },
                },
                "subgoals": [],
            }
        }
    )
    options_and_engines = """[options]
_vc_main_split0: mode bmc
_vc_main_split1: mode prove

[engines]
_vc_main_split0: smtbmc
_vc_main_split1: smtbmc
"""
    strategy = parse_string(strategy_json)
    sby_file = cfg.basedir / "dummy.sby"
    buf = io.StringIO()
    sby = sby_generator.SbyGenerator(strategy, cfg).get_sby_script(sby_file)
    sby.dump(buf)
    output = buf.getvalue()
    assert options_and_engines in output
