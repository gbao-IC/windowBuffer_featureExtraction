`timescale 1ns/1ps
module tb_ecg_feature_core #(parameter bit STALLED=0);
    logic clk=0,rst_n=1,flush=0,source_loss=0;
    always #10 clk=~clk;
    logic fs_valid=0,s_valid=0;
    wire fs_ready,s_ready,f_valid,w_fault,w_abort,w_loss;
    logic [31:0] tag=0,beat=0,rr=0,pv=0;
    logic signed [15:0] sample=0;
    wire [31:0] f_tag,f_beat,f_rr,f_pv;
    wire [8:0] count;
    wire w_req_ready,w_rsp_valid,w_rsp_error,w_release_ready;
    wire signed [15:0] w_data;
    wire [8:0] w_addr;
    logic start=0,abort=0,result_ready=0;
    wire ready,busy,e_req_valid,e_rsp_ready,release_valid,result_valid,done,flush_required;
    wire [8:0] req_addr;
    wire [2:0] error_code;
    wire signed [95:0] features [0:11];
    wire [31:0] result_id,result_beat;
    logic [31:0] rng=32'h3c000347;
    logic block_response=0,inject_error=0,inject_address=0;
    wire allow_req=!STALLED || rng[0] || rng[3];
    wire allow_rsp=!block_response && (!STALLED || rng[1] || rng[5]);
    wire e_req_ready=w_req_ready && allow_req;
    wire e_rsp_valid=w_rsp_valid && allow_rsp;
    wire [8:0] e_rsp_addr=inject_address ? w_addr^9'd1 : w_addr;
    wire e_rsp_error=w_rsp_error || inject_error;
    wire [1151:0] result_flat;
    genvar g;
    generate for(g=0;g<12;g=g+1) assign result_flat[g*96+:96]=features[g];endgenerate
    always @(negedge clk) begin
        rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
    end
    ecg_window_buffer window (
        .clk(clk),.rst_n(rst_n),.flush(flush),.source_loss(source_loss),
        .frame_start_valid(fs_valid),.frame_start_ready(fs_ready),.in_frame_id(tag),.in_beat_index_360(beat),
        .in_rr_curr_ticks_360(rr),.in_rr_prev_ticks_360(pv),.sample_in(sample),.sample_valid(s_valid),.sample_ready(s_ready),
        .frame_valid(f_valid),.frame_id(f_tag),.beat_index_360(f_beat),.rr_curr_ticks_360(f_rr),.rr_prev_ticks_360(f_pv),
        .samples_collected(count),.frame_release_valid(release_valid),.frame_release_ready(w_release_ready),
        .rd_req_valid(e_req_valid && allow_req),.rd_req_ready(w_req_ready),.rd_req_addr(req_addr),
        .rd_rsp_valid(w_rsp_valid),.rd_rsp_ready(e_rsp_ready && allow_rsp),.rd_rsp_data(w_data),.rd_rsp_addr(w_addr),.rd_rsp_error(w_rsp_error),
        .fault(w_fault),.loss_flag(w_loss),.frame_abort(w_abort)
    );
    ecg_feature_core dut (
        .clk(clk),.rst_n(rst_n),.abort(abort),.start(start),.start_ready(ready),.busy(busy),
        .frame_valid(f_valid),.frame_fault(w_fault),.frame_abort(w_abort),.frame_id(f_tag),.beat_index_360(f_beat),
        .rr_curr_ticks_360(f_rr),.rr_prev_ticks_360(f_pv),
        .rd_req_valid(e_req_valid),.rd_req_ready(e_req_ready),.rd_req_addr(req_addr),
        .rd_rsp_valid(e_rsp_valid),.rd_rsp_ready(e_rsp_ready),.rd_rsp_data(w_data),.rd_rsp_addr(e_rsp_addr),.rd_rsp_error(e_rsp_error),
        .frame_release_valid(release_valid),.frame_release_ready(w_release_ready),
        .result_valid(result_valid),.result_ready(result_ready),.features(features),
        .result_frame_id(result_id),.result_beat_index_360(result_beat),.done(done),.error_code(error_code),.flush_required(flush_required)
    );
    logic [15:0] samples [0:34799];
    logic [95:0] expected [0:1199];
    logic [31:0] metadata [0:199];
    string vectors;
    integer cases,i,j,cycles=0,begin_cycle,current_case=0,serial=0,accepted=0,completed=0,failed=0;
    integer requests=0,responses=0,req_stalls=0,rsp_stalls=0,output_stalls=0;
    integer active_requests=0,active_responses=0,min_latency=1000000,max_latency=0;
    bit in_transaction=0,held_req=0,held_result=0;
    logic [8:0] saved_addr;
    logic [1151:0] saved_result;
    always @(posedge clk) begin
        cycles++;
        if (!rst_n) begin in_transaction=0;held_req=0;held_result=0;end
        else begin
            if(start && ready) begin
                accepted++;in_transaction=1;active_requests=0;active_responses=0;begin_cycle=cycles;
            end
            if(e_req_valid && !e_req_ready) req_stalls++;
            if(w_rsp_valid && !e_rsp_valid) rsp_stalls++;
            if(held_req && !abort && f_valid && !w_fault && (req_addr!==saved_addr || !e_req_valid)) $fatal(1,"FAIL request changed under stall");
            held_req=e_req_valid && !e_req_ready;saved_addr=req_addr;
            if(e_req_valid && e_req_ready) begin
                if(!in_transaction || req_addr!==9'(active_requests)) $fatal(1,"FAIL request ordering");
                active_requests++;requests++;
            end
            if(e_rsp_valid && e_rsp_ready) begin
                if(w_data!==samples[current_case*347+active_responses]) $fatal(1,"FAIL window payload");
                active_responses++;responses++;
            end
            if(held_result && !abort && f_valid && !w_fault && (!result_valid || result_flat!==saved_result)) $fatal(1,"FAIL output changed during stall");
            held_result=result_valid && !result_ready;saved_result=result_flat;
            if(result_valid && !result_ready) output_stalls++;
            if(result_valid && result_ready) begin
                if(active_requests!=347 || active_responses!=347 || error_code!=0 || result_id!=32'(serial) || result_beat!=32'(serial*360)) $fatal(1,"FAIL frame metadata/count");
                for(integer f=0;f<12;f++)
                    if(features[f]!==expected[current_case*12+f]) $fatal(1,"FAIL feature case=%0d feature=%0d actual=%h expected=%h",current_case,f,features[f],expected[current_case*12+f]);
                completed++;in_transaction=0;
            end
        end
    end
    task automatic tick;@(posedge clk);#2;endtask
    task automatic recover;
        @(negedge clk);start=0;abort=0;source_loss=0;inject_error=0;inject_address=0;block_response=0;result_ready=0;flush=1;
        tick();@(negedge clk);flush=0;
        repeat(3) tick();
        if(busy||flush_required||f_valid||result_valid||done) $fatal(1,"FAIL clean recovery");
    endtask
    task automatic reset_all;
        #3 rst_n=0;#1;
        if(result_valid || done || e_req_valid || busy) $fatal(1,"FAIL reset outputs");
        @(negedge clk);start=0;s_valid=0;fs_valid=0;abort=0;flush=0;source_loss=0;block_response=0;inject_error=0;inject_address=0;result_ready=0;
        repeat(2) tick();@(negedge clk);rst_n=1;repeat(2) tick();
    endtask
    task automatic load_start(input integer c);
        current_case=c;serial++;
        @(negedge clk);fs_valid=1;tag=32'(serial);beat=32'(serial*360);rr=metadata[c*2];pv=metadata[c*2+1];
        if(!fs_ready) $fatal(1,"FAIL window not free");tick();
        @(negedge clk);fs_valid=0;tag='1;beat='1;rr='1;pv='1;
        for(integer s=0;s<347;s++) begin
            @(negedge clk);s_valid=1;sample=$signed(samples[c*347+s]);
            if(!s_ready) $fatal(1,"FAIL fill not ready");tick();
        end
        @(negedge clk);s_valid=0;tick();
        if(!f_valid||!ready) $fatal(1,"FAIL full window not available");
        @(negedge clk);start=1;tick();@(negedge clk);start=0;
    endtask
    task automatic await_result;
        integer timeout;
        timeout=0;
        while(!result_valid && timeout<5000) begin tick();timeout++;if(flush_required) $fatal(1,"FAIL unexpected error %0d",error_code);end
        if(!result_valid) $fatal(1,"FAIL feature timeout");
        min_latency=(cycles-begin_cycle)<min_latency ? cycles-begin_cycle : min_latency;
        max_latency=(cycles-begin_cycle)>max_latency ? cycles-begin_cycle : max_latency;
        if(done) $fatal(1,"FAIL done before result acceptance");
        for(integer f=0;f<12;f++) if(features[f]!==expected[current_case*12+f])
            $fatal(1,"FAIL feature case=%0d feature=%0d actual=%h expected=%h",current_case,f,features[f],expected[current_case*12+f]);
    endtask
    task automatic finish_result;
        repeat(17) tick();
        if(!f_valid || release_valid) $fatal(1,"FAIL ownership released before output acceptance");
        @(negedge clk);result_ready=1;tick();
        if(!done || !release_valid) $fatal(1,"FAIL completion/release");
        @(negedge clk);result_ready=0;tick();
        if(busy || f_valid || done) $fatal(1,"FAIL release completion");
    endtask
    task automatic expect_fault(input logic [2:0] code);
        integer timeout;
        timeout=0;
        while(!flush_required && timeout<20) begin tick();timeout++;end
        if(!flush_required || result_valid || error_code!=code) $fatal(1,"FAIL missing fault code %0d actual %0d",code,error_code);
        failed++;
        repeat(5) tick();
        if(result_valid || e_req_valid || ready || done) $fatal(1,"FAIL stale transaction in fault");
        recover();
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("CASES=%d",cases)) $fatal(1,"FAIL missing feature vectors");
        $readmemh({vectors,"/samples.mem"},samples,0,cases*347-1);
        $readmemh({vectors,"/expected.mem"},expected,0,cases*12-1);
        $readmemh({vectors,"/rr.mem"},metadata,0,cases*2-1);
        reset_all();
        for(i=0;i<cases;i++) begin
            load_start(i);await_result();finish_result();
            $display("PASS FEATURES case=%0d all12 bit_exact stalled=%0d",i,STALLED);
        end
        // Repeated frame, start pulse while busy does not create pending work.
        load_start(5);repeat(10) tick();@(negedge clk);start=1;tick();@(negedge clk);start=0;
        await_result();finish_result();
        // External abort with a response stalled in the verified Window.
        load_start(1);block_response=1;repeat(6) tick();@(negedge clk);abort=1;tick();expect_fault(1);
        // Window loss during arithmetic invalidates the frame and stops math.
        load_start(10);wait(active_responses==347);repeat(20) tick();@(negedge clk);source_loss=1;tick();expect_fault(1);
        // Loss after computing but before downstream acceptance revokes result.
        load_start(6);await_result();@(negedge clk);source_loss=1;tick();expect_fault(1);
        // Read-error and wrong-address responses are explicit faults.
        load_start(2);inject_error=1;expect_fault(2);
        load_start(3);inject_address=1;expect_fault(2);
        // Reset pending read, in arithmetic, and result under backpressure.
        load_start(4);block_response=1;repeat(4) tick();reset_all();
        load_start(8);wait(active_responses==347);repeat(20) tick();reset_all();
        load_start(9);await_result();reset_all();
        // Recovery runs all arithmetic after faults and reset, with no stale data.
        load_start(27);await_result();finish_result();
        if(completed!=cases+2 || failed!=5 || accepted!=cases+10 || output_stalls==0 || (STALLED && (req_stalls==0 || rsp_stalls==0)))
            $fatal(1,"FAIL coverage/accounting accepted=%0d completed=%0d faults=%0d",accepted,completed,failed);
        $display("PASS FEATURE_CORE cases=%0d completed=%0d faults=%0d reset_aborts=3 accepted=%0d requests=%0d responses=%0d req_stalls=%0d rsp_stalls=%0d output_stalls=%0d latency_min=%0d latency_max=%0d mismatches=0",cases,completed,failed,accepted,requests,responses,req_stalls,rsp_stalls,output_stalls,min_latency,max_latency);
        $finish;
    end
    initial begin #10000000;$fatal(1,"FAIL feature global timeout");end
endmodule
