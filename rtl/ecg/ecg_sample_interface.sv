`timescale 1ns/1ps
// ECG-only, same-clock signed16 transport. No scaling or sampling-rate timer.
// Ingress and egress are independent ready/valid channels. While stalled, the
// producer must hold sample_valid and sample_in until acceptance. A legal stall
// is NOT overflow. source_overflow reports loss in an upstream acquisition adapter.
module ecg_sample_interface (
    input  logic clk,
    input  logic rst_n,
    input  wire signed [15:0] sample_in,
    input  logic sample_valid,
    output wire sample_ready,
    output wire signed [15:0] sample_out,
    output wire sample_out_valid,
    input  logic sample_out_ready,
    input  logic source_overflow,
    output logic overflow_pulse,
    output logic overflow_flag
);
    logic signed [15:0] sample_reg;
    logic data_pending;

    assign sample_ready = rst_n && (!data_pending || sample_out_ready);
    assign sample_out_valid = rst_n && data_pending;
    assign sample_out = sample_reg;

    // All storage has exactly one procedural writer, including pending and flags.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sample_reg <= 16'sd0;
            data_pending <= 1'b0;
            overflow_pulse <= 1'b0;
            overflow_flag <= 1'b0;
        end else begin
            overflow_pulse <= source_overflow;
            if (source_overflow) overflow_flag <= 1'b1;
            if (sample_ready) begin
                // Dequeue and enqueue on the same edge replaces the old sample.
                data_pending <= sample_valid;
                if (sample_valid) sample_reg <= sample_in;
            end
        end
    end
endmodule
