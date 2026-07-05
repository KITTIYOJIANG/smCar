# RT1064 串口对接记录

当前阶段不要把 Python 规划器烧进车里。Python 规划器在电脑端运行，RT1064 端烧录 C 工程，通过串口接收规划后的三类命令：

- `move_to`
- `align_to_box`
- `push_box`

## 先烧录验证工程

第一步先验证下载和串口输出：

```text
D:\Projects\IntelCar\RT1064_Library-master\Example\Coreboard_Demo\E10_printf_debug_log_demo\mdk\rt1064.uvprojx
```

Keil 操作顺序：

```text
Project -> Clean Targets
Project -> Build Target
Flash -> Download
```

串口助手参数：

```text
baudrate: 115200
data bits: 8
stop bits: 1
parity: none
```

按复位后，如果看到 `Time: 1 s`、`Time: 2 s` 一类输出，说明下载和串口调试链路通了。E10 大约 20 秒后触发断言是例程故意设计的，不是板子坏了。

## 接线

默认调试串口来自逐飞库 `DEBUG_UART_*` 配置：

| 信号 | RT1064 引脚 | 说明 |
|---|---|---|
| TX | `B12` | 接 USB-TTL 的 RX |
| RX | `B13` | 接 USB-TTL 的 TX |
| GND | `GND` | 共地 |
| 电平 | `3.3V` | 不要用 5V TTL |

无线转串口可用推荐引脚：

| 信号 | RT1064 引脚 | 库配置 |
|---|---|---|
| TX | `D16` | `UART8_TX_D16` |
| RX | `D17` | `UART8_RX_D17` |
| RTS | `D26` | 无线模块流控 |

## PC 到车协议

一行一个 ASCII 命令，以 `\n` 结尾：

```text
SMCAR,<seq>,MOVE_TO,<row>,<col>
SMCAR,<seq>,ALIGN_TO_BOX,<row>,<col>,<direction>
SMCAR,<seq>,PUSH_BOX,<direction>,<cells>
```

例子：

```text
SMCAR,1,MOVE_TO,2,5
SMCAR,2,ALIGN_TO_BOX,2,6,R
SMCAR,3,PUSH_BOX,R,2
```

RT1064 返回：

```text
SMCAR,<seq>,OK,<message>
SMCAR,<seq>,ERR,<failure_code>,<message>
```

`seq` 用来防止串口残留数据和当前命令错配。

## PC 端发送

先列出串口：

```powershell
python .\command_consumer.py --list-serial-ports
```

导出规划并发送：

```powershell
python .\sokoban_simulator.py .\maps\01_straight_push.txt --algorithm astar --json > plan.json
python .\command_consumer.py .\plan.json --serial-port COM3 --baudrate 115200
```

把 `COM3` 换成实际串口号。

## RT1064 端参考代码

参考文件：

```text
D:\Projects\IntelCar\smcar\firmware\rt1064_serial_receiver_reference.c
```

建议先从 `E02_uart_demo` 拷贝工程，再把参考代码中的接收、解析、ACK 逻辑放进 `user\src\main.c` 和 `user\src\isr.c`。

第一阶段只验证：

```text
PC 发命令 -> RT1064 收到 -> RT1064 返回 OK
```

串口 ACK 稳定后，再把下面三个函数替换成真实底盘动作：

```c
vehicle_move_to(row, col);
vehicle_align_to_box(row, col, direction);
vehicle_push_box(direction, cells);
```

## 当前安全顺序

1. 先烧 `E10_printf_debug_log_demo` 验证下载和串口输出。
2. 再烧串口接收参考程序，只验证 ACK。
3. 再选电机例程，烧录前车轮必须架空。
4. 电机能控后再接 IMU。
5. 底盘稳定后再回到视觉识别和 OpenMV。
