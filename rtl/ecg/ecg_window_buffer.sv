`timescale 1ns/1ps
// Framed sample storage, NOT beat detection, sliding-window selection or resampling.
// Default: a caller-prepared 347-sample frame. FRAME_SAMPLES=500 stores raw windows
// unchanged for transport tests; it does not perform the training 500->347 transform.
module ecg_window_buffer #(
    parameter int unsigned FRAME_SAMPLES = 347,
    parameter int unsigned ADDR_WIDTH = (FRAME_SAMPLES > 1) ? $clog2(FRAME_SAMPLES) : 1,
    parameter int unsigned COUNT_WIDTH = $clog2(FRAME_SAMPLES + 1)
) (
    input logic clk, rst_n,
    input logic flush,
    input logic source_loss,
    // Descriptor must be accepted before the first sample of each frame.
    input logic frame_start_valid,
    output wire frame_start_ready,
    input wire [31:0] in_frame_id, in_beat_index_360,
    input wire [31:0] in_rr_curr_ticks_360, in_rr_prev_ticks_360,
    input wire signed [15:0] sample_in,
    input logic sample_valid,
    output wire sample_ready,
    // Level indication: full immutable frame, held until explicit release/abort.
    output wire frame_valid,
    output logic [31:0] frame_id, beat_index_360,
    output logic [31:0] rr_curr_ticks_360, rr_prev_ticks_360,
    output logic [COUNT_WIDTH-1:0] samples_collected,
    input logic frame_release_valid,
    output wire frame_release_ready,
    // One-entry elastic response, synchronous memory read, address echoed.
    input logic rd_req_valid,
    output wire rd_req_ready,
    input wire [ADDR_WIDTH-1:0] rd_req_addr,
    output wire rd_rsp_valid,
    input logic rd_rsp_ready,
    output wire signed [15:0] rd_rsp_data,
    output logic [ADDR_WIDTH-1:0] rd_rsp_addr,
    output logic rd_rsp_error,
    output wire fault,
    output logic loss_flag,
    output logic frame_abort
);
    typedef enum logic [2:0] {EMPTY, CAPTURE, SEAL, FULL, FAULT} state_t;
    state_t state;
    (* ram_style = "block" *) logic signed [15:0] memory [0:FRAME_SAMPLES-1];
    logic signed [15:0] read_data;
    logic response_pending;
    wire enabled = rst_n && !flush && !source_loss;
    wire write_fire = sample_valid && sample_ready;
    wire read_fire = rd_req_valid && rd_req_ready;

    assign frame_start_ready = enabled && (state == EMPTY);
    assign sample_ready = enabled && (state == CAPTURE);
    assign frame_valid = enabled && (state == FULL);
    assign frame_release_ready = frame_valid && !response_pending;
    assign rd_req_ready = frame_valid && !frame_release_valid &&
                          (!response_pending || rd_rsp_ready);
    assign rd_rsp_valid = enabled && response_pending;
    assign rd_rsp_data = (rd_rsp_valid && !rd_rsp_error) ? read_data : 16'sd0;
    assign fault = rst_n && (state == FAULT);

    // Never reset the RAM or data-read register. Invalid/unwritten memory is not
    // exposed because control permits reads only after all N writes complete.
    // CAPTURE and FULL are exclusive: no same-bank read/write collision exists.
    always_ff @(posedge clk) begin
        if (write_fire) memory[samples_collected[ADDR_WIDTH-1:0]] <= sample_in;
        if (read_fire && (int'(rd_req_addr) < FRAME_SAMPLES))
            read_data <= memory[rd_req_addr];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= EMPTY;
            samples_collected <= '0;
            frame_id <= '0;
            beat_index_360 <= '0;
            rr_curr_ticks_360 <= '0;
            rr_prev_ticks_360 <= '0;
            response_pending <= 1'b0;
            rd_rsp_addr <= '0;
            rd_rsp_error <= 1'b0;
            loss_flag <= 1'b0;
            frame_abort <= 1'b0;
        end else begin
            frame_abort <= 1'b0;
            // Loss dominates flush. Caller must stop/flush the source too before
            // a clean descriptor. Conservatively invalidate even a published frame.
            if (source_loss) begin
                frame_abort <= (state != EMPTY && state != FAULT);
                state <= FAULT;
                loss_flag <= 1'b1;
                samples_collected <= '0;
                response_pending <= 1'b0;
                rd_rsp_error <= 1'b0;
            end else if (flush) begin
                frame_abort <= (state != EMPTY && state != FAULT);
                state <= EMPTY;
                loss_flag <= 1'b0;
                samples_collected <= '0;
                response_pending <= 1'b0;
                rd_rsp_error <= 1'b0;
            end else begin
                if (rd_req_ready) begin
                    response_pending <= rd_req_valid;
                    if (rd_req_valid) begin
                        rd_rsp_addr <= rd_req_addr;
                        rd_rsp_error <= (int'(rd_req_addr) >= FRAME_SAMPLES);
                    end
                end else if (rd_rsp_valid && rd_rsp_ready) begin
                    response_pending <= 1'b0;
                end
                case (state)
                    EMPTY: if (frame_start_valid && frame_start_ready) begin
                        frame_id <= in_frame_id;
                        beat_index_360 <= in_beat_index_360;
                        rr_curr_ticks_360 <= in_rr_curr_ticks_360;
                        rr_prev_ticks_360 <= in_rr_prev_ticks_360;
                        samples_collected <= '0;
                        state <= CAPTURE;
                    end
                    CAPTURE: if (write_fire) begin
                        // Always write the last sample BEFORE publishing the frame.
                        samples_collected <= samples_collected + 1'b1;
                        if (samples_collected == COUNT_WIDTH'(FRAME_SAMPLES - 1)) state <= SEAL;
                    end
                    SEAL: state <= FULL; // One guard clock for upstream registered loss.
                    FULL: if (frame_release_valid && frame_release_ready) begin
                        state <= EMPTY;
                        samples_collected <= '0;
                    end
                    FAULT: begin end // Explicit flush/reset is required; no silent resync.
                    default: begin
                        state <= FAULT;
                        loss_flag <= 1'b1;
                        frame_abort <= 1'b1;
                        response_pending <= 1'b0;
                    end
                endcase
            end
        end
    end
endmodule
