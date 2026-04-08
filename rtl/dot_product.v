module dot_product(
    parameter int N = 8,
    parameter int WIDTH = 8
)(
    input  logic clk,
    input  logic rst,
    input  logic signed [N-1:0][WIDTH-1:0] A,
    input  logic signed [N-1:0][WIDTH-1:0] B,
    output logic signed [2*WIDTH+3:0] dot_out,
    output logic valid
);

    // Declare internal signals and registers
    logic signed [N-1:0][WIDTH-1:0] A_reg, B_reg;
    logic signed [2*WIDTH+3:0] product_sum;
    logic valid_reg;

    // Register inputs
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            A_reg <= 0;
            B_reg <= 0;
            valid_reg <= 0;
        end else begin
            A_reg <= A;
            B_reg <= B;
            valid_reg <= 1'b1; // Set valid flag at the end of calculation cycle
        end
    end

    // Compute dot product and store in product_sum register
    always @(*) begin
        product_sum = 0;
        for (int i=0; i<N; i++) begin
            product_sum += A_reg[i] * B_reg[i];
        end
    end

    // Outputs
    assign dot_out = product_sum;
    assign valid = valid_reg;

endmodule
