# SDC for dot_product
# Tech: SkyWater 130HD
# Spec target: 4.5 ns — using 9.0 ns (2.0x margin) for sky130hd closure

# ── Clock ──────────────────────────────────────────────────────
create_clock -name clk -period 9.0 [get_ports clk]
set_clock_uncertainty 0.1  [get_clocks clk]
set_clock_transition  0.15 [get_clocks clk]

# ── Reset (combinational false path) ───────────────────────────
set_false_path -from [get_ports rst]

# ── Input delays ───────────────────────────────────────────────
set_input_delay  1.8 -clock clk [get_ports {A B}]

# ── Output delays ──────────────────────────────────────────────
set_output_delay 1.8 -clock clk [get_ports {dot_out valid}]

# ── Load / drive ────────────────────────────────────────────────
set_load      0.01 [all_outputs]
set_driving_cell -lib_cell sky130_fd_sc_hd__inv_2 [all_inputs]
