module main (
    clk,
    x,
    y
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] y;
  logic [4:0] y1, y2, x_y2, xs;

  subm s1 (
      .clk(clk),
      .x  (xs),
      .y  (y1)
  );
  subm s2 (
      .clk(clk),
      .x  (y1),
      .y  (y2)
  );
  always_comb begin
    top_assumption1 : assume (x & 5'b00001);
    // top_assumption2 : assume (x > 0);
    top_property1 : assert (y & 5'b00001);
    s1_guarantee : assert (y1 >= 3 && (y1 & 5'b00001));
    // s2_guarantee : assert (y2 >= 3 && (y2 & 5'b00001));
    x_y2 = (x + y2);
    xs = (x_y2[0]) ? x_y2 : 5'd3;
    y = (y2 < 13) ? y2 : y2 - 2;
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  initial y = 1;
  always_ff @(posedge clk) begin
    y <= (x > 2) ? x : 5'd3;
    subm_assume1 : assume (x & 5'b00001);
    subm_assert1 : assert (y & 5'b00001);
  end
endmodule
