`timescale 1ns/1ps
// Phase3C count-domain contract v1: input integer signed16, output signed96 F32.
// Not an adapter to the trained model's amplitude units or Q12.20 inputs.
module ecg_feature_core (
    input logic clk, rst_n, abort, start,
    output wire start_ready, busy,
    input logic frame_valid, frame_fault, frame_abort,
    input wire [31:0] frame_id, beat_index_360, rr_curr_ticks_360, rr_prev_ticks_360,
    output wire rd_req_valid,
    input logic rd_req_ready,
    output wire [8:0] rd_req_addr,
    input logic rd_rsp_valid,
    output wire rd_rsp_ready,
    input wire signed [15:0] rd_rsp_data,
    input wire [8:0] rd_rsp_addr,
    input logic rd_rsp_error,
    output wire frame_release_valid,
    input logic frame_release_ready,
    output wire result_valid,
    input logic result_ready,
    output logic signed [95:0] features [0:11],
    output logic [31:0] result_frame_id, result_beat_index_360,
    output logic done,
    output logic [2:0] error_code,
    output wire flush_required
);
    typedef enum logic [3:0] {IDLE,REQ,WAIT_RSP,SETUP,MATH_START,MATH_WAIT,
                              ROOT_START,ROOT_WAIT,RESULT,RELEASE_FRAME,FAULT} state_t;
    state_t state;
    logic [8:0] index;
    logic [3:0] job;
    logic signed [24:0] sum;
    logic [38:0] sum_squares;
    logic [37:0] half1_squares,half2_squares;
    logic [15:0] peak;
    logic signed [15:0] minimum,maximum;
    logic [1:0] previous_sign;
    logic [8:0] zero_changes;
    logic [31:0] rr_current,rr_previous;
    logic [95:0] roots [0:2];
    logic [191:0] math_num,math_den,math_q,math_rem,division_rem;
    logic [8:0] root_den;
    wire math_busy,math_done,math_error;
    wire canceled = abort || frame_fault || frame_abort || !frame_valid;
    wire active = (state!=IDLE && state!=FAULT);
    wire math_start = !canceled && (state==MATH_START || state==ROOT_START);
    wire math_sqrt = state==ROOT_START;
    wire signed [16:0] extended_sample = {rd_rsp_data[15],rd_rsp_data};
    wire [16:0] magnitude = extended_sample<0 ? $unsigned(-extended_sample) : $unsigned(extended_sample);
    // Keep multiplication outside a self-determined signedness cast: an
    // input-width product would truncate 32768^2 before assignment widens it.
    wire [33:0] magnitude_square = magnitude * magnitude;
    wire [31:0] square = magnitude_square[31:0]; // <=2^30 for every signed16 input
    wire [1:0] sign_code = rd_rsp_data==0 ? 2'd0 : (rd_rsp_data<0 ? 2'd2 : 2'd1);
    wire [24:0] abs_sum = sum<0 ? $unsigned(-sum) : $unsigned(sum);
    wire [49:0] squared_sum = abs_sum * abs_sum;
    wire [16:0] peak_to_peak = $unsigned({maximum[15],maximum} - {minimum[15],minimum});
    logic [192:0] rounded_div;
    logic [191:0] root_left,root_right;
    logic [96:0] rounded_root;
    logic [95:0] rms_output;
    integer k;

    assign busy = state!=IDLE;
    assign start_ready = rst_n && state==IDLE && !canceled;
    assign rd_req_valid = rst_n && state==REQ && !canceled;
    assign rd_req_addr = index;
    assign rd_rsp_ready = rst_n && state==WAIT_RSP && !canceled;
    assign result_valid = rst_n && state==RESULT && !canceled;
    assign frame_release_valid = rst_n && state==RELEASE_FRAME && !canceled;
    assign flush_required = rst_n && state==FAULT;

    always_comb begin
        rounded_div = {1'b0,math_q};
        if (({1'b0,math_rem}<<1) > {1'b0,math_den} ||
            (({1'b0,math_rem}<<1)=={1'b0,math_den} && math_q[0]))
            rounded_div = rounded_div+1'b1;
        root_left = ((math_rem * 192'(root_den))+division_rem)<<2;
        root_right = 192'(root_den)*((math_q<<2)+192'd1);
        rounded_root = {1'b0,math_q[95:0]};
        if (root_left>root_right || (root_left==root_right && math_q[0]))
            rounded_root = rounded_root+1'b1;
        rms_output = roots[0]>>16;
        if (roots[0][15:0]>16'h8000 || (roots[0][15:0]==16'h8000 && roots[0][16]))
            rms_output = rms_output+1'b1;
    end
    ecg_feature_math arithmetic (
        .clk(clk),.rst_n(rst_n),.abort(abort || (active && canceled)),
        .start(math_start),.sqrt_op(math_sqrt),.numerator(math_num),.denominator(math_den),
        .busy(math_busy),.done(math_done),.error(math_error),.quotient(math_q),.remainder(math_rem)
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; index<=0;job<=0;sum<=0;sum_squares<=0;half1_squares<=0;half2_squares<=0;
            peak<=0;minimum<=0;maximum<=0;previous_sign<=0;zero_changes<=0;
            rr_current<=0;rr_previous<=0;math_num<=0;math_den<=0;division_rem<=0;root_den<=0;
            result_frame_id<=0;result_beat_index_360<=0;done<=0;error_code<=0;
            for (k=0;k<12;k=k+1) features[k]<='0;
            for (k=0;k<3;k=k+1) roots[k]<='0;
        end else begin
            done<=0;
            if (active && canceled) begin
                state<=FAULT;done<=(state!=RELEASE_FRAME);error_code<=3'd1;
            end else case (state)
                IDLE: if (start && start_ready) begin
                    result_frame_id<=frame_id;result_beat_index_360<=beat_index_360;
                    rr_current<=rr_curr_ticks_360;rr_previous<=rr_prev_ticks_360;
                    index<=0;job<=0;sum<=0;sum_squares<=0;half1_squares<=0;half2_squares<=0;
                    peak<=0;minimum<=0;maximum<=0;previous_sign<=0;zero_changes<=0;error_code<=0;
                    for (k=0;k<12;k=k+1) features[k]<='0;
                    state<=REQ;
                end
                REQ: if (rd_req_ready) state<=WAIT_RSP;
                WAIT_RSP: if (rd_rsp_valid) begin
                    if (rd_rsp_error || rd_rsp_addr!=index) begin
                        error_code<=3'd2;done<=1;state<=FAULT;
                    end else begin
                        sum<=sum+{{9{rd_rsp_data[15]}},rd_rsp_data};
                        sum_squares<=sum_squares+{7'b0,square};
                        if (index<9'd173) half1_squares<=half1_squares+{6'b0,square};
                        else half2_squares<=half2_squares+{6'b0,square};
                        if (magnitude>{1'b0,peak}) peak<=magnitude[15:0];
                        if (index==0 || rd_rsp_data<minimum) minimum<=rd_rsp_data;
                        if (index==0 || rd_rsp_data>maximum) maximum<=rd_rsp_data;
                        if (index!=0 && sign_code!=previous_sign) zero_changes<=zero_changes+1'b1;
                        previous_sign<=sign_code;
                        if (index==9'd346) state<=SETUP;
                        else begin index<=index+1'b1;state<=REQ;end
                    end
                end
                SETUP: begin
                    state<=MATH_START;
                    case (job)
                        0: begin math_num<=192'(sum_squares)<<96;math_den<=192'd347;root_den<=347;end
                        1: begin math_num<=192'(half1_squares)<<96;math_den<=192'd173;root_den<=173;end
                        2: begin math_num<=192'(half2_squares)<<96;math_den<=192'd174;root_den<=174;end
                        3: begin
                            math_num<=((192'(sum_squares)*192'd347)-192'(squared_sum))<<32;
                            math_den<=192'd120409;
                            features[0]<=$signed(rms_output);
                            features[2]<=$signed(96'(peak)<<32);
                            features[4]<=$signed(96'(peak_to_peak)<<32);
                            features[7]<=96'(maximum)<<<32;
                        end
                        4: begin math_num<=192'(zero_changes)<<32;math_den<=192'd347;end
                        5: begin math_num<=(192'(peak)*192'd1000000000)<<80;
                                 math_den<=192'(roots[0])*192'd1000000000+(192'd1<<48);end
                        6: begin math_num<=(192'(roots[1])*192'd1000000000)<<32;
                                 math_den<=192'(roots[2])*192'd1000000000+(192'd1<<48);end
                        7: begin math_num<=192'(rr_current)<<32;math_den<=192'd360;end
                        8: begin math_num<=192'(rr_previous)<<32;math_den<=192'd360;end
                        9: begin math_num<=(192'(rr_current)*192'd1000000000)<<32;
                                 math_den<=192'(rr_previous)*192'd1000000000+192'd360;end
                        10: begin math_num<=192'((rr_current>=rr_previous)?rr_current-rr_previous:rr_previous-rr_current)<<32;
                                  math_den<=192'd360;end
                        default: begin state<=FAULT;done<=1;error_code<=3'd3;end
                    endcase
                end
                MATH_START: if (!math_busy) state<=MATH_WAIT;
                MATH_WAIT: if (math_done) begin
                    if (math_error) begin state<=FAULT;done<=1;error_code<=3'd3;end
                    else if (job<3) begin
                        division_rem<=math_rem;math_num<=math_q;state<=ROOT_START;
                    end else if (|rounded_div[192:95]) begin state<=FAULT;done<=1;error_code<=3'd3;end
                    else begin
                        case (job)
                            3: features[1]<=$signed(rounded_div[95:0]);
                            4: features[3]<=$signed(rounded_div[95:0]);
                            5: features[5]<=rounded_div>(193'd15<<32) ? (96'sd15<<32) : $signed(rounded_div[95:0]);
                            6: features[6]<=$signed(rounded_div[95:0]);
                            7: features[8]<=$signed(rounded_div[95:0]);
                            8: features[9]<=$signed(rounded_div[95:0]);
                            9: features[10]<=$signed(rounded_div[95:0]);
                            10: features[11]<=rr_current<rr_previous ? -$signed(rounded_div[95:0]) : $signed(rounded_div[95:0]);
                            default: begin end
                        endcase
                        if (job==10) state<=RESULT;
                        else begin job<=job+1'b1;state<=SETUP;end
                    end
                end
                ROOT_START: if (!math_busy) state<=ROOT_WAIT;
                ROOT_WAIT: if (math_done) begin
                    if (math_error || |math_q[191:96] || rounded_root[96]) begin
                        state<=FAULT;done<=1;error_code<=3'd3;
                    end else begin roots[job]<=rounded_root[95:0];job<=job+1'b1;state<=SETUP;end
                end
                RESULT: if (result_ready) begin state<=RELEASE_FRAME;done<=1;end
                RELEASE_FRAME: if (frame_release_ready) state<=IDLE;
                FAULT: if (!frame_valid && !frame_fault && !frame_abort && !abort) state<=IDLE;
                default: begin state<=FAULT;done<=1;error_code<=3'd3;end
            endcase
        end
    end
endmodule
