`timescale 1ns/1ps
module tb_ecg_rom #(
    parameter MODEL_FILE = "tests/vectors/model_q12_20.hex"
);
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, en_a = 0, en_b = 0;
    logic [7:0] addr_a = 0, addr_b = 0;
    logic signed [31:0] data_a, data_b;
    logic valid_a, valid_b;
    logic [31:0] expected [0:163];
    ecg_model_rom #(.INIT_FILE(MODEL_FILE)) dut (.*);
    initial begin
        $readmemh(MODEL_FILE, expected);
        repeat (2) @(negedge clk);
        if (valid_a !== 0 || valid_b !== 0) $fatal(1, "FAIL ROM reset");
        rst_n = 1;
        // Every address on both independent ports, back-to-back reads, last address.
        for (int i = 0; i < 164; i++) begin
            en_a = 1; en_b = 1;
            addr_a = 8'(i); addr_b = 8'(163-i);
            @(posedge clk); #1;
            if (valid_a !== 1 || valid_b !== 1 || data_a !== expected[i] || data_b !== expected[163-i])
                $fatal(1, "FAIL ROM one-cycle read address=%0d", i);
            @(negedge clk);
        end
        // Addresses 164 and 255 are invalid; no stale data may be consumed.
        addr_a = 164; addr_b = 255;
        @(posedge clk); #1;
        if (valid_a !== 0 || valid_b !== 0 || data_a !== 0 || data_b !== 0)
            $fatal(1, "FAIL invalid ROM address");
        @(negedge clk); en_a = 0; en_b = 1; addr_b = 15;
        @(posedge clk); #1;
        if (valid_a !== 0 || valid_b !== 1 || data_b !== expected[15])
            $fatal(1, "FAIL independent ROM enables");
        @(negedge clk); rst_n = 0; #1;
        if (valid_a !== 0 || valid_b !== 0 || data_a !== 0 || data_b !== 0)
            $fatal(1, "FAIL asynchronous ROM-valid reset");
        $display("PASS ROM 164_addresses_each_port latency=1 invalid_addresses independent_enables reset");
        $finish;
    end
    initial begin #100000; $fatal(1, "FAIL ROM timeout"); end
endmodule
