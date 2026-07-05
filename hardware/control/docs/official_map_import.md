# 官方上位机地图导入记录

日期：2026-06-20

## 来源

本地官方上位机地图目录：

```text
第二十一届全国大学生智能汽车竞赛智能视觉组调试环境搭建软件/上位机/SmartCar_VR_V1.2/map_file
```

当前包含：

| 官方文件 | 当前处理 |
|---|---|
| `map1.txt` | 已导入 |
| `map2.txt` | 已导入 |
| `map3.txt` | 暂未导入 |

## 起点假设

官方地图文件没有小车起点 `@`，因为真实比赛中小车位置由全局定位系统实时给出。

为了先做规划器离线测试，当前统一采用左下附近空格作为假定起点：

```text
row=10, col=1
```

生成后的文件：

```text
maps/official/official_map1_start_10_01.txt
maps/official/official_map2_start_10_01.txt
```

后续接入真实视觉后，起点应来自识别到的小车当前格子，而不是写死在地图文件里。

## 关于 map3

`map3.txt` 中包含 `*`。在本仓库当前规划器里，`*` 表示“普通箱子已经在目标点上”；但在官方上位机地图里，它更可能是炸弹或扩展元素。

当前规划器还没有实现炸弹逻辑，也没有实现官方规则里的“箱子到达目标后箱子和目标同时消失”。因此本次没有把 `map3.txt` 纳入强制回归，避免把错误语义包装成通过。

可以用下面命令重新导入：

```powershell
python .\import_official_maps.py
```

实验性处理 `*`：

```powershell
python .\import_official_maps.py --bomb-policy empty
python .\import_official_maps.py --bomb-policy target
python .\import_official_maps.py --bomb-policy classic-star
```

这些实验策略只是帮助分析算法压力，不代表官方真实语义。
