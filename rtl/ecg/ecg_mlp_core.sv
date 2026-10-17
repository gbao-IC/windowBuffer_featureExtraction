`timescale 1ns/1ps
// Authoritative standalone ECG Stage-A core. No dependency on the legacy top.
// One inference at a time; see docs/phase2a_report.md for the cycle/handshake contract.
module ecg_mlp_core #(
    parameter MODEL_FILE = "tests/vectors/model_q12_20.hex"
) (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    input  wire signed [31:0] features [0:11],
    output logic ready,
    output logic busy,
    output logic valid,
    output logic done,
    output logic overflow,
    output logic [2:0] error_stage, // 0=none, 1=normalizer, 2=FC1, 3=FC2, 4=ROM
    output logic [1:0] class_id,
    output logic signed [31:0] normalized [0:11],
    output logic signed [31:0] pre_activation [0:7],
    output logic signed [31:0] hidden [0:7],
    output logic signed [31:0] logits [0:3],
    // Registered diagnostic events; no backpressure. Unused debug logic may prune.
    output logic trace_valid,
    output logic [1:0] trace_stage, // 1=normalizer product, 2=FC1 sum, 3=FC2 sum
    output logic [3:0] trace_index,
    output logic signed [67:0] trace_value
);
    import ecg_q12_20_pkg::*;

    typedef enum logic [3:0] {
        IDLE, NORM_REQ, NORM_MULT, NORM_ROUND,
        BIAS_REQ, BIAS_LOAD, WEIGHT_REQ, MAC_MULT, MAC_ADD, LAYER_ROUND,
        ARG_INIT, ARG_SCAN, FINISH
    } state_t;
    state_t state;
    logic armed, second_layer;
    logic [3:0] index;
    logic [2:0] neuron;
    logic [1:0] arg_index, best_index;
    logic signed [31:0] best_logit;
    logic signed [31:0] snapshot [0:11];
    logic en_a, en_b, rom_valid_a, rom_valid_b;
    logic [7:0] addr_a, addr_b;
    logic signed [31:0] rom_a, rom_b;
    logic signed [32:0] multiply_a;
    logic signed [31:0] multiply_b, mac_input;
    logic signed [64:0] multiply_result, product_reg;
    logic signed [67:0] accumulator, round_input;
    logic signed [68:0] extended_sum;
    logic signed [48:0] rounded;
    integer reset_index;

    ecg_model_rom #(.INIT_FILE(MODEL_FILE)) model_rom (
        .clk(clk), .rst_n(rst_n),
        .en_a(en_a), .addr_a(addr_a), .data_a(rom_a), .valid_a(rom_valid_a),
        .en_b(en_b), .addr_b(addr_b), .data_b(rom_b), .valid_b(rom_valid_b)
    );

    assign ready = rst_n && (state == IDLE) && armed;
    assign busy = rst_n && (state != IDLE);

    always_comb begin
        en_a = 1'b0;
        en_b = 1'b0;
        addr_a = 8'd0;
        addr_b = 8'd0;
        case (state)
            NORM_REQ: begin
                en_a = 1'b1;
                en_b = 1'b1;
                addr_a = {4'b0, index};
                addr_b = 8'd12 + {4'b0, index};
            end
            BIAS_REQ: begin
                en_a = 1'b1;
                addr_a = (second_layer ? 8'd160 : 8'd120) + {5'b0, neuron};
            end
            WEIGHT_REQ: begin
                en_a = 1'b1;
                if (second_layer)
                    addr_a = 8'd128 + {2'b0, neuron, 3'b0} + {4'b0, index};
                else
                    addr_a = 8'd24 + {1'b0, neuron, 4'b0}
                             - {3'b0, neuron, 2'b0} + {4'b0, index};
            end
            default: begin end
        endcase
    end

    // One shared multiplier for normalization and both layers. Full signed33x32
    // result; MAC input is sign-extended signed32, so product[64:63] must agree.
    always_comb begin
        mac_input = 32'sd0;
        if (second_layer) begin
            if (index < 4'd8) mac_input = hidden[index[2:0]];
        end else begin
            if (index < 4'd12) mac_input = normalized[index];
        end
        multiply_a = $signed({mac_input[31], mac_input});
        multiply_b = rom_a;
        if (state == NORM_MULT) begin
            multiply_a = $signed({snapshot[index][31], snapshot[index]})
                         - $signed({rom_a[31], rom_a});
            multiply_b = rom_b;
        end
        multiply_result = multiply_a * multiply_b;
        extended_sum = $signed({accumulator[67], accumulator})
                       + $signed({{5{product_reg[63]}}, product_reg[63:0]});
        round_input = accumulator;
        if (state == NORM_ROUND)
            round_input = $signed({{3{product_reg[64]}}, product_reg});
        rounded = round_even_20(round_input);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            armed <= 1'b1;
            second_layer <= 1'b0;
            index <= 4'd0;
            neuron <= 3'd0;
            arg_index <= 2'd0;
            best_index <= 2'd0;
            best_logit <= 32'sd0;
            accumulator <= 68'sd0;
            product_reg <= 65'sd0;
            valid <= 1'b0;
            done <= 1'b0;
            overflow <= 1'b0;
            error_stage <= 3'd0;
            class_id <= 2'd0;
            trace_valid <= 1'b0;
            trace_stage <= 2'd0;
            trace_index <= 4'd0;
            trace_value <= 68'sd0;
            for (reset_index = 0; reset_index < 12; reset_index = reset_index + 1) begin
                snapshot[reset_index] <= 32'sd0;
                normalized[reset_index] <= 32'sd0;
            end
            for (reset_index = 0; reset_index < 8; reset_index = reset_index + 1) begin
                pre_activation[reset_index] <= 32'sd0;
                hidden[reset_index] <= 32'sd0;
            end
            for (reset_index = 0; reset_index < 4; reset_index = reset_index + 1)
                logits[reset_index] <= 32'sd0;
        end else begin
            done <= 1'b0;
            trace_valid <= 1'b0;
            if (!start) armed <= 1'b1;
            case (state)
                IDLE: if (start && ready) begin
                    for (reset_index = 0; reset_index < 12; reset_index = reset_index + 1)
                        snapshot[reset_index] <= features[reset_index];
                    armed <= 1'b0;
                    valid <= 1'b0;
                    overflow <= 1'b0;
                    error_stage <= 3'd0;
                    class_id <= 2'd0;
                    index <= 4'd0;
                    neuron <= 3'd0;
                    second_layer <= 1'b0;
                    state <= NORM_REQ;
                end
                NORM_REQ: state <= NORM_MULT;
                NORM_MULT: begin
                    if (!rom_valid_a || !rom_valid_b) begin
                        error_stage <= 3'd4;
                        state <= FINISH;
                    end else begin
                        product_reg <= multiply_result;
                        trace_valid <= 1'b1;
                        trace_stage <= 2'd1;
                        trace_index <= index;
                        trace_value <= $signed({{3{multiply_result[64]}}, multiply_result});
                        state <= NORM_ROUND;
                    end
                end
                NORM_ROUND: begin
                    if (!fits_signed32(rounded)) begin
                        overflow <= 1'b1;
                        error_stage <= 3'd1;
                        state <= FINISH;
                    end else begin
                        normalized[index] <= rounded[31:0];
                        if (index == 4'd11) begin
                            index <= 4'd0;
                            state <= BIAS_REQ;
                        end else begin
                            index <= index + 4'd1;
                            state <= NORM_REQ;
                        end
                    end
                end
                BIAS_REQ: state <= BIAS_LOAD;
                BIAS_LOAD: begin
                    if (!rom_valid_a) begin
                        error_stage <= 3'd4;
                        state <= FINISH;
                    end else begin
                        accumulator <= $signed({{36{rom_a[31]}}, rom_a}) <<< 20;
                        index <= 4'd0;
                        state <= WEIGHT_REQ;
                    end
                end
                WEIGHT_REQ: state <= MAC_MULT;
                MAC_MULT: begin
                    if (!rom_valid_a) begin
                        error_stage <= 3'd4;
                        state <= FINISH;
                    end else begin
                        product_reg <= multiply_result;
                        state <= MAC_ADD;
                    end
                end
                MAC_ADD: begin
                    if ((product_reg[64] != product_reg[63]) || (extended_sum[68] != extended_sum[67])) begin
                        overflow <= 1'b1;
                        error_stage <= second_layer ? 3'd3 : 3'd2;
                        state <= FINISH;
                    end else begin
                        accumulator <= extended_sum[67:0];
                        if (index == (second_layer ? 4'd7 : 4'd11))
                            state <= LAYER_ROUND;
                        else begin
                            index <= index + 4'd1;
                            state <= WEIGHT_REQ;
                        end
                    end
                end
                LAYER_ROUND: begin
                    trace_valid <= 1'b1;
                    trace_stage <= second_layer ? 2'd3 : 2'd2;
                    trace_index <= {1'b0, neuron};
                    trace_value <= accumulator;
                    if (!fits_signed32(rounded)) begin
                        overflow <= 1'b1;
                        error_stage <= second_layer ? 3'd3 : 3'd2;
                        state <= FINISH;
                    end else if (second_layer) begin
                        logits[neuron[1:0]] <= rounded[31:0];
                        if (neuron == 3'd3) state <= ARG_INIT;
                        else begin
                            neuron <= neuron + 3'd1;
                            state <= BIAS_REQ;
                        end
                    end else begin
                        pre_activation[neuron] <= rounded[31:0];
                        hidden[neuron] <= rounded[48] ? 32'sd0 : rounded[31:0];
                        if (neuron == 3'd7) begin
                            second_layer <= 1'b1;
                            neuron <= 3'd0;
                        end else neuron <= neuron + 3'd1;
                        state <= BIAS_REQ;
                    end
                end
                ARG_INIT: begin
                    best_index <= 2'd0;
                    best_logit <= logits[0];
                    arg_index <= 2'd1;
                    state <= ARG_SCAN;
                end
                ARG_SCAN: begin
                    if ($signed(logits[arg_index]) > $signed(best_logit)) begin
                        best_index <= arg_index;
                        best_logit <= logits[arg_index];
                    end
                    if (arg_index == 2'd3) state <= FINISH;
                    else arg_index <= arg_index + 2'd1;
                end
                FINISH: begin
                    done <= 1'b1;
                    valid <= (error_stage == 3'd0);
                    class_id <= (error_stage == 3'd0) ? best_index : 2'd0;
                    state <= IDLE;
                end
                default: begin
                    error_stage <= 3'd4;
                    valid <= 1'b0;
                    state <= FINISH;
                end
            endcase
        end
    end
endmodule
