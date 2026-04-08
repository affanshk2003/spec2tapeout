// Simple testbench for fp16_multiplier
module tb_fp16_multiplier;

  logic [15:0] a, b, result;

  // Instantiate the multiplier
  fp16_multiplier dut (
    .a(a),
    .b(b),
    .result(result)
  );

  // Function to compare expected vs actual
  task check_result(string test_name, logic [15:0] expected);
    begin
      $display("%s:", test_name);
      $display("  result   = %b", result);
      $display("  expected = %b", expected);
      if (result === expected)
        $display("  PASS\n");
      else
        $display("  FAIL\n");
    end
  endtask

  // Test procedure
  initial begin
    // Test 1: 1.0 * 2.0 = 2.0
    a = 16'b0_01111_0000000000; // 1.0
    b = 16'b0_10000_0000000000; // 2.0
    #1;
    check_result("Test 1: 1.0 * 2.0", 16'b0_10000_0000000000); // 2.0

    // Test 2: 0.0 * 5.0 = 0.0
    a = 16'b0_00000_0000000000; // 0.0
    b = 16'b0_10001_0100000000; // 5.0
    #1;
    check_result("Test 2: 0.0 * 5.0", 16'b0_00000_0000000000); // 0.0

    // Test 3: -3.0 * 4.0 = -12.0
    a = 16'b1_10000_1000000000; // -3.0
    b = 16'b0_10001_0000000000; // 4.0
    #1;
    check_result("Test 3: -3.0 * 4.0", 16'b1_10010_1000000000); // -12.0

    $finish;
  end

endmodule
