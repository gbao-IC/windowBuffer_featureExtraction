`timescale 1ns/1ps
module tb_ecg_mlp #(
    parameter MODEL_FILE = "tests/vectors/model_q12_20.hex"
);
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, start = 0;
    logic signed [31:0] features [0:11];
    logic ready, busy, valid, done, overflow;
    logic [2:0] error_stage;
    logic [1:0] class_id;
    logic signed [31:0] normalized [0:11], pre_activation [0:7], hidden [0:7], logits [0:3];
    logic trace_valid;
    logic [1:0] trace_stage;
    logic [3:0] trace_index;
    logic signed [67:0] trace_value;
    logic [67:0] expected [0:965]; // maximum 14 x 69; shorter suites use a bounded read
    string vectors;
    integer case_count, expect_error, exercise_protocol;
    integer active_case = 0;
    integer cycles = 0, accepted = 0, completed = 0, aborted = 0, accept_cycle = 0;
    integer last_latency = 0;
    bit pending = 0, previous_done = 0;
    bit [11:0] norm_seen = 0;
    bit [7:0] fc1_seen = 0;
    bit [3:0] fc2_seen = 0, class_coverage = 0;
    ecg_mlp_core #(.MODEL_FILE(MODEL_FILE)) dut (.*);

    // Observe request at the accepting edge, response after NBA updates.
    always @(posedge clk) begin : scoreboard
        integer base;
        cycles = cycles + 1;
        if (!rst_n) begin
            if (pending) aborted = aborted + 1;
            pending = 0;
            previous_done = 0;
            norm_seen = 0; fc1_seen = 0; fc2_seen = 0;
        end else begin
            if (start && ready) begin
                if (pending) $fatal(1, "FAIL accepted while busy");
                accepted = accepted + 1;
                pending = 1;
                accept_cycle = cycles;
                norm_seen = 0; fc1_seen = 0; fc2_seen = 0;
            end
            #1;
            base = active_case * 69;
            if (ready && busy) $fatal(1, "FAIL ready and busy overlap");
            if (busy && valid) $fatal(1, "FAIL stale valid while computing");
            if (previous_done && done) $fatal(1, "FAIL done wider than one cycle");
            previous_done = done;
            if (trace_valid && expect_error == 0) begin
                if (!pending) $fatal(1, "FAIL trace without request");
                case (trace_stage)
                    1: begin
                        if (trace_index >= 12 || norm_seen[trace_index]) $fatal(1, "FAIL duplicate/invalid normalizer trace");
                        if (trace_value !== expected[base+12+int'(trace_index)])
                            $fatal(1, "FAIL norm product case=%0d index=%0d actual=%h expected=%h", active_case, trace_index, trace_value, expected[base+12+int'(trace_index)]);
                        norm_seen[trace_index] = 1;
                    end
                    2: begin
                        if (trace_index >= 8 || fc1_seen[trace_index[2:0]]) $fatal(1, "FAIL duplicate/invalid FC1 trace");
                        if (trace_value !== expected[base+36+int'(trace_index)]) $fatal(1, "FAIL FC1 accumulator case=%0d neuron=%0d", active_case, trace_index);
                        fc1_seen[trace_index[2:0]] = 1;
                    end
                    3: begin
                        if (trace_index >= 4 || fc2_seen[trace_index[1:0]]) $fatal(1, "FAIL duplicate/invalid FC2 trace");
                        if (trace_value !== expected[base+60+int'(trace_index)]) $fatal(1, "FAIL FC2 accumulator case=%0d neuron=%0d", active_case, trace_index);
                        fc2_seen[trace_index[1:0]] = 1;
                    end
                    default: $fatal(1, "FAIL invalid trace stage");
                endcase
            end
            if (done) begin
                if (!pending) $fatal(1, "FAIL unsolicited/duplicate completion");
                pending = 0;
                completed = completed + 1;
                last_latency = cycles - accept_cycle;
                if (expect_error != 0) begin
                    if (valid !== 0 || overflow !== 1 || error_stage !== 3'(expect_error) || class_id !== 0)
                        $fatal(1, "FAIL overflow response stage=%0d actual=%0d", expect_error, error_stage);
                    if (last_latency != (expect_error == 1 ? 13 : expect_error == 2 ? 76 : 376))
                        $fatal(1, "FAIL overflow latency %0d", last_latency);
                end else begin
                    if (valid !== 1 || overflow !== 0 || error_stage !== 0) $fatal(1, "FAIL response flags");
                    if (last_latency != 461) $fatal(1, "FAIL latency expected=461 actual=%0d", last_latency);
                    if (norm_seen !== 12'hfff || fc1_seen !== 8'hff || fc2_seen !== 4'hf)
                        $fatal(1, "FAIL incomplete intermediate trace");
                    for (int i = 0; i < 12; i++)
                        if (normalized[i] !== expected[base+24+i][31:0]) $fatal(1, "FAIL normalized case=%0d index=%0d", active_case, i);
                    for (int i = 0; i < 8; i++) begin
                        if (pre_activation[i] !== expected[base+44+i][31:0]) $fatal(1, "FAIL pre-activation case=%0d index=%0d", active_case, i);
                        if (hidden[i] !== expected[base+52+i][31:0]) $fatal(1, "FAIL hidden case=%0d index=%0d", active_case, i);
                    end
                    for (int i = 0; i < 4; i++)
                        if (logits[i] !== expected[base+64+i][31:0]) $fatal(1, "FAIL logits case=%0d index=%0d", active_case, i);
                    if (class_id !== expected[base+68][1:0]) $fatal(1, "FAIL class case=%0d", active_case);
                    class_coverage[class_id] = 1;
                end
                $display("PASS inference case=%0d class=%0d error_stage=%0d cycles=%0d", active_case, class_id, error_stage, last_latency);
            end
        end
    end

    task automatic launch(input integer case_id);
        @(negedge clk);
        if (ready !== 1) $fatal(1, "FAIL not ready for new request");
        active_case = case_id;
        for (int i = 0; i < 12; i++) features[i] = expected[case_id*69+i][31:0];
        start = 1;
        @(posedge clk); #2;
        if (busy !== 1 || ready !== 0 || valid !== 0 || done !== 0) $fatal(1, "FAIL acceptance handshake");
        if (overflow !== 0 || error_stage !== 0 || class_id !== 0) $fatal(1, "FAIL stale error/class on acceptance");
    endtask

    task automatic run_case(input integer case_id, input bit hold_start);
        integer waited;
        logic [1:0] held_class;
        launch(case_id);
        waited = 0;
        do begin
            @(negedge clk);
            waited = waited + 1;
            // Input payload changes after acceptance. Busy requests must be ignored.
            start = hold_start || (waited == 5) || (waited == 6);
            for (int i = 0; i < 12; i++) features[i] = 32'hdeadbeef ^ 32'(i + waited);
            @(posedge clk); #2;
            if (waited > 500) $fatal(1, "FAIL inference timeout");
        end while (!done);
        if (hold_start) begin
            held_class = class_id;
            repeat (8) begin
                @(posedge clk); #2;
                if (ready !== 0 || busy !== 0 || done !== 0 || class_id !== held_class || valid !== 1)
                    $fatal(1, "FAIL held start retrigger/result stability");
            end
            @(negedge clk); start = 0;
            @(posedge clk); #2;
            if (ready !== 1 || valid !== 1) $fatal(1, "FAIL start rearm");
        end
    endtask

    task automatic reset_in_state(input integer target_state);
        integer waited;
        launch(0);
        waited = 0;
        while (int'(dut.state) != target_state) begin
            @(negedge clk); start = 0;
            @(posedge clk); #2;
            waited = waited + 1;
            if (waited > 500 || done) $fatal(1, "FAIL state not reached for reset %0d", target_state);
        end
        @(negedge clk); rst_n = 0; start = 0;
        #1;
        if (ready !== 0 || busy !== 0 || valid !== 0 || done !== 0 || overflow !== 0 || error_stage !== 0 || class_id !== 0)
            $fatal(1, "FAIL asynchronous reset state=%0d", target_state);
        for (int i = 0; i < 12; i++) if (normalized[i] !== 0) $fatal(1, "FAIL reset normalized");
        for (int i = 0; i < 8; i++) if (hidden[i] !== 0 || pre_activation[i] !== 0) $fatal(1, "FAIL reset FC1");
        for (int i = 0; i < 4; i++) if (logits[i] !== 0) $fatal(1, "FAIL reset logits");
        repeat (2) @(negedge clk);
        rst_n = 1;
        @(posedge clk); #2;
        if (ready !== 1 || done !== 0 || valid !== 0) $fatal(1, "FAIL reset release");
        run_case(target_state % case_count, 0);
        $display("PASS reset_abort_and_recovery state=%0d", target_state);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "FAIL missing VECTORS");
        if (!$value$plusargs("CASES=%d", case_count)) $fatal(1, "FAIL missing CASES");
        if (!$value$plusargs("ERROR_STAGE=%d", expect_error)) expect_error = 0;
        if (!$value$plusargs("PROTOCOL=%d", exercise_protocol)) exercise_protocol = 0;
        if (case_count < 1 || case_count > 14) $fatal(1, "FAIL case count");
        $readmemh(vectors, expected, 0, (case_count + (expect_error != 0 ? 1 : 0))*69-1);
        for (int i = 0; i < 12; i++) features[i] = 0;
        repeat (3) @(negedge clk);
        if (ready !== 0 || done !== 0 || valid !== 0) $fatal(1, "FAIL power-on reset");
        rst_n = 1;
        @(posedge clk); #2;
        if (ready !== 1) $fatal(1, "FAIL ready after reset");
        for (int c = 0; c < case_count; c++) run_case(c, 0);
        // Immediate next request, no extra idle cycle; repeated feature payloads.
        run_case(0, 0);
        run_case(case_count-1, 0);
        if (expect_error != 0) begin
            expect_error = 0;
            run_case(case_count, 0);
            $display("PASS successful_recovery_after_overflow_without_reset");
        end
        if (exercise_protocol != 0) begin
            if (class_coverage !== 4'hf) $fatal(1, "FAIL four predicted classes not covered");
            run_case(0, 1);
            for (int s = 1; s <= 12; s++) reset_in_state(s);
            if (aborted != 12) $fatal(1, "FAIL reset abort accounting");
        end
        repeat (5) begin
            @(posedge clk); #2;
            if (done !== 0 || busy !== 0) $fatal(1, "FAIL extra completion");
        end
        if (accepted != completed + aborted || pending) $fatal(1, "FAIL transaction accounting");
        $display("PASS MLP suite cases=%0d completed=%0d aborted=%0d accepted=%0d class_mask=%h mismatches=0", case_count, completed, aborted, accepted, class_coverage);
        $finish;
    end
    initial begin #2000000; $fatal(1, "FAIL global timeout"); end
endmodule
