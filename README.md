# 智能车人工智能视觉组备赛

当前仓库先用于你负责的算法主线：状态机、文本地图模拟、推箱子规划和后续底盘控制接口。

## 文本地图模拟器

运行内置样例：

```powershell
python .\sokoban_simulator.py
```

运行指定地图：

```powershell
python .\sokoban_simulator.py .\sample_map.txt
```

地图固定为 16 列 x 12 行。符号含义：

| 符号 | 含义 |
|---|---|
| `#` | 墙 |
| `-` | 空地 |
| `@` | 车 |
| `$` | 无标签箱子 |
| `.` | 无标签目标点 |
| `a-z` | 带标签箱子 |
| `A-Z` | 对应标签目标点 |
| `*` | 无标签箱子在目标点 |
| `+` | 车在目标点 |

第一版模拟器只解决纯推箱子路径规划，不做 GUI、摄像头、物理仿真或赛事上位机替代。

## 输出说明

程序会输出两层动作。

第一层是 BFS 的栅格动作：

```text
move R
push R
```

第二层是面向实车控制的编译动作：

```text
move_to(row=3, col=6)
align_to_box(row=3, col=7, 'R')
push_box('R', 2)
```

后续接底盘时，优先对接第二层动作。

## 地图测试集

自动跑 `maps/` 下所有地图：

```powershell
python .\run_map_tests.py
```

使用 A* 搜索：

```powershell
python .\run_map_tests.py --algorithm astar
```

单张地图也可以选择算法：

```powershell
python .\sokoban_simulator.py .\maps\11_two_labeled_swap.txt --algorithm astar
```

导出车端可读的 JSON 动作：

```powershell
python .\sokoban_simulator.py .\maps\11_two_labeled_swap.txt --algorithm astar --json
```

每张地图会输出：

```text
是否有解
BFS 栅格步数
编译后 move_to / align_to_box / push_box 数量
replay 是否通过
```

带标签箱子必须推到对应大写目标。例如 `a` 只能推到 `A`，`b` 只能推到 `B`。这用于模拟真实比赛中“箱子分类后推到对应目标点”的情况。

`replay=PASS` 表示编译后的实车动作重新回放后，最终地图仍然满足完成条件。它用于防止 `compile_plan()` 把 BFS/A* 路径压缩错。
