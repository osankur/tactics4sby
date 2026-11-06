module top (
    clk,
    x,
    y
);
  input clk;
  input logic x;
  output logic y;
  initial y = 1;
  always_ff @(posedge clk) begin
    assert (y);
    y <= x;
  end
endmodule
