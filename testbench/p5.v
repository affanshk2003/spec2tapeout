// Code your testbench here
// or browse Examples
module tb_dot_product;

    parameter int N = 8;
    parameter int WIDTH = 8;

    logic clk, rst;
    logic signed [N-1:0][WIDTH-1:0] A;
    logic signed [N-1:0][WIDTH-1:0] B;
    logic signed [2*WIDTH+3:0] dot_out;
    logic valid;

    // Instantiate DUT
    dot_product #(
        .N(N),
        .WIDTH(WIDTH)
    ) dut (
        .clk(clk),
        .rst(rst),
        .A(A),
        .B(B),
        .dot_out(dot_out),
        .valid(valid)
    );

    // Clock generation
    always #5 clk = ~clk;

    initial begin
        integer i;
        logic signed [2*WIDTH+3:0] expected_result;

        // Initialize
        clk = 0;
        rst = 1;
        #10;
        rst = 0;

        // Generate test vectors
        expected_result = 0;
        for (i = 0; i < N; i++) begin
            A[i] = $random % 100 - 50; // Range [-50, 49]
            B[i] = $random % 100 - 50;
            expected_result += A[i] * B[i];
        end

        // Display inputs
        $display("A = ");
        for (i = 0; i < N; i++) $write("%0d ", A[i]);
        $display();
        $display("B = ");
        for (i = 0; i < N; i++) $write("%0d ", B[i]);
        $display();
        $display("Expected dot product: %0d", expected_result);

        // Wait for valid output
        wait (valid == 1);
        #1;

        // Check result
        if (dot_out === expected_result) begin
            $display("PASS: Output = %0d", dot_out);
        end else begin
            $display("FAIL: Output = %0d, Expected = %0d", dot_out, expected_result);
        end

        $finish;
    end

endmodule
