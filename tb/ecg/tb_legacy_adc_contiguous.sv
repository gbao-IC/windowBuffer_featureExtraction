`timescale 1ns/1ps
// Deliberately tests the NEW requirement against the unmodified legacy module.
// Expected baseline FAIL: valid on adjacent clocks must represent distinct samples.
module tb_legacy_adc_contiguous;
    logic clk = 0, rst_n = 0, adc_valid = 0;
    logic [7:0] adc_data = 0;
    wire [7:0] sample_out;
    wire sample_valid, adc_overflow;
    wire [31:0] sample_count;
    integer received = 0;
    always #10 clk = ~clk;
    adc_interface dut (
        .clk(clk), .rst_n(rst_n), .sample_rate_div(16'd0), .mode_ppg_ecg(1'b1),
        .adc_data_in(adc_data), .adc_data_valid(adc_valid), .adc_clk(1'b0),
        .sample_out(sample_out), .sample_valid(sample_valid),
        .adc_overflow(adc_overflow), .sample_count(sample_count)
    );
    always @(posedge clk) if (rst_n && sample_valid) received++;
    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        @(negedge clk); adc_valid = 1; adc_data = 8'h01;
        @(negedge clk); adc_data = 8'h80;
        @(negedge clk); adc_data = 8'hff;
        @(negedge clk); adc_valid = 0;
        repeat (10) @(negedge clk);
        if (received != 3) $fatal(1, "FAIL LEGACY_CONTIGUOUS expected=3 actual=%0d", received);
        $display("PASS LEGACY_CONTIGUOUS");
        $finish;
    end
    initial begin #10000; $fatal(1, "FAIL baseline timeout"); end
endmodule
