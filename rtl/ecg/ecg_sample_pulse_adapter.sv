`timescale 1ns/1ps
// For a SAME-CLOCK source that cannot pause (e.g. a future XADC adapter).
// Every clock with arrival_valid=1 is one new sample, including adjacent clocks.
// Full + stalled: drop the NEW arrival, preserve the queued sample, report loss.
// This wrapper is not an analog ADC, a CDC bridge, or an XADC-code converter.
module ecg_sample_pulse_adapter (
    input  logic clk,
    input  logic rst_n,
    input  wire signed [15:0] arrival_sample,
    input  logic arrival_valid,
    output wire arrival_ready,
    output wire signed [15:0] sample_out,
    output wire sample_out_valid,
    input  logic sample_out_ready,
    output wire overflow_pulse,
    output wire overflow_flag
);
    wire dropped_arrival;
    assign dropped_arrival = rst_n && arrival_valid && !arrival_ready;

    ecg_sample_interface transport (
        .clk(clk), .rst_n(rst_n),
        .sample_in(arrival_sample),
        .sample_valid(arrival_valid && arrival_ready),
        .sample_ready(arrival_ready),
        .sample_out(sample_out), .sample_out_valid(sample_out_valid),
        .sample_out_ready(sample_out_ready),
        .source_overflow(dropped_arrival),
        .overflow_pulse(overflow_pulse), .overflow_flag(overflow_flag)
    );
endmodule
