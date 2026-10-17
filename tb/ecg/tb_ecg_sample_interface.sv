`timescale 1ns/1ps
module tb_ecg_sample_interface #(
    parameter bit PULSE_MODE = 1'b0
);
    logic clk = 1'b0;
    always #10 clk = ~clk; // Logical simulation at 50 MHz; not timing closure.
    logic rst_n = 1'b1;
    logic signed [15:0] input_sample = 16'sd0;
    logic input_valid = 1'b0, output_ready = 1'b0, upstream_loss = 1'b0;
    wire input_ready, output_valid, overflow_pulse, overflow_flag;
    wire signed [15:0] output_sample;
    generate
        if (PULSE_MODE) begin : pulse_source
            ecg_sample_pulse_adapter dut (
                .clk(clk), .rst_n(rst_n), .arrival_sample(input_sample),
                .arrival_valid(input_valid), .arrival_ready(input_ready),
                .sample_out(output_sample), .sample_out_valid(output_valid),
                .sample_out_ready(output_ready), .overflow_pulse(overflow_pulse),
                .overflow_flag(overflow_flag)
            );
        end else begin : replay_source
            ecg_sample_interface dut (
                .clk(clk), .rst_n(rst_n), .sample_in(input_sample),
                .sample_valid(input_valid), .sample_ready(input_ready),
                .sample_out(output_sample), .sample_out_valid(output_valid),
                .sample_out_ready(output_ready), .source_overflow(upstream_loss),
                .overflow_pulse(overflow_pulse), .overflow_flag(overflow_flag)
            );
        end
    endgenerate

    // Transaction queue is independent of the DUT's register implementation.
    shortint signed expected[$];
    shortint signed head_value;
    integer accepted = 0, delivered = 0, dropped = 0, aborted = 0;
    integer simultaneous = 0, stalls = 0, loss_events = 0, checks = 0;
    bit expected_sticky = 0, edge_loss;
    bit was_input_stalled = 0;
    logic signed [15:0] stalled_input;
    bit [7:0] occupancy_valid_ready_coverage = 0;
    bit [65535:0] word_coverage = '0;
    bit signed_min_seen = 0, signed_max_seen = 0, zero_seen = 0;
    bit accepted_this_cycle;
    logic [31:0] rng = 32'h3a16cafe;
    integer i, accepted_before, delivered_before, dropped_before;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aborted += expected.size();
            expected.delete();
            expected_sticky = 0;
            was_input_stalled = 0;
            #1;
            if ({input_ready, output_valid, overflow_pulse, overflow_flag} !== 4'b0000 ||
                output_sample !== 16'sd0) $fatal(1, "FAIL reset outputs");
        end else begin
            checks++;
            if (input_ready !== ((expected.size() == 0) || output_ready))
                $fatal(1, "FAIL ready contract");
            if (output_valid !== (expected.size() != 0)) $fatal(1, "FAIL unexpected valid");
            if (!PULSE_MODE && was_input_stalled &&
                (!input_valid || input_sample !== stalled_input))
                $fatal(1, "FAIL test producer violated ready/valid protocol");
            occupancy_valid_ready_coverage[{(expected.size() != 0), input_valid, output_ready}] = 1'b1;
            if (output_valid && output_ready && input_valid && input_ready) simultaneous++;
            if (output_valid && !output_ready) stalls++;
            if (output_valid && output_ready) begin
                head_value = expected.pop_front();
                if (output_sample !== head_value) $fatal(1, "FAIL reordered/corrupt output got=%h expected=%h", output_sample, head_value);
                delivered++;
                word_coverage[$unsigned(output_sample)] = 1'b1;
                if ($signed(output_sample) == -32768) signed_min_seen = 1;
                if ($signed(output_sample) == 32767) signed_max_seen = 1;
                if ($signed(output_sample) == 0) zero_seen = 1;
            end
            if (input_valid && input_ready) begin
                expected.push_back(input_sample);
                accepted++;
            end
            edge_loss = PULSE_MODE ? (input_valid && !input_ready) : upstream_loss;
            if (PULSE_MODE && edge_loss) dropped++;
            if (edge_loss) begin expected_sticky = 1; loss_events++; end
            was_input_stalled = input_valid && !input_ready;
            stalled_input = input_sample;
            #1;
            if (expected.size() > 1) $fatal(1, "FAIL scoreboard capacity");
            if (output_valid !== (expected.size() != 0)) $fatal(1, "FAIL registered latency/valid");
            if (expected.size() != 0 && output_sample !== expected[0])
                $fatal(1, "FAIL pending payload changed/lost during stall");
            if (overflow_pulse !== edge_loss || overflow_flag !== expected_sticky)
                $fatal(1, "FAIL overflow pulse/sticky");
        end
    end

    task automatic cycle(input bit valid_value, input logic signed [15:0] value,
                         input bit ready_value, input bit loss_value = 0);
        @(negedge clk);
        input_valid = valid_value;
        input_sample = value;
        output_ready = ready_value;
        upstream_loss = loss_value;
        @(posedge clk);
        accepted_this_cycle = input_valid && input_ready;
        #2;
    endtask

    task automatic reset_now;
        // Deliberately assert between clock edges; pending data must be aborted.
        #3 rst_n = 0;
        #2;
        if (output_valid !== 0 || input_ready !== 0 || overflow_flag !== 0)
            $fatal(1, "FAIL asynchronous reset");
        @(negedge clk);
        input_valid = 0; input_sample = 0; output_ready = 0; upstream_loss = 0;
        repeat (2) @(posedge clk);
        @(negedge clk); rst_n = 1;
        #2;
        if (input_ready !== 1 || output_valid !== 0) $fatal(1, "FAIL reset release");
    endtask

    initial begin
        reset_now();
        cycle(0, 16'sd0, 0);
        cycle(0, 16'sd0, 1);
        cycle(1, 16'sh8000, 0);
        cycle(0, 16'sd0, 0); // Hold queued sample despite irrelevant input change.
        repeat (8) cycle(1, 16'sh7fff, 0); // Legal held valid OR repeated pulse arrivals.
        cycle(1, 16'sh7fff, 1); // Forward old + accept new on the same edge.
        cycle(1, -16'sd1, 1);
        cycle(1, 16'sd0, 1);
        cycle(0, 16'sd0, 1);
        if (!PULSE_MODE && overflow_flag !== 0) $fatal(1, "FAIL legal stall reported loss");
        if (PULSE_MODE && dropped != 8) $fatal(1, "FAIL expected eight dropped new arrivals");

        // Reset while a sample and a stalled offer are present.
        cycle(1, -16'sd12345, 0);
        cycle(1, 16'sd12345, 0);
        reset_now();
        cycle(0, 16'sd0, 1);
        if (!PULSE_MODE) begin
            cycle(0, 16'sd0, 1, 1); // Upstream loss independent of data valid.
            cycle(1, -16'sd257, 1, 1);
            cycle(0, 16'sd0, 1, 0);
            if (overflow_flag !== 1) $fatal(1, "FAIL upstream sticky loss");
            reset_now();
        end

        // Exhaustive bit integrity: all signed16 encodings, continuous valid.
        accepted_before = accepted; delivered_before = delivered; dropped_before = dropped;
        for (i = 0; i < 65536; i++) cycle(1, 16'(i), 1);
        cycle(0, 16'sd0, 1);
        if (accepted - accepted_before != 65536 || delivered - delivered_before != 65536 || dropped != dropped_before)
            $fatal(1, "FAIL gapless throughput / sample loss");
        if (&word_coverage !== 1'b1) $fatal(1, "FAIL signed16 coverage");
        $display("PASS exhaustive signed16 words=65536 one_sample_per_clock mode=%0d", PULSE_MODE);

        // Deterministic source and sink stalls, with a contract-respecting Replay.
        for (i = 0; i < 10000; i++) begin
            rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
            if (!PULSE_MODE && input_valid && !accepted_this_cycle)
                cycle(1, input_sample, rng[0]);
            else
                cycle(rng[1], $signed(rng[31:16]), rng[0]);
        end
        if (!PULSE_MODE && input_valid && !accepted_this_cycle) cycle(1, input_sample, 1);
        cycle(0, 16'sd0, 1);
        cycle(0, 16'sd0, 1);
        if (expected.size() != 0 || accepted != delivered + aborted)
            $fatal(1, "FAIL transaction conservation");
        if (occupancy_valid_ready_coverage !== 8'hff || simultaneous == 0 || stalls == 0 ||
            !signed_min_seen || !signed_max_seen || !zero_seen || loss_events == 0)
            $fatal(1, "FAIL required coverage");
        reset_now();
        cycle(1, -16'sd30000, 1); cycle(0, 16'sd0, 1);
        if (overflow_flag !== 0 || output_valid !== 0) $fatal(1, "FAIL post-reset recovery");
        $display("PASS ECG_SAMPLE mode=%0d accepted=%0d delivered=%0d aborted=%0d dropped=%0d loss_events=%0d simultaneous=%0d stalls=%0d checks=%0d coverage=%h mismatches=0",
                 PULSE_MODE, accepted, delivered, aborted, dropped, loss_events, simultaneous, stalls, checks, occupancy_valid_ready_coverage);
        $finish;
    end
    initial begin #5000000; $fatal(1, "FAIL timeout"); end
endmodule
