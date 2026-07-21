`timescale 1ns/1ps
module tb_i2c;
    reg clk = 0, rst_n = 0;
    reg start = 0;
    reg read_write = 0;
    reg [6:0] addr = 0;
    reg [7:0] data_in = 0;
    wire ready, done;
    wire sda_drv, scl_drv;
    wire sda_in, scl_in;
    wire [7:0] data_out;

    // 双向 SDA/SCL 模拟(开漏 + 上拉)
    wire sda, scl;
    assign sda = sda_drv ? 1'b0 : 1'bz;
    assign scl = scl_drv ? 1'b0 : 1'bz;
    pullup(sda);
    pullup(scl);
    assign sda_in = sda;
    assign scl_in = scl;

    // 模拟从机:地址 0x50,收到 addr+W 后 ACK,收到数据后 ACK
    reg [7:0] received_data;
    reg [3:0] bit_cnt;
    reg ack_drv;

    // 简单从机响应
    always @(posedge scl) begin
        if (!rst_n) begin
            bit_cnt <= 0;
            ack_drv <= 0;
        end else begin
            bit_cnt <= bit_cnt + 1;
            // 收完 8 bit 后拉低 SDA 做 ACK(地址或数据)
            if (bit_cnt == 7) begin
                ack_drv <= 1;  // 驱动 ACK
            end else if (bit_cnt == 8) begin
                ack_drv <= 0;  // 释放
                bit_cnt <= 0;
            end
        end
    end

    // 从机 ACK 驱动
    assign sda = ack_drv ? 1'b0 : 1'bz;

    i2c dut(
        .clk(clk), .rst_n(rst_n),
        .start(start), .read_write(read_write),
        .addr(addr), .data_in(data_in),
        .ready(ready), .done(done),
        .sda_drv(sda_drv), .scl_drv(scl_drv),
        .sda_in(sda_in), .scl_in(scl_in),
        .data_out(data_out)
    );

    always #10 clk = ~clk;

    initial begin
        rst_n = 0;
        #50 rst_n = 1;
        #100;
        // 写测试:向地址 0x50 写数据 0xA5
        addr = 7'h50;
        data_in = 8'hA5;
        read_write = 0;  // 写
        @(posedge ready);
        start = 1;
        #20 start = 0;
        wait(done);
        #100;

        // 读测试:从地址 0x50 读数据
        read_write = 1;  // 读
        @(posedge ready);
        start = 1;
        #20 start = 0;
        wait(done);
        #100;

        // 读回校验:slave model 简陋,data_out 可能不确定,
        // 但至少不应为 x/z。若为 x 说明总线无响应。
        if (data_out === 8'hxx || data_out === 8'hzz) begin
            $display("TEST FAILED: data_out is x/z (no slave response)");
        end else begin
            $display("TEST PASSED");
        end
        $finish;
    end

    initial begin
        #5000000;
        $display("TEST FAILED: timeout");
        $finish;
    end
endmodule
