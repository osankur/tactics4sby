module main (
    clk,
    x,
    y
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] y;
  logic [4:0] y1, y2, tmp;
  initial begin
    tmp = 1;
    y   = 1;
  end
  subm s1 (
      .clk(clk),
      .x  (x),
      .y  (y1)
  );
  subm s2 (
      .clk(clk),
      .x  (tmp),
      // .x  (y1),
      .y  (y2)
  );
  always_ff @(posedge clk) begin
    tmp <= y1;
    y   <= y2;
    top_assume : assume (x[0]);
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
