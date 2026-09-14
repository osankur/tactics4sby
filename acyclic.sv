module acyclic (
    x,
    z
);
  input logic [4:0] x;
  output logic [4:0] z;
  logic [4:0] y;

  subm s (
      .x(x),
      .y(y)
  );
  always_comb begin
    assume1 : assume (x > 0);
    acyclic_assert1 : assert (z >= 2);
    z = (y < 13) ? y : y - 2;
  end
endmodule

module subm (
    input  logic [4:0] x,
    output logic [4:0] y
);
  always_comb begin
    y = (x > 2) ? x : 5'd2;
    subm_assert1 : assert (y >= 2);
  end
endmodule
