module main (
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
    top_assumption1 : assume (x > 0);
    top_property1 : assert (z >= 2);
    top_assumption2 : assume (x > y1);
    top_assumption3 : assume (undriven2);
    top_property2 : assert (z >= 2 && undriven1);
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
    z <= (z < 15) ? z + 1 : z;
    subm_assume1 : assume (y > 0);
    subm_assert2 : assert (y >= 2 && z > 0);
  end
endmodule
