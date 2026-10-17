# Usage: vivado -mode batch -source synthesis/ecg/run_vivado.tcl \
#          -tclargs <NEW output-directory> synth|route
# Prefer tools/run_ecg_synthesis.py: it checks the model SHA and stages sources.
# All paths are relative to this script's repository/staged root, never the caller.
set ecg_root [file normalize [file join [file dirname [info script]] ../..]]

proc ecg_write {path value} {
    set f [open $path w]
    puts $f $value
    close $f
}

proc ecg_reports {dir stage} {
    set prefix [file join $dir $stage]
    report_utilization -file ${prefix}_utilization.rpt
    report_utilization -hierarchical -file ${prefix}_utilization_hier.rpt
    report_timing_summary -delay_type min_max -check_timing_verbose \
        -report_unconstrained -max_paths 10 -file ${prefix}_timing_summary.rpt
    report_timing -delay_type max -max_paths 20 -input_pins \
        -path_type full_clock_expanded -file ${prefix}_setup_paths.rpt
    report_timing -delay_type min -max_paths 20 -input_pins \
        -path_type full_clock_expanded -file ${prefix}_hold_paths.rpt
    report_timing -from [all_registers] -to [all_registers] -delay_type max \
        -max_paths 20 -input_pins -file ${prefix}_register_paths.rpt
    check_timing -verbose -file ${prefix}_check_timing.rpt
    report_clocks -file ${prefix}_clocks.rpt
    report_exceptions -file ${prefix}_exceptions.rpt
    report_drc -file ${prefix}_drc.rpt
    write_checkpoint ${prefix}.dcp
    write_verilog -mode funcsim ${prefix}_funcsim.v
    write_xdc ${prefix}_effective.xdc

    # Inventory actual leaf primitives, not inferred counts from RTL operators.
    set counts [dict create]
    foreach c [get_cells -hierarchical -filter {IS_PRIMITIVE == 1}] {
        dict incr counts [get_property REF_NAME $c]
    }
    set f [open ${prefix}_primitives.tsv w]
    puts $f "primitive\tcount"
    foreach ref [lsort [dict keys $counts]] {puts $f "$ref\t[dict get $counts $ref]"}
    close $f

    # Keep every INIT/INITP word and port configuration for mapping review.
    # Nonzero INIT is evidence of initialization, NOT a bit-exact ROM proof.
    set brams [get_cells -hierarchical -filter {REF_NAME =~ RAMB*}]
    set f [open ${prefix}_bram_properties.tsv w]
    puts $f "cell\tproperty\tvalue"
    foreach c $brams {
        foreach p [lsort [list_property $c]] {
            if {[regexp {^(REF_NAME|LOC|INIT.*|READ_WIDTH.*|WRITE_WIDTH.*|DO.*REG|RAM_MODE|WRITE_MODE.*)$} $p]} {
                puts $f "$c\t$p\t[get_property $p $c]"
            }
        }
    }
    close $f
    set mapping [expr {[llength $brams] > 0 ? "PASS" : "FAIL"}]
    ecg_write ${prefix}_bram_presence.tsv "status\t$mapping\nprimitive_count\t[llength $brams]"
}

proc ecg_main {arguments} {
    global ecg_root
    if {[llength $arguments] != 2} {error "Expected NEW output directory and synth|route"}
    lassign $arguments output mode
    if {$mode ni {synth route}} {error "Mode must be synth or route"}
    set output [file normalize $output]
    if {[file exists $output]} {error "Refusing to overwrite existing output: $output"}
    set model [file join $ecg_root tests/vectors/model_q12_20.hex]
    set f [open $model r]
    set words [regexp -all -inline {\S+} [read $f]]
    close $f
    if {[llength $words] != 164} {error "Model must contain exactly 164 words"}
    foreach word $words {
        if {![regexp {^[0-9a-fA-F]{8}$} $word]} {error "Invalid 32-bit model word: $word"}
    }
    # Preserve the RTL's default relative MODEL_FILE. No string generic override
    # (unsupported by some Vivado versions) and no edit to the original RTL.
    cd $ecg_root
    file mkdir $output
    ecg_write [file join $output version.txt] [version]
    set part xc7z020clg484-1
    if {[llength [get_parts -quiet $part]] != 1} {error "Target part not installed: $part"}
    create_project -in_memory -part $part
    set_param general.maxThreads 1
    foreach name {ecg_q12_20_pkg.sv ecg_model_rom.sv ecg_mlp_core.sv} {
        read_verilog -sv [file join $ecg_root rtl/ecg $name]
    }
    read_xdc [file join $ecg_root synthesis/ecg/ecg_mlp_ooc.xdc]
    synth_design -top ecg_mlp_core -part $part -mode out_of_context -flatten_hierarchy rebuilt
    if {[llength [get_sites -quiet BUFGCTRL_X0Y0]] != 1} {error "Assumed OOC clock site missing"}
    if {[llength [get_clocks ecg_clk]] != 1} {error "Expected exactly one ecg_clk"}
    if {abs([get_property PERIOD [get_clocks ecg_clk]] - 20.0) > 0.000001} {
        error "Clock constraint is not 20 ns"
    }
    ecg_reports $output synth
    ecg_write [file join $output synth_complete.txt] "PASS synthesis commands completed; timing gates are separate"
    if {$mode eq "route"} {
        opt_design
        place_design
        phys_opt_design
        route_design
        ecg_reports $output route
        report_route_status -file [file join $output route_status.rpt]
        ecg_write [file join $output route_complete.txt] "PASS implementation commands completed; inspect timing/DRC/route reports"
    }
    puts "PASS ECG_VIVADO_FLOW $mode (command completion, not timing signoff)"
}

if {[catch {ecg_main $argv} message options]} {
    puts stderr "FAIL ECG_VIVADO_FLOW: $message"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
