module main (
    clk,
    x,
    z
);
  input clk;
  input logic [4:0] x;
  output logic [4:0] z;
  logic [4:0] y1, y2, y;
  logic undriven1, undriven2;

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
    assert (y2 >= 2);
    pure_assume1 : assume (x > 0);
    z = (y < 13) ? y : y - 2;
  end
endmodule

module subm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  logic [4:0] z, y1;
  initial z <= 0;
  subsubm s3 (
      .clk(clk),
      .x  (x),
      .y  (y1)
  );
  always_comb begin
    subm_assume1 : assume (x > 0);
    y = (z > 2) ? z : 5'd2;
    assert (y >= 2);
  end
  always_ff @(posedge clk) begin
    z <= (z < 15) ? z + 1 : y1;
  end
endmodule


module subsubm (
    input clk,
    input logic [4:0] x,
    output logic [4:0] y
);
  logic [4:0] z;
  initial z <= 0;
  always_comb begin
    subsubm_assume1 : assume (x > 0);
    assert (y >= 2);
    y = (x > 2) ? x : 5'd2;
  end
endmodule
