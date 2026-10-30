module protocol (
    input clk,
    input rst,
    input [7:0] input_data,
    output [7:0] output_data,
    output en_output
);
  localparam RECEIVE = 2'b00, PROCESS = 2'b01, SCHEDULE = 2'b10, SEND = 2'b11;
  logic [2:0] state;

  logic sender_wen, sender_ren;
  logic [7:0] sender_rdata;
  logic [4:0] sender_count;
  logic sender_full, sender_empty;

  logic receiver_wen, receiver_ren;
  logic [7:0] receiver_wdata;
  logic [7:0] receiver_rdata;
  logic [4:0] receiver_count;
  logic receiver_full, receiver_empty;

  logic [3:0] step;
  logic [3:0] past_step;

  initial begin
    state = 0;
    sender_wen = 0;
    sender_ren = 0;
    receiver_wen = 0;
    receiver_ren = 0;
    step = 0;
    past_step = 0;
  end
  ;
  assign en_output = state == SEND;
  fifo #(
      .MAX_DATA (16),
      .ADDR_SIZE(4)
  ) receiver (
      .wen  (receiver_wen),
      .ren  (receiver_ren),
      .clk  (clk),
      .rst  (rst),
      .wdata(input_data),
      .rdata(receiver_rdata),
      .count(receiver_count),
      .full (receiver_full),
      .empty(receiver_empty)
  );

  fifo #(
      .MAX_DATA (32),
      .ADDR_SIZE(5)
  ) sender (
      .wen  (sender_wen),
      .ren  (sender_ren),
      .clk  (clk),
      .rst  (rst),
      .wdata(receiver_rdata),
      .rdata(output_data),
      .count(sender_count),
      .full (sender_full),
      .empty(sender_empty)
  );
  always_ff @(posedge clk) begin
    if (rst) begin
      step <= 0;
      past_step <= 0;
      sender_wen <= 0;
      sender_ren <= 0;
      receiver_wen <= 0;
      receiver_ren <= 0;
    end
    if (~rst) begin
      if (state == RECEIVE && step < 4) begin
        receiver_wen <= 1;
        receiver_ren <= 0;
        sender_wen <= 0;
        sender_ren <= 0;
        state <= PROCESS;
      end else if (state == PROCESS) begin
        receiver_wen <= 0;
        receiver_ren <= 1;
        sender_wen <= 0;
        sender_ren <= 0;
        state <= SCHEDULE;
      end else if (state == SCHEDULE) begin
        receiver_wen <= 0;
        receiver_ren <= 0;
        sender_wen <= 1;
        sender_ren <= 0;
        state <= SEND;
      end else if (state == SEND) begin
        receiver_wen <= 0;
        receiver_ren <= 0;
        sender_wen <= 0;
        sender_ren <= 1;
        state <= RECEIVE;
        step <= (step == 4) ? step : step + 1;
      end
      protocol_assert1 : assert ($past(step) < 4 || sender_empty && receiver_empty);
    end
  end
endmodule
