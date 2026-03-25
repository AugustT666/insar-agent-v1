# ISCE3 + MintPy 使用说明

本仓库用于基于 NISAR RSLC 数据完成 `isce3 + MintPy` 时序处理，流程分成两层：

1. 单主影像配准栈
2. 下游干涉网络构建与 MintPy 时序反演

脚本默认不再依赖任何本机硬编码环境路径。使用前只需要：

- 预先安装好 `isce3`
- 预先安装好 `MintPy`
- 激活对应虚拟环境，并确保当前环境里可以直接调用 `python` 和 `smallbaselineApp.py`

## 1. 目录约定

仓库默认使用以下目录结构：

```text
.
├── insar_nisar.yaml
├── nisar.txt
├── data
│   ├── dem
│   │   └── dem.tif
│   └── rslc
│       ├── *.h5
│       └── ...
├── scripts
│   ├── prepare_isce3_stack.py
│   ├── prepare_isce3_network.py
│   ├── plot_isce3_baseline_network.py
│   ├── prep_nisar_current_gunw.py
│   └── run_mintpy_nisar_stack.sh
└── work
```

默认约定如下：

- RSLC 数据放在 `data/rslc`
- DEM 放在 `data/dem/dem.tif`
- ISCE3 模板配置文件为 `insar_nisar.yaml`
- MintPy 自定义模板为 `nisar.txt`
- 所有中间结果和输出默认写入 `work/`

## 2. 流程概览

推荐流程如下：

1. 生成单主影像配准栈
2. 运行单主影像栈，得到统一配准参考
3. 生成下游干涉网络 runconfig
4. 运行下游网络，得到各 pair 的 GUNW 产品
5. 绘制时空基线图
6. 运行 MintPy 时序反演

需要注意：

- `prepare_isce3_stack.py` 只负责单主影像配准栈
- `prepare_isce3_network.py` 只负责下游干涉网络
- 时间基线阈值、连边策略、pair list 都只属于下游构网层
- MintPy 不会凭空补出不存在的干涉对，因此下游网络必须先实际生成对应 GUNW 产品

## 3. 单主影像配准栈

### 3.1 生成配准栈

在已激活的 `isce3` 环境中运行：

```bash
python scripts/prepare_isce3_stack.py
```

默认行为：

- 默认选择最早日期作为参考景
- 为其余所有影像生成单主影像 runconfig

建议：

- 公开使用时，最好显式指定参考日期
- 如果你的工作流对负时间基线敏感，建议直接指定最早日期为参考景

例如：

```bash
python scripts/prepare_isce3_stack.py --reference 20251029
```

### 3.2 常用参数

```bash
python scripts/prepare_isce3_stack.py \
  --reference 20251029 \
  --output-dir work/isce3_stack
```

关键参数说明：

- `--reference`
  - 参考景日期，格式 `YYYYMMDD`
  - 也支持直接传入某个 RSLC 文件路径
  - 默认 `auto`
  - `auto` 会选择最早日期

### 3.3 输出内容

默认输出到 `work/isce3_stack`，主要包括：

- `runconfigs/`
  - 单主影像栈的 runconfig
- `runs/`
  - 每个主辅组合的运行目录
- `run_all.sh`
  - 顺序运行脚本
- `run_parallel.sh`
  - 并发运行脚本
- `stack_manifest.csv`
  - 参考景、辅景、runconfig、run 目录清单
- `reference_date.txt`
  - 选中的参考景日期

## 4. 运行单主影像栈

### 4.1 顺序运行

```bash
bash work/isce3_stack/run_all.sh
```

`run_all.sh` 默认调用当前环境中的：

```bash
python -m nisar.workflows.insar
```

如果你确实需要换成别的入口命令，也可以直接在后面覆盖：

```bash
bash work/isce3_stack/run_all.sh python -m nisar.workflows.insar
```

### 4.2 并发运行

```bash
bash work/isce3_stack/run_parallel.sh work/isce3_stack 8
```

