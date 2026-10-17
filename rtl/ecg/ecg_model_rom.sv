`timescale 1ns/1ps
// Xilinx inference template: two synchronous read ports, constant initialization,
// no reset of the memory or read-data registers. Add INIT_FILE to FPGA sources.
module ecg_model_rom #(
    parameter INIT_FILE = "tests/vectors/model_q12_20.hex"
) (
    input  logic clk,
    input  logic rst_n,
    input  logic en_a,
    input  logic [7:0] addr_a,
    output logic signed [31:0] data_a,
    output logic valid_a,
    input  logic en_b,
    input  logic [7:0] addr_b,
    output logic signed [31:0] data_b,
    output logic valid_b
);
    (* rom_style = "block" *) logic signed [31:0] mem [0:163];
    logic signed [31:0] q_a, q_b;

    initial $readmemh(INIT_FILE, mem);

    always_ff @(posedge clk) begin
        if (en_a && addr_a < 8'd164)
            q_a <= mem[addr_a];
    end
    always_ff @(posedge clk) begin
        if (en_b && addr_b < 8'd164)
            q_b <= mem[addr_b];
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_a <= 1'b0;
            valid_b <= 1'b0;
        end else begin
            valid_a <= en_a && (addr_a < 8'd164);
            valid_b <= en_b && (addr_b < 8'd164);
        end
    end
    // Invalid/disabled requests never expose stale or uninitialized data.
    assign data_a = valid_a ? q_a : 32'sd0;
    assign data_b = valid_b ? q_b : 32'sd0;
endmodule
