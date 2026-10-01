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
    top_assumption1 : assume (x & 5'b00001);
    top_property1 : assert (z >= 2);
    z = (y < 13) ? y : y - 2;
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  logic [4:0] sx;
  logic [4:0] z;
  initial z <= 1;
  always_comb begin
    sx = (x > 2) ? x : 5'd3;
    y  = (sx > z) ? sx : z;
  end
  always_ff @(posedge clk) begin
    z <= (z < y) ? y : z;
    subm_assume1 : assume (x & 5'b00001);
    subm_assert1 : assert (y >= 3 && (y & 5'b00001));
  end
endmodule
