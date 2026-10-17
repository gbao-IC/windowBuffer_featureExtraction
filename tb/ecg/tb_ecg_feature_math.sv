`timescale 1ns/1ps
module tb_ecg_feature_math;
    logic clk=0,rst_n=1,abort=0,start=0,sqrt_op=0;
    logic [191:0] numerator=0,denominator=0;
    wire busy,done,error;
    wire [191:0] quotient,remainder;
    logic [191:0] vectors [0:5999];
    string path;
    integer cases,i,cycles;
    always #10 clk=~clk;
    ecg_feature_math dut(.*);
    initial begin
        if (!$value$plusargs("VECTORS=%s",path) || !$value$plusargs("CASES=%d",cases)) $fatal(1,"FAIL missing math vectors");
        $readmemh(path,vectors,0,cases*6-1);
        #3 rst_n=0;repeat(2) @(negedge clk);rst_n=1;
        for(i=0;i<cases;i=i+1) begin
            @(negedge clk);sqrt_op=vectors[i*6][0];numerator=vectors[i*6+1];denominator=vectors[i*6+2];start=1;
            @(posedge clk);#1;
            @(negedge clk);start=0;cycles=0;
            while(!done && cycles<200) begin @(posedge clk);#1;cycles++;end
            if (!done || busy || quotient!==vectors[i*6+3] || remainder!==vectors[i*6+4] || error!==vectors[i*6+5][0])
                $fatal(1,"FAIL math i=%0d op=%0d q=%h expected=%h rem=%h",i,sqrt_op,quotient,vectors[i*6+3],remainder);
            if(cycles != (vectors[i*6+5][0] ? 0 : (sqrt_op ? 96 : 192))) $fatal(1,"FAIL math latency %0d",cycles);
        end
        // Abort and reset while work is pending must not emit stale completion.
        @(negedge clk);start=1;sqrt_op=0;numerator='1;denominator=7;
        @(negedge clk);start=0;repeat(8) @(negedge clk);abort=1;
        @(negedge clk);abort=0;
        repeat(200) begin @(posedge clk);#1;if(done||busy) $fatal(1,"FAIL stale math after abort");end
        @(negedge clk);start=1;sqrt_op=1;
        @(negedge clk);start=0;repeat(8) @(negedge clk);#3 rst_n=0;
        #1;if(busy||done) $fatal(1,"FAIL math async reset");
        @(negedge clk);rst_n=1;
        repeat(100) begin @(posedge clk);#1;if(done||busy) $fatal(1,"FAIL stale math after reset");end
        // Known nontrivial recovery.
        @(negedge clk);start=1;sqrt_op=1;numerator=192'd10000;
        @(negedge clk);start=0;
        wait(done);#1;if(quotient!==192'd100 || remainder!==0) $fatal(1,"FAIL math recovery");
        $display("PASS FEATURE_MATH cases=%0d divide192 sqrt96 abort reset recovery",cases);$finish;
    end
    initial begin #2000000;$fatal(1,"FAIL math timeout");end
endmodule
