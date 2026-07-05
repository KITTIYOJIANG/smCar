# 右眼数据集目录清单

时间：2026-07-01

## 主目录

```text
D:\Projects\Embodied\SmartCars\IntelCar\smcar\openmv\openmvImages\raw_Images\right_eye
```

## 任务分区

```text
right_eye\character
right_eye\digit
right_eye\tnt
right_eye\background
right_eye\_incoming_unsorted
```

## 人物目录命名

人物按固定编号排序，目录名采用：

```text
00mickey_mouse
01pikachu
02spongebob_squarepants
03pleasant_sheep
04donald_duck
05nezha
06big_head_son
07gg_bond
08calabash_brothers
09grey_wolf
```

场景放到人物目录下面：

```text
right_eye\character\00mickey_mouse\far
right_eye\character\00mickey_mouse\mid
right_eye\character\00mickey_mouse\near
right_eye\character\00mickey_mouse\motion_blur
```

注意：目录前缀只是为了文件管理和排序。训练脚本会自动把 `00mickey_mouse` 还原成模型标签 `mickey_mouse`。

## 当前人物图片

| 类别目录 | 场景 | 总数 |
| --- | --- | ---: |
| `00mickey_mouse` | `far`, `left`, `mid`, `motion_blur`, `near` | 234 |
| `01pikachu` | `far`, `motion_blur` | 32 |
| `02spongebob_squarepants` | `far` | 45 |
| `03pleasant_sheep` | `far`, `motion_blur` | 25 |
| `04donald_duck` | `far`, `motion_blur` | 31 |
| `05nezha` | `far`, `motion_blur` | 54 |
| `06big_head_son` | `far`, `motion_blur` | 32 |
| `07gg_bond` | `far`, `motion_blur` | 28 |
| `08calabash_brothers` | `far`, `motion_blur` | 113 |
| `09grey_wolf` | `far`, `motion_blur` | 38 |

人物合计：632 张。

## 当前 TNT 图片

| 目录 | 数量 |
| --- | ---: |
| `right_eye\tnt\tnt_unsorted` | 51 |

## 当前数字图片

数字还没有拍，以下目录已提前建好，当前全部为空：

```text
00_far / 00_mid / 00_near / 00_motion_blur
01_far / 01_mid / 01_near / 01_motion_blur
02_far / 02_mid / 02_near / 02_motion_blur
03_far / 03_mid / 03_near / 03_motion_blur
04_far / 04_mid / 04_near / 04_motion_blur
05_far / 05_mid / 05_near / 05_motion_blur
06_far / 06_mid / 06_near / 06_motion_blur
07_far / 07_mid / 07_near / 07_motion_blur
08_far / 08_mid / 08_near / 08_motion_blur
09_far / 09_mid / 09_near / 09_motion_blur
```

## 后续拍照规则

1. 不确定类别的图先放 `right_eye\_incoming_unsorted`。
2. 人物图放 `right_eye\character\<编号人物名>\<场景>`。
3. 数字图放 `right_eye\digit\<两位数字>_<场景>`。
4. TNT 图放 `right_eye\tnt\tnt_<场景>`，当前已有 `tnt_unsorted`。
5. 背景/空画面/干扰图放 `right_eye\background`，用于训练或测试 unknown/background。
