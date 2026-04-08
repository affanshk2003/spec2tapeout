module exp_fixed_point #(parameter WIDTH = 8)(
    input wire clk,
    input wire rst,
    input wire enable,
    input wire [WIDTH-1:0] x_in,
    output wire [2*WIDTH-1:0] exp_out
);

    reg [WIDTH-1:0] x;
    reg [2*WIDTH-1:0] e;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            e <= 0;
        end else if (enable) begin
            x <= x_in;
            e[2*WIDTH-1:WIDTH] <= {x, 1'b0}; // Shift left by one bit
            e[WIDTH-1:0] <= ((e[2*WIDTH-1:WIDTH] + 1) * x >> 1) + (1 << WIDTH); // Taylor series expansion
        end
    end

    assign exp_out = e;
endmodule
