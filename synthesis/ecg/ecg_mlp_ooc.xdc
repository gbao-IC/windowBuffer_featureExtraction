# Standalone module analysis, NOT a ZC702 board/pin constraint file.
# Boundary budgets are assumptions for a future same-clock fabric caller.
create_clock -name ecg_clk -period 20.000 -waveform {0.000 10.000} [get_ports clk]
set_clock_uncertainty -setup 0.200 [get_clocks ecg_clk]
set_clock_uncertainty -hold 0.100 [get_clocks ecg_clk]
set_clock_transition 0.200 [get_clocks ecg_clk]

# Includes rst_n: deassertion is assumed synchronous with this clock and must
# meet recovery/removal. No false path hides reset or any arithmetic path.
set ecg_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set ecg_outputs [get_ports -filter {DIRECTION == OUT}]
set_input_delay -clock ecg_clk -max 5.000 $ecg_inputs
set_input_delay -clock ecg_clk -min 0.000 $ecg_inputs
set_input_transition 0.500 $ecg_inputs
set_output_delay -clock ecg_clk -max 5.000 $ecg_outputs
set_output_delay -clock ecg_clk -min 0.000 $ecg_outputs

# An assumed external BUFG location, not an instantiated buffer or board pin.
# This improves OOC clock estimates; the full-system clock still needs routing.
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
# No multicycle paths, false paths, pin locations, or DRC severity overrides.