含义：

- 第 1 个参数：栈目录
- 第 2 个参数：并发数

如果需要指定其他 Python，可通过环境变量覆盖：

```bash
PYTHON_BIN=python bash work/isce3_stack/run_parallel.sh work/isce3_stack 8
```

## 5. 下游干涉网络

下游网络和单主影像栈是两回事：

- 单主影像栈用于统一配准参考
- 下游网络用于真正生成时序反演所需的 pair 产品
- 时间基线阈值也只在这一层生效

### 5.1 默认模式：时间基线阈值 `tbase36`

直接运行：

```bash
python scripts/prepare_isce3_network.py
```

默认会生成：

- 输出目录：`work/isce3_network`
- 网络标签：`pairs_tbase36d`

### 5.2 自定义时间基线阈值

例如只保留时间基线不超过 24 天的 pair：

```bash
python scripts/prepare_isce3_network.py \
  --output-dir work/isce3_tbase24 \
  --max-temporal-baseline-days 24
```

### 5.3 固定连边数模式

例如每景向后连接 3 景：

```bash
python scripts/prepare_isce3_network.py \
  --network-mode conn \
  --connection-span 3 \
  --output-dir work/isce3_conn3
```

### 5.4 使用已有 pair list

如果你已经手工准备好了 `YYYYMMDD_YYYYMMDD` 格式的 pair list，也可以直接：

```bash
python scripts/prepare_isce3_network.py \
  --pair-list my_pairs.txt \
  --output-dir work/isce3_tbase24
```

### 5.5 输出内容

`prepare_isce3_network.py` 默认输出到 `work/isce3_network`，主要包括：

- `runconfigs/`
  - 下游干涉网络每个 pair 的 runconfig
- `runs/`
  - 每个 pair 的运行目录
- `run_all.sh`
  - 顺序运行脚本
- `run_parallel.sh`
  - 并发运行脚本
- `pair_lists/pairs_tbase36d.txt` 或 `pair_lists/pairs_conn3.txt`
  - 当前规则生成的 pair list
- `pair_lists/pairs_selected.txt`
  - 当前网络实际使用的 pair 列表
- `pair_lists/pairs_selected.csv`
  - pair 与 RSLC 文件映射清单

## 6. 运行下游干涉网络

顺序运行：

```bash
bash work/isce3_network/run_all.sh
```

并发运行，例如 8 并发：

```bash
bash work/isce3_network/run_parallel.sh work/isce3_network 8
```

## 7. 绘制时空基线图

基线图需要从已生成的 GUNW 产品中读取垂直基线，因此必须在下游网络跑完之后再执行。

命令如下：

```bash
python scripts/plot_isce3_baseline_network.py --network-dir work/isce3_network
```

可选参数：

- `--pair-list`
  - 如果不想使用 `pair_lists/pairs_selected.txt`，可指定其他 pair list
- `--title`
  - 自定义图标题

输出内容位于 `work/isce3_network/pair_lists/`：

- `baseline_network.png`
- `baseline_network.pdf`
- `pair_baselines.csv`
- `scene_baselines.csv`

## 8. 运行 MintPy

### 8.1 推荐方式

直接使用封装脚本：

```bash
bash scripts/run_mintpy_nisar_stack.sh work/mintpy 'work/isce3_network/runs/*/products/*.h5'
```

这个脚本会自动完成：

1. 从 GUNW 产品准备 MintPy 输入
2. 统一公共网格
3. 在 `reference_point` 前施加一次公共有效像元掩膜
4. 生成 `smallbaselineApp.cfg`
5. 先运行到 `reference_point`
6. 在 `reference_point` 后按参考相位再施加一次公共有效像元掩膜
7. 再从 `correct_unwrap_error` 继续运行主流程

这样做是为了绕过当前 MintPy 版本在 `quick_overview` 和 `ifgram_inversion` 两个边界条件下可能触发的报错。

