module main (
    clk,
    x,
    z
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] z;
  logic [4:0] y1, y2, y;

  subm s1 (
      .clk(clk),
      .x  (x),
      .y  (y1)
  );
  subm s2 (
      .clk(clk),
      .x  (y1),
      .y  (y2)
  );
  subm s3 (
      .clk(clk),
      .x  (y2),
      .y  (y)
  );
  always_comb begin
    top_assumption1 : assume (x[0] && x <= 5);
    intermediate_assert1 : assert (y1 >= 7);
    intermediate_assert2 : assert (y2 >= 9);
    top_property1 : assert (z >= 11);
    z = (y < 13) ? y : y - 2;
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  initial y = 1;
  always_comb begin
    y = (x + 2 < 13) ? x + 2 : 5'd3;
    subm_assume1 : assume (x[0]);
    subm_assert1 : assert (y[0] && y <= x + 2);
  end
endmodule
