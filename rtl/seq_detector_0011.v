module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected
);

reg [3:0] shift_register;  // Four bit register to store last four bits of the input stream
always @(posedge clk or posedge reset) begin
    if (reset) begin
        shift_register <= 4'b0000;  // Reset state
    end else begin
        shift_register <= {shift_register[2:0], data_in};  // Shift in new bit from the input stream
   <beginofsentence>endmodule
