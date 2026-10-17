`timescale 1ns/1ps
module tb_ecg_arithmetic;
    import ecg_q12_20_pkg::*;
    logic [67:0] expected [0:539]; // 180 cases x 3 words
    logic signed [48:0] rounded;
    string vectors;
    integer count;
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "FAIL missing VECTORS");
        if (!$value$plusargs("CASES=%d", count)) $fatal(1, "FAIL missing CASES");
        if (count != 180) $fatal(1, "FAIL unexpected arithmetic count %0d", count);
        $readmemh(vectors, expected);
        for (int i = 0; i < count; i++) begin
            rounded = round_even_20($signed(expected[3*i]));
            if (rounded !== expected[3*i+1][48:0])
                $fatal(1, "FAIL RNE case=%0d actual=%h expected=%h", i, rounded, expected[3*i+1]);
            if (fits_signed32(rounded) !== expected[3*i+2][0])
                $fatal(1, "FAIL range case=%0d", i);
            #1;
        end
        $display("PASS arithmetic cases=%0d signed_rounding_and_range", count);
        $finish;
    end
endmodule
