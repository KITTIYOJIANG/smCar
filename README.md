# SmartCar Workspace

这个仓库现在按职责拆成两块，根目录只保留入口说明和少量工程配置。

```text
smcar/
  software/vision/       视觉识别：OpenMV/OpenART、模型、数据集工具、ROI 配置
  hardware/control/      小车路径控制：推箱子规划、命令消费者、串口协议、RT1064 参考代码
  local_assets/          本地资料：安装包、下载包、报告、旧模型备份，不进 git
```

## 常用入口

路径规划和底盘命令测试：

```powershell
cd .\hardware\control
python .\run_all_tests.py --skip-astar
python .\sokoban_simulator.py .\maps\11_two_labeled_swap.txt --algorithm astar --json
python .\command_consumer.py .\plan.json --serial-port COM3 --baudrate 115200
```

视觉识别和数据集工具：

```powershell
cd .\software\vision
python .\tools\prepare_openart_dataset.py preview-character
python .\scripts\dataset_tools\preview_roi.py
```

## 管理规则

- 源码、配置、说明文档放在 `software/vision` 或 `hardware/control` 对应模块内。
- 训练截图、生成报告、安装包、临时备份放进 `local_assets` 或被 `.gitignore` 忽略的目录。
- `.venv_tflite` 是本地虚拟环境，保留在本机但不提交。
- 新增地图夹具放到 `hardware/control/maps`，新增视觉采集原图放到 `software/vision/openmv/openmvImages`。
