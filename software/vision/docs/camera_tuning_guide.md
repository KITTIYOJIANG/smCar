# 屏幕拍摄调参指南

日期：2026-06-23

## 当前结论

你的画面已经从“虚焦、过曝、颜色糊”进步到“基本可识别”。现在最关键的不是继续追某个亮度数字，而是让画面在连续帧里稳定。

现场观察说明：自动曝光打开时画面反而更自然一些，所以当前脚本采用“柔和自动曝光”：

- 固定增益：防止噪点和亮度乱飘。
- 固定白平衡：防止颜色类别漂移。
- 曝光小幅慢调：适应屏幕/环境亮度变化，但避免明显抽动。

## 当前推荐参数

文件：

```text
openmv/scripts/board/main_dark_screen.py
```

核心参数：

```python
EXPOSURE_US_START = 900
EXPOSURE_US_MIN = 500
EXPOSURE_US_MAX = 2200
GAIN_DB = 0

BRIGHTNESS = -3
CONTRAST = 2
SATURATION = 2

SCREEN_ROI = (205, 5, 285, 225)

TARGET_L_MEAN = 72
TARGET_L_UQ = 85

AUTO_EXPOSURE_TRIM = True
TRIM_EVERY_N_FRAMES = 20
```

## 怎么看串口输出

OpenMV 会打印类似：

```text
fps=8.2 exp_us=900 Lmean=72 Luq=85
```

含义：

| 字段 | 含义 | 怎么判断 |
|---|---|---|
| `exp_us` | 当前曝光时间 | 不要频繁大跳；慢慢变化可以接受 |
| `Lmean` | 屏幕 ROI 平均亮度 | 70 左右可用 |
| `Luq` | 屏幕 ROI 高亮区域 | 80 到 90 左右可用 |

## 调参规则

### 画面一抽一抽

把自动调节变慢：

```python
TRIM_EVERY_N_FRAMES = 30
```

如果还抽，继续加到：

```python
TRIM_EVERY_N_FRAMES = 40
```

### 画面整体太亮

先不要改 `TARGET_L_UQ`，优先缩小曝光上限：

```python
EXPOSURE_US_MAX = 1600
```

如果还是亮，再调：

```python
TARGET_L_UQ = 80
```

### 画面整体太暗

提高起始曝光和上限：

```python
EXPOSURE_US_START = 1200
EXPOSURE_US_MAX = 2600
```

### 白色边框发糊

优先处理顺序：

1. 重新对焦。
2. 降低电脑/投屏亮度。
3. 降低 `EXPOSURE_US_MAX`。
4. 避免窗户、灯条、白墙进入画面。

### 颜色分不开

可以小幅提高：

```python
SATURATION = 3
```

不要超过 3，太高会让颜色阈值变脏。

## ROI 调法

当前：

```python
SCREEN_ROI = (205, 5, 285, 225)
```

四个数含义：

```text
(x, y, width, height)
```

调节方法：

| 现象 | 调整 |
|---|---|
| 红框偏左 | 增大第一个数 `x` |
| 红框偏右 | 减小第一个数 `x` |
| 红框偏上 | 增大第二个数 `y` |
| 红框偏下 | 减小第二个数 `y` |
| 红框太宽 | 减小第三个数 `width` |
| 红框太高 | 减小第四个数 `height` |

红框只框屏幕，不要框到黑边、车架、窗户、灯条。

## 偏振片建议

偏振片有用，主要解决玻璃反光和白色亮斑。最简单测试方法：

1. 拿一副偏振太阳镜放在镜头前。
2. 慢慢旋转。
3. 如果反光明显变少且屏幕没有黑掉，就可以买小偏振片或 CPL。

注意：LCD/手机屏幕本身是偏振光，角度不对会变得很暗甚至发黑，所以偏振片必须旋转找角度。

## 什么时候可以开始做识别

满足这些就可以开始：

```text
sharpness_laplacian > 2000
overexposed_percent < 5%
蓝色/青色/白色肉眼能分开
连续画面不明显抽动
```

你现在的截图大致已经接近这个状态。下一步可以开始做格点识别，不需要继续死磕 `Luq=66`。
