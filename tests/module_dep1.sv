module top (
    clk,
    x,
    z
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] z;
  logic [4:0] y1, y;
  logic undriven1, undriven2;

  subm s1 (
      .clk(clk),
      .x  (x),
      .y  (y1)
  );
  subm s2 (
      .clk(clk),
      .x  (y1),
      .y  (y)
  );
  always_comb begin
    pure_assume1 : assume (x > 0);
    pure_acyclic_assert1 : assert (z >= 2);
    nonpure_assume1 : assume (x > y1);
    nonpure_assume2 : assume (undriven2);
    nonpure_acyclic_assert1 : assert (z >= 2 && undriven1);
    z = (y < 13) ? y : y - 2;
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  logic [4:0] z;
  initial z <= 0;
  always_comb begin
    y = (x > 2) ? x : 5'd2;
    subm_assert1 : assert (y >= 2);
  end
  always_ff @(posedge clk) begin
    subm_assume1 : assume (y > 0);
    z <= (z < 15) ? z + 1 : z;
    subm_assert2 : assert (y >= 2 && z > 0);
  end
endmodule
