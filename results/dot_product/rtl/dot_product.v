module dot_product #(
    parameter int N = 8,
    parameter int WIDTH = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic signed [N-1:0][WIDTH-1:0] A,
    input  logic signed [N-1:0][WIDTH-1:0] B,
    output logic signed [2*WIDTH+3:0] dot_out,
    output logic valid
);

    // Internal signals
    reg signed [N-1:0][WIDTH-1:0] A_reg;
    wire signed [N-1:0][WIDTH-1:0] B_wire;
    reg signed [2*WIDTH+3:0] dot_out_reg;
    reg valid_reg, valid_next;

    // Register inputs
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            A_reg <= 0;
        end else begin
            A_reg <= A;
        end
    end

    assign B_wire = B;  // No register for input B to avoid combinational loops

    // Dot product computation
    always @(*) begin
        dot_out_reg = 0;
        for (integer i = 0; i < N; i++) begin
            dot_out_reg += $signed(A_reg[i]) * $signed(B_wire[i]);
        end
    end

    // Output assignment
    assign dot_out = dot_out_reg;
    assign valid = valid_reg;

    // Valid flag generation
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            valid_reg <= 0;
        end else begin
            valid_reg <= valid_next;
        end
    end

    assign valid_next = |dot_out_reg[2*WIDTH+3:WIDTH];  // Check if dot product is zero

endmodule
