# I2C 控制器设计需求

设计一个 I2C 主机控制器,支持单字节读写从机寄存器:

- SCL 频率 100kHz,时钟 50MHz(分频系数 500)
- 7-bit 地址 + 1-bit R/W
- 接口:
  - `i2c_master`: 主机模块
    - 输入: clk, rst_n, start, read_write, addr[6:0], data_in[7:0]
    - 输出: ready, sda_drv, scl_drv, sda_in, scl_in, data_out[7:0], done
    - 双向 SDA/SCL 通过 sda_drv/scl_drv(输出驱动)和 sda_in/scl_in(输入采样)实现
  - 顶层模块名 `i2c`,例化 i2c_master,对外暴露双向 sda/scl(pad 驱动)
- 协议时序:
  - START: SCL 高时 SDA 下降沿
  - STOP: SCL 高时 SDA 上升沿
  - 数据: 8 bit MSB first,第 9 bit 是 ACK(从机拉低 SDA)
  - 写: START + addr+W + data + STOP
  - 读: START + addr+R + data + STOP
- ACK 检测:主机释放 SDA 后采样,低=ACK,高=NACK

约束:
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)
- SDA 是双向信号,主机需要在适当时候切换方向(发送数据时驱动,等待 ACK 时释放)
