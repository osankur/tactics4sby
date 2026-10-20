// -- This file was copied and modified from the sby repository at https://github.com/yosysHQ/sby
// -- (see docs/examples/fifo.sv)
// --
// -- SymbiYosys (sby) -- Front-end for Yosys-based formal verification flows
// --
// -- Copyright (C) 2016  Claire Xenia Wolf <claire@yosyshq.com>
// --
// -- Permission to use, copy, modify, and/or distribute this software for any
// -- purpose with or without fee is hereby granted, provided that the above
// -- copyright notice and this permission notice appear in all copies.
// --
// -- THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
// -- WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
// -- MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
// -- ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
// -- WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
// -- ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
// -- OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.


// address generator/counter
module addr_gen #(
    parameter MAX_DATA  = 16,
    parameter ADDR_SIZE = 4
) (
    input en,
    clk,
    rst,
    output reg [ADDR_SIZE-1:0] addr
);
  logic init;

  initial addr <= 0;
  initial init <= 1;
  // async reset
  // increment address when enabled
  always @(posedge clk or posedge rst) begin
    if (rst) addr <= 0;
    else if (en) begin
      if (addr == MAX_DATA - 1) addr <= 0;
      else addr <= addr + 1;
    end
  end
endmodule

// Define our top level fifo entity
module fifo #(
    parameter MAX_DATA  = 16,
    parameter ADDR_SIZE = 4
) (
    input wen,
    ren,
    clk,
    rst,
    input [7:0] wdata,
    output [7:0] rdata,
    output [ADDR_SIZE:0] count,
    output full,
    empty
);
  wire wskip, rskip;
  reg [4:0] data_count;

  // fifo storage
  // async read, sync write
  wire [3:0] waddr, raddr;
  reg [7:0] data[MAX_DATA-1:0];
  always @(posedge clk) if (wen) data[waddr] <= wdata;
  assign rdata = data[raddr];
  // end storage

  // addr_gen for both write and read addresses
  addr_gen #(
      .MAX_DATA (MAX_DATA),
      .ADDR_SIZE(ADDR_SIZE)
  ) fifo_writer (
      .en  (wen || wskip),
      .clk (clk),
      .rst (rst),
      .addr(waddr)
  );

  addr_gen #(
      .MAX_DATA (MAX_DATA),
      .ADDR_SIZE(ADDR_SIZE)
  ) fifo_reader (
      .en  (ren || rskip),
      .clk (clk),
      .rst (rst),
      .addr(raddr)
  );

  // status signals
  initial data_count <= 0;

  always @(posedge clk or posedge rst) begin
    if (rst) data_count <= 0;
    else if (wen && !ren && data_count < MAX_DATA) data_count <= data_count + 1;
    else if (ren && !wen && data_count > 0) data_count <= data_count - 1;
  end

  assign full  = data_count == MAX_DATA;
  assign empty = (data_count == 0) && ~rst;
  assign count = data_count;

  // overflow protection
`ifndef NO_FULL_SKIP
  // write while full => overwrite oldest data, move read pointer
  assign rskip = wen && !ren && data_count >= MAX_DATA;
  // read while empty => read invalid data, keep write pointer in sync
  assign wskip = ren && !wen && data_count == 0;
`else
  assign rskip = 0;
  assign wskip = 0;
`endif  // NO_FULL_SKIP
`ifdef _AG_
  logic [4:0] prev_data_count;
  logic [2:0] init;
  initial prev_data_count = 0;
  initial init = 1;
  always @(posedge clk) begin
    //init <= (init == 0) ? init : init - 1;
    init <= 0;
    if (rst) prev_data_count <= 0;
    if (~rst) begin
      prev_data_count <= data_count;
      // ~init /\ $post(wen) /\ ~$past(ren) /\ $past(count)<MAX_DATA-1 -> count == prev_data_count + 1 && ~empty
      fifo_assert_incr :
      assert (init || !$past(
          wen
      ) || $past(
          ren
      ) || $past(
          rst
      ) || !($past(
          count
      ) < MAX_DATA - 1) || count == prev_data_count + 1 && ~empty);
      // ~init /\ ~$post(wen) /\ $past(ren) /\ ~empty -> count == prev_data_count - 1 && ~full
      fifo_assert_decr :
      assert (init || $past(
          wen
      ) || !$past(
          ren
      ) || $past(
          rst
      ) || empty || count == prev_data_count - 1 && ~full);

      // After rst, both count and prev_data_count are 0
      fifo_after_rst : assert (~$past(rst) || count == 0 && prev_data_count == 0);
      // ~init /\ ~$post(wen) /\ ~$past(ren) /\ ~$past(rst) -> count == prev_data_count
      fifo_unchanged_when_no_wen_no_ren :
      assert (init || $past(wen) || $past(ren) || $past(rst) || count == prev_data_count);
      // count is unchanged when both wen and ren are asserted
      // ~init /\ ~$past(rst) /\ $post(wen) /\ $past(ren)  -> count == $past(count)
      fifo_unchanged_when_wen_and_ren :
      assert (init || $past(rst) || !($past(wen) && $past(ren)) || count == $past(count));
      // empty <-> count == 0
      fifo_empty1 : assert ((~empty || count == 0) && (count != 0 || empty));
    end
  end
`endif


endmodule
