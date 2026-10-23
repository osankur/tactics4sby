module main (
    clk
);
  input clk;
  logic [4:0] y1, y2, y;
  initial begin
    y = 1;
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
    y <= (y1 < y2) ? y2 : y1;
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
