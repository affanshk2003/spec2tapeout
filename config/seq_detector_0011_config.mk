# config.mk for seq_detector_0011
# Auto-fixed by agent_v3_4.py for ORFS compatibility

export PLATFORM        := sky130hd
export DESIGN_NAME     := seq_detector_0011
export DESIGN_NICKNAME := seq_detector_0011

# Paths relative to ORFS flow/ directory.
# Agent copies files to these locations in Phase 1.
export VERILOG_FILES   := designs/src/seq_detector_0011/seq_detector_0011_synth.v
export SDC_FILE        := designs/sky130hd/seq_detector_0011/constraint.sdc

export CLOCK_PORT      := clk
export CLOCK_NET       := clk
export CLOCK_PERIOD    := 20.0

export CORE_UTILIZATION  := 40
export CORE_ASPECT_RATIO := 1
export CORE_MARGIN       := 2

export PLACE_DENSITY          := 0.60
export PLACE_DENSITY_LB_ADDON := 0.1

export CTS_BUF_CELL    := sky130_fd_sc_hd__buf_2

export MIN_ROUTING_LAYER := met1
export MAX_ROUTING_LAYER := met5

export VDD_NET_NAME    := VDD
export GND_NET_NAME    := VSS
export POWER_NETS      := VDD
export GROUND_NETS     := VSS

export CELL_PAD_IN_SITES_GLOBAL_PLACEMENT := 4
export CELL_PAD_IN_SITES_DETAIL_PLACEMENT := 2

export SETUP_SLACK_MARGIN := 0.0
export HOLD_SLACK_MARGIN  := 0.0

export ANTENNA_RATIO   := 400
export SYNTH_STRATEGY  := AREA 0
export SYNTH_MAX_FANOUT := 6
export VERBOSE         := 0
