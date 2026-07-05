# 第二十一届智能视觉组调试环境搭建记录

本文档整理本地已下载资料包的内容、启动步骤和当前项目的对接入口。

## 资料包位置

本地目录：

```text
D:\Projects\IntelCar\smcar\第二十一届全国大学生智能汽车竞赛智能视觉组调试环境搭建软件
```

主要内容：

| 目录 | 用途 |
|---|---|
| `上位机\SmartCar_VR_V1.2` | 虚拟现实推箱子上位机，已解压可直接运行 |
| `第二十一届全国大学生智能汽车竞赛智能视觉组数据集` | 官方分类数据集，10 类共 1571 张 |
| `Apriltag` | 场地 tag16h5_15/16/17/18、车模方位标识牌、场地示意图 |
| `无线摄像头` | iVCam 手机端 APK 和 Windows 端安装包 |
| `无线投屏到手机` | spacedesk 手机端 APK 和 Windows 驱动安装包 |

## 上位机启动

上位机路径：

```text
D:\Projects\IntelCar\smcar\第二十一届全国大学生智能汽车竞赛智能视觉组调试环境搭建软件\上位机\SmartCar_VR_V1.2\SmartCar_VR_V1.2.exe
```

从 PowerShell 启动：

```powershell
$root = "D:\Projects\IntelCar\smcar\第二十一届全国大学生智能汽车竞赛智能视觉组调试环境搭建软件"
$vr = Join-Path $root "上位机\SmartCar_VR_V1.2"
Start-Process -FilePath (Join-Path $vr "SmartCar_VR_V1.2.exe") -WorkingDirectory $vr
```

当前已验证启动成功：

```text
SmartCar_VR_V1.2.exe
窗口标题: SmartCar_VR
```

`V1.2` 更新要点：

- 优化车模标识牌识别。
- 调整第一视角距离，避免近距离无法看全箱子四周图片。
- 增加键盘控制：方向键控制车模平移，`A` 左转，`D` 右转。
- 支持任意分辨率缩放。
- 调整虚拟场地光线，减少 RGB565 投屏光斑。

## 摄像头配置

配置文件：

```text
上位机\SmartCar_VR_V1.2\camera.ini
```

当前内容：

```ini
camera_index=0
```

已检测到摄像头：

```text
Index: 0 | Name: Camera #0 (640x480)
Index: 1 | Name: Camera #1 (640x480)
```

当前验证结果：

- Windows 已安装 `iVCam 7.3.7`，设备管理中可见 `e2eSoft iVCam`。
- OpenCV 索引 `0` 是 iVCam 画面；未连接手机时显示等待连接画面。
- OpenCV 索引 `1` 是电脑自带摄像头。
- 因此当前上位机保持 `camera_index=0`。

如果上位机画面不是目标摄像头，修改 `camera.ini`：

```ini
camera_index=1
```

然后重启 `SmartCar_VR_V1.2.exe`。

## 上位机地图

内置地图目录：

```text
上位机\SmartCar_VR_V1.2\map_file
```

当前包含：

| 文件 | 说明 |
|---|---|
| `map1.txt` | 简单双箱双目标 |
| `map2.txt` | 带墙体绕行，多箱多目标 |
| `map3.txt` | 更复杂墙体、箱子和目标布局 |

注意：这些地图文件服务于官方上位机，不包含本仓库文本模拟器需要的 `@` 车起点符号；导入本仓库模拟器前需要补充车起点。

## 数据集清单

官方数据集：

| 类别 | 图片数 |
|---|---:|
| `00mickey_mouse` | 159 |
| `01pikachu` | 155 |
| `02spongebob_squarepants` | 163 |
| `03pleasant_sheep` | 157 |
| `04donald_duck` | 161 |
| `05nezha` | 151 |
| `06big_head_son` | 153 |
| `07gg_bond` | 154 |
| `08calabash_brothers` | 150 |
| `09grey_wolf` | 168 |
| **合计** | **1571** |

上位机自带 `image_class` 样例共 127 张，可作为上位机贴图资源，不建议当作完整训练集。

## 推荐操作顺序

1. 启动 `SmartCar_VR_V1.2.exe`，确认窗口出现。
2. 如果全局画面不对，调整 `camera.ini` 的 `camera_index` 后重启。
3. 打印或制作 `Apriltag\场地Apriltag` 中的 15、16、17、18 场地码，并按规则放到场地四角。
4. 制作车模顶部方位标识牌支架，标识牌高度按规则固定为 `15cm ± 0.5cm`。
5. 需要手机摄像头时，安装 `无线摄像头` 中的 iVCam 手机端和 Windows 端。
6. 需要手机作为车载屏幕时，安装 `无线投屏到手机` 中的 spacedesk 手机端和 Windows 驱动。
7. 用键盘控制上位机车模，先手动验证地图、视角、碰撞、推箱子逻辑。
8. 本仓库继续用 `sokoban_simulator.py` 做算法验证，输出 `move_to`、`align_to_box`、`push_box` 三类动作。

当前 Windows 端已安装 `spacedesk Windows DRIVER 2.2.17.0`，服务进程已运行：

```text
spacedeskConsole
spacedeskService
spacedeskServiceTray
```

## 与当前仓库对接

当前仓库已具备：

- 文本推箱子规划器：`sokoban_simulator.py`
- 地图批量测试：`run_map_tests.py`
- 车端 JSON 命令消费者：`command_consumer.py`
- 底盘占位实现：`vehicle_stub.py`

验证命令：

```powershell
python .\run_map_tests.py
python .\run_consumer_tests.py
```

导出单张地图规划结果：

```powershell
python .\sokoban_simulator.py .\maps\11_two_labeled_swap.txt --algorithm astar --json > plan.json
python .\command_consumer.py .\plan.json
```

下一步开发重点：

- 从上位机/屏幕图像识别出 `16x12` 地图状态。
- 将官方图像分类数据集训练成轻量分类模型，用于识别箱子贴图类别。
- 将识别结果映射到本仓库的地图符号：普通箱子 `$`、普通目标 `.`、带类别箱子 `a-z`、带类别目标 `A-Z`。
- 把 `VehicleController` 从占位实现替换为真实底盘控制。
