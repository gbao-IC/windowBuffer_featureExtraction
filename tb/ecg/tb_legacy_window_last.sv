`timescale 1ns/1ps
// Reproduce the preserved baseline's missing final write, without editing it.
module tb_legacy_window_last;
    logic clk = 0, rst_n = 0, valid = 0, read_en = 0;
    logic [7:0] data = 0;
    logic [8:0] address = 0;
    wire [7:0] output_data;
    wire ready, bank;
    wire [31:0] count;
    integer i;
    always #10 clk = ~clk;
    window_buffer dut (.clk(clk), .rst_n(rst_n), .enable(1'b1), .soft_reset(1'b0),
        .sample_in(data), .sample_valid(valid), .read_en(read_en), .read_addr(address),
        .frame_out(output_data), .window_ready(ready), .samples_collected(count), .ready_bank(bank));
    initial begin
        repeat (3) @(negedge clk); rst_n = 1;
        for (i=0; i<512; i++) begin
            @(negedge clk); valid = 1; data = (i == 511) ? 8'ha5 : 8'h55;
        end
        @(negedge clk); valid = 0; read_en = 1; address = 9'd511;
        @(negedge clk); read_en = 0;
        if (output_data !== 8'ha5 || count !== 32'd512)
            $fatal(1, "FAIL LEGACY_WINDOW_LAST expected=a5/count512 actual=%h/count%0d", output_data, count);
        $display("PASS LEGACY_WINDOW_LAST"); $finish;
    end
endmodule
