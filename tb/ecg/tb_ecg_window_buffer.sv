`timescale 1ns/1ps
module tb_ecg_window_buffer #(
    parameter int N = 347,
    parameter int LINK_MODE = 0 // 0=direct, 1=Phase3A Replay, 2=Phase3A pulse
);
    localparam int AW = (N > 1) ? $clog2(N) : 1;
    localparam int CW = $clog2(N + 1);
    logic clk = 0, rst_n = 1, flush = 0, inject_loss = 0;
    always #10 clk = ~clk;
    logic start_valid = 0, release_valid = 0;
    wire start_ready, release_ready, frame_valid, fault, loss_flag, frame_abort;
    logic [31:0] tag = 0, beat = 0, rr = 0, prev_rr = 0;
    wire [31:0] out_tag, out_beat, out_rr, out_prev_rr;
    wire [CW-1:0] collected;
    logic signed [15:0] src_data = 0;
    logic src_valid = 0;
    wire src_ready, sample_ready, sample_valid;
    wire signed [15:0] sample_data;
    wire adapter_loss, adapter_sticky;
    wire source_loss = inject_loss || adapter_loss;
    wire front_rst_n = rst_n && !flush; // Test caller flushes its queued input too.
    logic req_valid = 0, rsp_ready = 0;
    logic [AW-1:0] req_addr = 0;
    wire req_ready, rsp_valid, rsp_error;
    wire [AW-1:0] rsp_addr;
    wire signed [15:0] rsp_data;
    generate
        if (LINK_MODE == 0) begin : direct_link
            assign sample_data = src_data;
            assign sample_valid = src_valid;
            assign src_ready = sample_ready;
            assign adapter_loss = 0;
            assign adapter_sticky = 0;
        end else if (LINK_MODE == 1) begin : replay_link
            ecg_sample_interface front (
                .clk(clk), .rst_n(front_rst_n), .sample_in(src_data), .sample_valid(src_valid),
                .sample_ready(src_ready), .sample_out(sample_data), .sample_out_valid(sample_valid),
                .sample_out_ready(sample_ready), .source_overflow(1'b0),
                .overflow_pulse(adapter_loss), .overflow_flag(adapter_sticky)
            );
        end else begin : pulse_link
            ecg_sample_pulse_adapter front (
                .clk(clk), .rst_n(front_rst_n), .arrival_sample(src_data), .arrival_valid(src_valid),
                .arrival_ready(src_ready), .sample_out(sample_data), .sample_out_valid(sample_valid),
                .sample_out_ready(sample_ready), .overflow_pulse(adapter_loss), .overflow_flag(adapter_sticky)
            );
        end
    endgenerate
    ecg_window_buffer #(.FRAME_SAMPLES(N)) dut (
        .clk(clk), .rst_n(rst_n), .flush(flush), .source_loss(source_loss),
        .frame_start_valid(start_valid), .frame_start_ready(start_ready),
        .in_frame_id(tag), .in_beat_index_360(beat), .in_rr_curr_ticks_360(rr), .in_rr_prev_ticks_360(prev_rr),
        .sample_in(sample_data), .sample_valid(sample_valid), .sample_ready(sample_ready),
        .frame_valid(frame_valid), .frame_id(out_tag), .beat_index_360(out_beat),
        .rr_curr_ticks_360(out_rr), .rr_prev_ticks_360(out_prev_rr), .samples_collected(collected),
        .frame_release_valid(release_valid), .frame_release_ready(release_ready),
        .rd_req_valid(req_valid), .rd_req_ready(req_ready), .rd_req_addr(req_addr),
        .rd_rsp_valid(rsp_valid), .rd_rsp_ready(rsp_ready), .rd_rsp_data(rsp_data),
        .rd_rsp_addr(rsp_addr), .rd_rsp_error(rsp_error),
        .fault(fault), .loss_flag(loss_flag), .frame_abort(frame_abort)
    );

    // Reference is an ordered list of accepted samples plus a transaction queue.
    shortint signed frame_words[$];
    typedef struct packed {
        logic [AW-1:0] address;
        logic signed [15:0] value;
        bit error;
    } response_t;
    response_t responses[$], entry;
    bit active = 0, poisoned = 0, expect_abort;
    logic [127:0] metadata = 0;
    integer cycles = 0, last_write_cycle = -1, frames = 0, released = 0;
    integer writes = 0, reads = 0, replies = 0, bad_reads = 0, aborts = 0;
    integer stalled_writes = 0, stalled_responses = 0, read_write_attempts = 0;
    integer seen_first = 0, seen_last = 0, loss_events = 0;
    bit accepted_src, accepted_req, accepted_rsp, accepted_start, accepted_release;
    logic [31:0] rng = 32'h3b347500;
    integer i, j, before_reads;

    function automatic logic signed [15:0] synthetic(input int frame_number, input int position);
        int phase, value;
        begin
            // Integer triangular ECG-like shape + distinct per-frame perturbation.
            // Extremes at endpoints intentionally test storage, not physiology.
            phase = position * 347 / N;
            value = (position % 23) - 11 + frame_number * 7;
            if (phase >= 40 && phase < 70) value += (15 - ((phase > 55) ? phase-55 : 55-phase)) * 40;
            if (phase >= 160 && phase < 185) value += (13 - ((phase > 173) ? phase-173 : 173-phase)) * 500;
            if (phase >= 185 && phase < 200) value -= (200-phase) * 100;
            if (phase >= 235 && phase < 275) value += (20 - ((phase > 255) ? phase-255 : 255-phase)) * 70;
            if (frame_number & 1) value = -value;
            if (position == 0) value = -32768;
            if (position == N-1) value = 32767;
            synthetic = 16'(value);
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_words.delete(); responses.delete(); active = 0; poisoned = 0; metadata = 0;
            last_write_cycle = -1;
            #1;
            if ({start_ready, sample_ready, frame_valid, req_ready, rsp_valid, fault, loss_flag} !== 7'b0 || rsp_data !== 0)
                $fatal(1, "FAIL reset visible state");
        end else begin
            cycles++;
            expect_abort = 0;
            if (source_loss || flush) begin
                expect_abort = active;
                if (active) aborts++;
                if (source_loss) loss_events++;
                active = 0; poisoned = source_loss;
                frame_words.delete(); responses.delete(); last_write_cycle = -1;
                if (sample_ready || req_ready || start_ready || rsp_valid || frame_valid)
                    $fatal(1, "FAIL cancellation did not gate handshakes");
            end else begin
                if (sample_valid && !sample_ready) stalled_writes++;
                if (rsp_valid && !rsp_ready) stalled_responses++;
                if (sample_valid && req_valid && req_ready) read_write_attempts++;
                if (sample_ready && req_ready) $fatal(1, "FAIL single-bank write/read overlap");
                if (rsp_valid && rsp_ready) begin
                    if (responses.size() != 1) $fatal(1, "FAIL unsolicited read response");
                    entry = responses.pop_front();
                    if ({rsp_addr, rsp_data, rsp_error} !== entry) $fatal(1, "FAIL response data/order");
                    replies++;
                    if (!rsp_error && int'(rsp_addr) == 0) seen_first++;
                    if (!rsp_error && int'(rsp_addr) == N-1) seen_last++;
                end
                if (release_valid && release_ready) begin
                    if (responses.size() != 0 || !frame_valid) $fatal(1, "FAIL premature release");
                    active = 0; frame_words.delete(); released++; last_write_cycle = -1;
                end
                if (start_valid && start_ready) begin
                    if (active || poisoned) $fatal(1, "FAIL descriptor overwritten");
                    active = 1; frames++; frame_words.delete();
                    metadata = {tag, beat, rr, prev_rr};
                end
                if (sample_valid && sample_ready) begin
                    if (!active || frame_words.size() >= N) $fatal(1, "FAIL sample outside frame");
                    frame_words.push_back(sample_data); writes++;
                    if (frame_words.size() == N) last_write_cycle = cycles;
                end
                if (req_valid && req_ready) begin
                    if (frame_words.size() != N) $fatal(1, "FAIL partial frame read");
                    entry.address = req_addr;
                    entry.error = int'(req_addr) >= N;
                    entry.value = entry.error ? 16'sd0 : frame_words[int'(req_addr)];
                    responses.push_back(entry); reads++;
                    if (entry.error) bad_reads++;
                end
            end
            #1;
            if (fault !== poisoned || loss_flag !== poisoned || frame_abort !== expect_abort)
                $fatal(1, "FAIL loss/flush/abort status");
            if (collected !== CW'(frame_words.size())) $fatal(1, "FAIL sample count");
            if ({out_tag, out_beat, out_rr, out_prev_rr} !== metadata) $fatal(1, "FAIL metadata association");
            if (frame_valid !== (active && frame_words.size() == N && cycles > last_write_cycle && !source_loss && !flush))
                $fatal(1, "FAIL frame publication latency/completeness");
            if (rsp_valid !== (responses.size() == 1)) $fatal(1, "FAIL synchronous read response latency");
            if (responses.size() == 1 && {rsp_addr, rsp_data, rsp_error} !== responses[0])
                $fatal(1, "FAIL registered/stalled response changed");
        end
    end

    task automatic tick;
        @(posedge clk);
        accepted_src = src_valid && src_ready;
        accepted_req = req_valid && req_ready;
        accepted_rsp = rsp_valid && rsp_ready;
        accepted_start = start_valid && start_ready;
        accepted_release = release_valid && release_ready;
        #2;
    endtask
    task automatic idle_inputs;
        src_valid = 0; start_valid = 0; req_valid = 0; rsp_ready = 0; release_valid = 0; inject_loss = 0;
    endtask
    task automatic clean;
        @(negedge clk); idle_inputs(); flush = 1;
        tick();
        @(negedge clk); flush = 0;
        tick();
        if (!start_ready || fault || frame_valid || rsp_valid) $fatal(1, "FAIL flush recovery");
    endtask
    task automatic reset_now;
        #3 rst_n = 0;
        #2;
        if (frame_valid || rsp_valid || sample_ready || start_ready) $fatal(1, "FAIL async reset");
        @(negedge clk); idle_inputs(); flush = 0;
        repeat (2) tick();
        @(negedge clk); rst_n = 1;
        tick();
    endtask
    task automatic begin_frame(input int number);
        @(negedge clk);
        start_valid = 1; tag = 32'(number); beat = 32'(36000+number*500);
        rr = 32'(288+number); prev_rr = 32'(287+number);
        tick();
        if (!accepted_start || !sample_ready) $fatal(1, "FAIL start handshake");
        @(negedge clk); start_valid = 0;
        // The source fields are free to change after capture.
        tag = '1; beat = '1; rr = '1; prev_rr = '1;
    endtask
    task automatic send_words(input int number, input int count, input bit gaps);
        int index;
        begin
            index = 0;
            while (index < count) begin
                @(negedge clk);
                src_valid = 1; src_data = synthetic(number, index);
                tick();
                if (accepted_src) begin
                    index++;
                    if (gaps && (index % 7 == 0)) begin
                        @(negedge clk); src_valid = 0;
                        repeat (3) tick();
                    end
                end
            end
            @(negedge clk); src_valid = 0;
        end
    endtask
    task automatic fill_frame(input int number, input bit gaps);
        int waited;
        begin
            begin_frame(number); send_words(number, N, gaps);
            waited = 0;
            while (!frame_valid && waited < 10) begin tick(); waited++; end
            if (!frame_valid || collected != N) $fatal(1, "FAIL complete frame missing");
            if (sample_ready) $fatal(1, "FAIL full buffer accepts more samples");
        end
    endtask
    task automatic read_all(input bit backwards, input bit random_stall);
        int sent, got;
        begin
            sent = 0; got = 0;
            while (got < N) begin
                @(negedge clk);
                rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
                req_valid = sent < N;
                req_addr = AW'(backwards ? N-1-sent : sent);
                rsp_ready = !random_stall || rng[0];
                tick();
                if (accepted_req) sent++;
                if (accepted_rsp) got++;
            end
            @(negedge clk); req_valid = 0; rsp_ready = 0;
            tick();
            if (rsp_valid) $fatal(1, "FAIL extra response");
        end
    endtask
    task automatic release_frame;
        @(negedge clk); release_valid = 1;
        tick();
        if (!accepted_release || !start_ready || frame_valid) $fatal(1, "FAIL release");
        @(negedge clk); release_valid = 0;
    endtask
    task automatic assert_loss;
        @(negedge clk); inject_loss = 1;
        tick();
        if (!fault || !loss_flag || frame_valid || rsp_valid) $fatal(1, "FAIL poisoned frame exposed");
        @(negedge clk); inject_loss = 0;
        repeat (3) tick();
        if (start_ready || sample_ready || req_ready) $fatal(1, "FAIL silent recovery without flush");
        clean();
    endtask

    initial begin
        reset_now();
        // No header/no complete frame: cannot read uninitialized memory.
        @(negedge clk); req_valid = 1; req_addr = 0; rsp_ready = 1;
        repeat (3) tick();
        if (rsp_valid || req_ready) $fatal(1, "FAIL read before frame");
        @(negedge clk); req_valid = 0; rsp_ready = 0;
        fill_frame(1, 0);
        // Direct producer holds a next-frame sample while reads are requested.
        if (LINK_MODE == 0) begin @(negedge clk); src_valid = 1; src_data = -16'sd1234; end
        read_all(0, 0); read_all(1, 1);
        // Invalid address has a deterministic error response, no stale RAM data.
        @(negedge clk); req_valid = 1; req_addr = AW'(N); rsp_ready = 0;
        tick();
        if (!accepted_req || !rsp_valid || !rsp_error || rsp_data !== 0) $fatal(1, "FAIL invalid read address");
        @(negedge clk); req_valid = 0; release_valid = 1;
        repeat (5) begin tick(); if (release_ready) $fatal(1, "FAIL release with outstanding response"); end
        @(negedge clk); rsp_ready = 1;
        tick();
        if (accepted_release || !accepted_rsp) $fatal(1, "FAIL release discarded response");
        tick();
        if (!accepted_release || frame_valid) $fatal(1, "FAIL held release handshake");
        clean(); // Cancels the held extra source offer too.

        for (j = 0; j < 4; j++) begin
            fill_frame(j+2, 1); read_all(j[0], 1); release_frame();
        end
        // Partial fill stalls indefinitely; no guessed timeout/frame padding.
        begin_frame(20); send_words(20, (N > 1) ? N-1 : 0, 0);
        repeat (12) tick();
        if (frame_valid) $fatal(1, "FAIL incomplete frame published");
        assert_loss(); // Loss during CAPTURE.

        // Loss after final write but before publication (registered source loss).
        begin_frame(21); send_words(21, N, 0);
        if (LINK_MODE != 0) tick(); // Drain the last Phase3A queued sample.
        inject_loss = 1;
        tick();
        if (!fault || frame_valid) $fatal(1, "FAIL loss at seal boundary");
        @(negedge clk); inject_loss = 0; clean();
        fill_frame(22, 0); assert_loss(); // Published but unconsumed frame.
        fill_frame(23, 0);
        @(negedge clk); req_valid = 1; req_addr = 0; rsp_ready = 0;
        tick();
        @(negedge clk); req_valid = 0;
        assert_loss(); // Cancel a stalled read response, consumer must discard frame.

        // Simultaneous loss + flush must remain poisoned until a clean flush.
        @(negedge clk); flush = 1; inject_loss = 1;
        tick(); if (!fault) $fatal(1, "FAIL loss priority over flush");
        @(negedge clk); flush = 0; inject_loss = 0;
        clean();
        begin_frame(24); send_words(24, (N > 1) ? N/2 : 0, 0); reset_now();
        fill_frame(25, 0);
        @(negedge clk); req_valid = 1; req_addr = AW'(N-1); rsp_ready = 0;
        tick(); reset_now(); // Full + response pending reset, no stale replay.

        if (LINK_MODE == 2) begin
            fill_frame(30, 0);
            // One pending slot in Phase3A, then actual pulse overflow while full.
            @(negedge clk); src_valid = 1; src_data = 16'sd111;
            tick();
            @(negedge clk); src_data = 16'sd222;
            tick();
            @(negedge clk); src_valid = 0;
            tick();
            if (!fault || !loss_flag || !adapter_sticky) $fatal(1, "FAIL Phase3A drop not propagated");
            clean();
        end
        fill_frame(31, 0); read_all(0, 0); release_frame();
        if (reads != replies + 2) $fatal(1, "FAIL read conservation: expected two cancelled responses");
        if (!seen_first || !seen_last || !bad_reads || !stalled_responses || loss_events < 5)
            $fatal(1, "FAIL coverage");
        if (LINK_MODE == 0 && !read_write_attempts) $fatal(1, "FAIL read/write attempt coverage");
        $display("PASS ECG_WINDOW N=%0d link=%0d frames=%0d released=%0d writes=%0d reads=%0d replies=%0d aborted=%0d loss_events=%0d first=%0d last=%0d invalid=%0d write_stalls=%0d response_stalls=%0d simultaneous_attempts=%0d mismatches=0",
                 N, LINK_MODE, frames, released, writes, reads, replies, aborts, loss_events,
                 seen_first, seen_last, bad_reads, stalled_writes, stalled_responses, read_write_attempts);
        $finish;
    end
    initial begin #10000000; $fatal(1, "FAIL window timeout"); end
endmodule
