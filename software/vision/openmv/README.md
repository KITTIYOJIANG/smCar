# OpenMV 文件夹使用规则

这个目录只负责 OpenART / OpenMV 拍照、调参、板端脚本和由拍摄图生成的数据。

## 右眼识别任务

右眼负责三大项：

```text
character  人物
digit      数字
tnt        TNT
```

主数据目录：

```text
D:\Projects\Embodied\SmartCars\IntelCar\smcar\openmv\openmvImages\raw_Images\right_eye
```

## 新拍图片放哪里

不确定类别的右眼原图，先放：

```text
openmv\openmvImages\raw_Images\right_eye\_incoming_unsorted
```

如果拍摄时已经知道类别，直接放到对应任务目录。

人物图按编号人物目录管理：

```text
openmv\openmvImages\raw_Images\right_eye\character\00mickey_mouse\far
openmv\openmvImages\raw_Images\right_eye\character\01pikachu\motion_blur
openmv\openmvImages\raw_Images\right_eye\character\09grey_wolf\far
```

数字图先保持空目录，等你补拍：

```text
openmv\openmvImages\raw_Images\right_eye\digit\00_far
openmv\openmvImages\raw_Images\right_eye\digit\06_motion_blur
```

TNT 图：

```text
openmv\openmvImages\raw_Images\right_eye\tnt\tnt_unsorted
```

## 人物编号顺序

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

编号只是为了文件排序。训练工具会自动把 `00mickey_mouse` 还原成模型标签 `mickey_mouse`。

## 从 OpenMV 板子拷图

OpenMV 脚本通常先把图片保存到板子或 SD 卡，例如 `/sd/screen_000.jpg`。

电脑上运行：

```powershell
python openmv\scripts\pc\pull_openmv_screenshots.py --source E:\
```

默认会拷到：

```text
openmv\openmvImages\raw_Images\right_eye\_incoming_unsorted
```

如果这次拍的是某一类，直接指定目标：

```powershell
python openmv\scripts\pc\pull_openmv_screenshots.py --source E:\ --dest openmv\openmvImages\raw_Images\right_eye\character\00mickey_mouse\far
```

## 不同目录的含义

```text
openmv\openmvImages\raw_Images
```

原始拍摄图，只放没有画框、没有裁剪、没有后处理的照片。

```text
openmv\openmvImages\datasets
```

脚本生成的裁剪图、切格子图、可训练数据。不要手工把新拍原图丢进这里。

```text
openmv\openmvImages\dataset_previews
```

预览图、检查图，只用来看 ROI 对不对。不要拿这里的图片训练。

## 脚本位置

板端脚本：

```text
openmv\scripts\board
```

电脑端辅助工具：

```text
openmv\scripts\pc
```

配置文件：

```text
openmv\configs
```

## 重要原则

1. 原图永远先进 `raw_Images`。
2. 裁剪图和预览图不要混进原图目录。
3. 带框截图、OpenMV IDE 截图、报错截图不要训练。
4. 数字、人物、TNT 分开放。
5. 每次重训前，先确认训练来源是不是原图或干净 ROI。
