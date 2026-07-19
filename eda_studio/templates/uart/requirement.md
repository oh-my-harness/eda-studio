# UART 设计需求

设计一个简易 UART 发送器 + 接收器:

- 波特率 115200,时钟 50MHz
- 数据位 8,停止位 1,无校验
- 接口:
  - `uart_tx`: TX 模块,输入 clk/rst_n/tx_start/tx_data[7:0],输出 tx_busy/txd
  - `uart_rx`: RX 模块,输入 clk/rst_n/rxd,输出 rx_busy/rx_data[7:0]/rx_valid
- 顶层模块名 `uart`,例化 uart_tx + uart_rx,对外暴露 txd/rxd

约束:
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)