### 8.2 自定义参数

脚本参数为：

```bash
bash scripts/run_mintpy_nisar_stack.sh <work_dir> '<gunw_glob>' <custom_cfg>
```

例如：

```bash
bash scripts/run_mintpy_nisar_stack.sh \
  work/mintpy_tbase24 \
  'work/isce3_tbase24/runs/*/products/*.h5' \
  nisar.txt
```

### 8.3 直接调用 MintPy

如果你想手工调用：

```bash
smallbaselineApp.py --dir work/mintpy nisar.txt
```

不过通常更建议用封装脚本，因为它已经把 NISAR GUNW 的输入准备步骤串好了。

## 9. MintPy 配置说明

仓库默认使用 `nisar.txt` 作为 MintPy 自定义模板，当前默认配置包含：

- `mintpy.plot = yes`
- `mintpy.troposphericDelay.method = no`
- `mintpy.topographicResidual = yes`
- `mintpy.topographicResidual.pixelwiseGeometry = no`

这意味着：

- 默认会生成 `pic/` 图件
- 默认先跳过大气校正
- 默认开启 DEM 残差校正

如果你后续想开启大气校正，可以在 `nisar.txt` 中修改相关参数后重新运行。

## 10. 主要输出结果

### ISCE3 单主影像栈

- `work/isce3_stack/runconfigs/`
- `work/isce3_stack/stack_manifest.csv`
- `work/isce3_stack/reference_date.txt`

### ISCE3 下游网络

- `work/isce3_network/runconfigs/`
- `work/isce3_network/runs/*/products/*.h5`
- `work/isce3_network/pair_lists/baseline_network.png`

### MintPy

- `work/mintpy/timeseries.h5`
- `work/mintpy/timeseries_demErr.h5`
- `work/mintpy/velocity.h5`
- `work/mintpy/velocity.kmz`
- `work/mintpy/temporalCoherence.h5`
- `work/mintpy/maskTempCoh.h5`
- `work/mintpy/pic/`

## 11. 常见注意事项

### 11.1 关于参考景

虽然脚本支持 `--reference auto`，但实际使用时更推荐显式指定参考日期，尤其是：

- 数据时间覆盖较长
- 工作流对负时间基线敏感
- 你希望结果更可复现

当前脚本已经对这类情况做了保护：

- `auto` 默认会选择最早日期
- 如果你手动指定了一个晚于部分影像的参考景，脚本会在生成阶段直接报错，而不会等到 `isce3` 运行时再因负时间基线失败

### 11.2 关于默认构网

当前默认是：

- `network-mode = tbase`
- `max-temporal-baseline-days = 36`

对 12 天重访数据来说，`tbase36` 通常会形成一个较稠密但仍可控的网络。

### 11.3 关于基线图

基线图不是从 pair list 直接画的，而是从实际 GUNW 产品里读取垂直基线，所以：

- 没跑完网络，不能画
- 某个 pair 的产品缺失，会导致绘图报错

### 11.4 关于 MintPy 入口

`run_mintpy_nisar_stack.sh` 默认依赖当前环境中的：

- `python`
- `smallbaselineApp.py`

如果你的命令名不同，可以通过环境变量覆盖：

```bash
PYTHON_BIN=python SMALLBASELINE_BIN=smallbaselineApp.py \
bash scripts/run_mintpy_nisar_stack.sh work/mintpy 'work/isce3_network/runs/*/products/*.h5'
```

## 12. 示例

```bash
python scripts/prepare_isce3_stack.py --reference 20251029
bash work/isce3_stack/run_parallel.sh work/isce3_stack 8

python scripts/prepare_isce3_network.py
bash work/isce3_network/run_parallel.sh work/isce3_network 8

python scripts/plot_isce3_baseline_network.py --network-dir work/isce3_network

bash scripts/run_mintpy_nisar_stack.sh work/mintpy 'work/isce3_network/runs/*/products/*.h5'
```
