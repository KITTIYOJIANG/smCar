# Vision Software

这里放视觉识别相关程序和配置，主要面向 OpenMV/OpenART、ROI 调参、数据集整理和模型部署。

```text
software/vision/
  openmv/                   板端脚本、PC 拉图工具、OpenMV 说明
  scripts/dataset_tools/    ROI、切图、训练、评估工具
  scripts/openart_legacy/   旧固件和兼容性探测脚本
  tools/                    数据集准备工具
  models/                   模型部署包和训练输出
  roi_config.json           ROI 数据集配置
  ipm_runtime_config.py     IPM 运行参数
  docs/                     视觉调试、相机调参、状态机说明
```

建议先切到这个目录再运行视觉侧工具，这样旧脚本里的相对路径仍然直观：

```powershell
cd .\software\vision
python .\tools\prepare_openart_dataset.py preview-character
python .\scripts\dataset_tools\preview_roi.py
```
