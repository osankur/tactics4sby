module main (
    clk,
    x,
    y
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] y;
  logic [4:0] y1;

  subm s1 (
      .clk(clk),
      .x  (x),
      .y  (y1)
  );
  always_comb begin
    top_assumption1 : assume (x & 5'b00001);
    top_property1 : assert (y & 5'b00001);
    y = (y1 < 13) ? y1 : y1 - 2;
  end
endmodule

module subm (
    input clk,
    inout logic [4:0] x,
    output logic [4:0] y
);
  initial y = 1;
  always_comb begin
    y = (x > 2) ? x : 5'd3;
    subm_assume1 : assume (x & 5'b00001);
    subm_assert1 : assert (y & 5'b00001);
  end
endmodule
