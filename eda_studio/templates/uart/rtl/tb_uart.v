`timescale 1ns/1ps
module tb_uart;
    reg clk = 0, rst_n = 0;
    reg tx_start = 0;
    reg [7:0] tx_data = 0;
    wire tx_busy, txd;
    wire rx_busy;
    wire [7:0] rx_data;
    wire rx_valid;

    uart dut(
        .clk(clk), .rst_n(rst_n),
        .tx_start(tx_start), .tx_data(tx_data), .tx_busy(tx_busy), .txd(txd),
        .rxd(txd), .rx_busy(rx_busy), .rx_data(rx_data), .rx_valid(rx_valid)
    );

    always #10 clk = ~clk;

    initial begin
        rst_n = 0;
        #50 rst_n = 1;
        #100 tx_start = 1; tx_data = 8'h55;
        #20 tx_start = 0;
        wait(rx_valid);
        #100;
        if (rx_data === 8'h55) begin
            $display("TEST PASSED: rx_data=0x%02x", rx_data);
        end else begin
            $display("TEST FAILED: expected 0x55 got 0x%02x", rx_data);
        end
        $finish;
    end

    initial begin
        #2000000;
        $display("TEST FAILED: timeout");
        $finish;
    end
endmodule
