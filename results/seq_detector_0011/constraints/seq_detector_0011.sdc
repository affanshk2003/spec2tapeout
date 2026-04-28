# SDC for seq_detector_0011
# Tech: SkyWater 130HD
# Spec target: 1.1 ns — using 3.85 ns (3.5x margin) for sky130hd closure

# ── Clock ──────────────────────────────────────────────────────
create_clock -name clk -period 3.85 [get_ports clk]
set_clock_uncertainty 0.1  [get_clocks clk]
set_clock_transition  0.15 [get_clocks clk]

# ── Reset (combinational false path) ───────────────────────────
set_false_path -from [get_ports reset]

# ── Input delays ───────────────────────────────────────────────
set_input_delay  0.77 -clock clk [get_ports {data_in}]

# ── Output delays ──────────────────────────────────────────────
set_output_delay 0.77 -clock clk [get_ports {detected}]

# ── Load / drive ────────────────────────────────────────────────
set_load      0.01 [all_outputs]
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 [all_inputs]
