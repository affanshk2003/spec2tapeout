module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected
);

reg [3:0] shift_register;  // 4-bit register to store last 3 bits of the sequence
always @(posedge clk or posedge reset) begin
    if (reset) begin
        shift_register <= 4'b0000;  // Reset value
    end else begin
        shift_register <= {shift_register[2:0], data_in};  // Shift in new bit and drop oldest bit
    end
end

always @(*) begin
    if (reset) begin
        detected <= 1'b0;  // Reset value
    end else begin
        detected <= (shift_register == 4'b0011);  // Detected when last 4 bits match "0011"
    end
end

endmodule
