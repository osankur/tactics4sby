module protocol (
    input clk,
    input rst
);

  logic wen, ren;
  logic [7:0] wdata;
  logic [7:0] rdata;
  logic [4:0] count;
  logic full, empty;

  logic [3:0] step;

  initial begin
    wen   = 0;
    ren   = 0;
    wdata = 8'b00000000;
    step  = 0;
  end
  ;
  fifo comm (
      .wen  (wen),
      .ren  (ren),
      .clk  (clk),
      .rst  (rst),
      .wdata(wdata),
      .rdata(rdata),
      .count(count),
      .full (full),
      .empty(empty)
  );
  always_ff @(posedge clk) begin
    if (rst) begin
      step <= 0;
      wen  <= 0;
      ren  <= 0;
    end
    if (~rst) begin
      if (step == 0) begin
        ren   <= 0;
        wen   <= 1;
        wdata <= 8'b00000001;
      end else if (step == 1) begin
        ren   <= 0;
        wen   <= 1;
        wdata <= 8'b00000010;
      end else if (step == 2) begin
        wen <= 0;
        ren <= 1;
      end else if (step == 3) begin
        wen <= 0;
        ren <= 1;
      end
      step <= (step == 4) ? step : step + 1;
      protocol_assert1 : assert ($past(step) < 4 || empty);
    end
  end
endmodule
