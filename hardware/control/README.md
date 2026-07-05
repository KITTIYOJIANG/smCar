# Hardware Control

这里放小车路径控制和底盘通信相关程序。

```text
hardware/control/
  sokoban_simulator.py      16 x 12 文本地图规划器
  command_consumer.py       执行规划器导出的 JSON 命令
  vehicle_stub.py           无硬件时的底盘占位实现
  vehicle_serial.py         RT1064 串口发送与 ACK 解析
  run_*_tests.py            控制侧回归测试
  maps/                     地图夹具和官方地图导入结果
  tests/                    命令消费者坏输入用例
  firmware/                 RT1064 接收端参考代码
  docs/                     协议、测试计划、地图导入说明
```

常用命令：

```powershell
python .\run_all_tests.py --skip-astar
python .\run_map_tests.py --algorithm astar
python .\sokoban_simulator.py .\maps\11_two_labeled_swap.txt --algorithm astar --json > plan.json
python .\command_consumer.py .\plan.json
python .\command_consumer.py .\plan.json --serial-port COM3 --baudrate 115200
```
