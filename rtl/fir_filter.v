module fir_filter #(
  parameter WIDTH = 16,
  parameter N = 8
)(
  input  logic                             clk,
  input  logic                             rst,
  input  logic signed [WIDTH-1:0]          x_in,
  input  logic signed [N-1:0][WIDTH-1:0]   h,
  output logic signed [2*WIDTH+$clog2(N):0] y_out
);

  localparam DEPTH = $clog2(N) + 1;

  // Registers for storing input samples and coefficients
  logic signed [DEPTH-1:0][WIDTH-1:0] x_in_regs;
  logic signed [DEPTH-1:0][WIDTH-1:0] h_regs;

  // Register to store the accumulated result
  logic signed [2*WIDTH+$clog2(N):0] y_out_reg;

  always @(posedge clk or posedge rst) begin
    if (rst) begin
      x_in_regs <= 0;
      h_regs <= 0;
      y_out_reg <= 0;
    end else begin
      // Shift input samples and coefficients
      x_in_regs <= {x_in, x_in_regs[DEPTH-1:1]};
      h_regs <= {h, h_regs[DEPTH-1:1]};

      // Accumulate the product of input samples and coefficients
      y_out_reg <= 0;
      for (int i = 0; i < N; i++) begin
        y_out_reg <= y_out_reg + x_in_regs[i] * h_regs[i];
      end
    end
  end

  // Output the accumulated result
  assign y_out = y_out_reg;
endmodule
