`timescale 1ns/1ps
// Unsigned, iterative floor division / floor square root with exact remainder.
// No '/', real arithmetic, vendor IP, or combinational unrolled divider.
module ecg_feature_math (
    input logic clk, rst_n, abort, start, sqrt_op,
    input wire [191:0] numerator, denominator,
    output logic busy, done, error,
    output logic [191:0] quotient, remainder
);
    logic mode;
    logic [7:0] count;
    logic [191:0] shift_reg, divisor;
    logic [192:0] rem_reg, trial, candidate, rem_next;
    logic [95:0] root_reg, root_next;
    logic [191:0] quotient_next;
    logic take_bit;
    always_comb begin
        trial = mode ? ((rem_reg << 2) | {191'b0,shift_reg[191:190]}) :
                       ((rem_reg << 1) | {192'b0,shift_reg[191]});
        candidate = mode ? (({97'b0,root_reg} << 2) | 193'd1) : {1'b0,divisor};
        take_bit = trial >= candidate;
        rem_next = take_bit ? trial-candidate : trial;
        root_next = {root_reg[94:0],take_bit};
        quotient_next = {shift_reg[190:0],take_bit};
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy<=0; done<=0; error<=0; quotient<='0; remainder<='0;
            mode<=0; count<=0; shift_reg<='0; divisor<='0; rem_reg<='0; root_reg<='0;
        end else if (abort) begin
            busy<=0; done<=0; error<=0; quotient<='0; remainder<='0;
            mode<=0; count<=0; shift_reg<='0; divisor<='0; rem_reg<='0; root_reg<='0;
        end else begin
            done<=0;
            if (start && !busy) begin
                mode<=sqrt_op; count<=0; shift_reg<=numerator; divisor<=denominator;
                rem_reg<='0;root_reg<='0;error<=0;
                if (!sqrt_op && denominator==0) begin
                    busy<=0;done<=1;error<=1;quotient<='0;remainder<='0;
                end else busy<=1;
            end else if (busy) begin
                rem_reg<=rem_next;count<=count+1'b1;
                if (mode) begin
                    shift_reg<=shift_reg<<2;root_reg<=root_next;
                    if (count==8'd95) begin
                        busy<=0;done<=1;quotient<={96'b0,root_next};remainder<=rem_next[191:0];
                    end
                end else begin
                    shift_reg<=quotient_next;
                    if (count==8'd191) begin
                        busy<=0;done<=1;quotient<=quotient_next;remainder<=rem_next[191:0];
                    end
                end
            end
        end
    end
endmodule
