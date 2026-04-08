// Testbench for the FIR filter
module test_fir_filter;

  parameter WIDTH = 16;
  parameter N = 8;
  logic clk, rst;
  logic signed [WIDTH-1:0] x_in;
  logic signed [N-1:0][WIDTH-1:0] h;
  logic signed [2*WIDTH+$clog2(N):0] y_out;

  // Instantiate the DUT
  fir_filter #(.WIDTH(WIDTH), .N(N)) dut (
    .clk(clk),
    .rst(rst),
    .x_in(x_in),
    .h(h),
    .y_out(y_out)
  );

  // Clock generation
  always #5 clk = ~clk;

  // Input samples and expected outputs
  logic signed [WIDTH-1:0] samples [0:15];
  logic signed [2*WIDTH+$clog2(N):0] expected_val;
  int i, j;

  initial begin
    clk = 0;
    rst = 1;
    x_in = 0;

    for (i = 0; i < N; i++) begin
      h[i] = i + 1; // Coefficients: 1, 2, ..., N
    end

    for (i = 0; i < 16; i++) begin
      samples[i] = i + 1;
    end

    @(negedge clk);
    rst = 0;

    for (i = 0; i < 16; i++) begin
      
      @(negedge clk);
	  x_in = samples[i];
      expected_val = 0;
      for (j = 0; j < N; j++) begin
        if ((i-j) >= 0)
          expected_val += samples[i-j] * h[j];
      end

      @(posedge clk);
      #1;
      $display("Sample %0d: y_out = %0d, expected = %0d", i, y_out, expected_val);
      if (y_out === expected_val)
        $display("PASS");
      else
        $display("FAIL");
    end

    $finish;
  end

endmodule

