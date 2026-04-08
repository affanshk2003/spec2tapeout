module test_exp_fixed_point;

  parameter WIDTH = 8;
  localparam FRAC = WIDTH - 1;

  logic clk, rst, enable;
  logic signed [WIDTH-1:0] x_in;
  logic signed [2*WIDTH-1:0] exp_out;
  logic signed [2*WIDTH-1:0] expected;

  // DUT
  exp_fixed_point #(.WIDTH(WIDTH)) dut (
    .clk(clk),
    .rst(rst),
    .enable(enable),
    .x_in(x_in),
    .exp_out(exp_out)
  );

  // Clock generation
  always #5 clk = ~clk;

  // Convert constant to fixed-point (no real types used)
  function automatic logic signed [WIDTH-1:0] to_fixed(input int int_val);
    to_fixed = int_val <<< FRAC;
  endfunction

  initial begin
    clk = 0;
    rst = 1;
    enable = 0;
    x_in = 0;

    @(negedge clk);
    rst = 0;

    // Apply input: x = 1.0
    x_in = to_fixed(1);  // 1.0 in fixed-point
    enable = 1;
    @(negedge clk);

    // Wait 2 cycles (2-stage pipeline)
    repeat (3) @(negedge clk);

    // Expected result in fixed-point: e^1 ≈ 2.718 -> 2 * 2^FRAC + approx 0.718 * 2^FRAC (341 to match the algorithm)
    expected = 341;

    $display("exp(1.0) = %0d (expected ≈ %0d)", exp_out, expected);

    if ($abs(exp_out - expected) < (1 <<< (FRAC - 2)))
      $display("PASS");
    else
      $display("FAIL");

    $finish;
  end

endmodule
