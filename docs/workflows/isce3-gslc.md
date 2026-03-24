# ISCE3 GSLC 工作流说明

> **维护说明**：本文档由用户（InSAR 领域专家）填写。Claude 会读取本文档中的内容，将其转化为 `engines/isce3/` 中的代码（默认配置、参数校验、命令构建）。
>
> 请在每个 `TODO` 处填写你的实际知识。内容不需要是正式的技术文档，操作笔记、脚本注释、口述说明都可以。

---

## 一、工作流用途

**工作流名称：** `gslc`
**ISCE3 模块：** `nisar.workflows.gslc`
**调用命令：** `python -m nisar.workflows.gslc <runconfig.yaml>`

**用途说明：**

> TODO：用一两句话说明这个工作流做什么、适合什么场景、输出什么产品。
>
> 示例：将 RSLC（Range-compressed SLC）产品投影到地理坐标系，生成 GSLC（Geocoded SLC）产品。常作为 InSAR 处理链的前置步骤，也可单独用于地理编码验证。

---

## 二、输入数据要求

### 2.1 输入 RSLC

> TODO：说明 RSLC 输入文件的格式、命名约定、路径要求。

| 项目 | 说明 |
|---|---|
| 文件格式 | TODO（HDF5 / .h5） |
| 文件命名示例 | TODO |
| 路径约定 | TODO |
| 其他要求 | TODO |

### 2.2 DEM（数字高程模型）

> TODO：说明 DEM 的格式、坐标系要求、分辨率建议。

| 项目 | 说明 |
|---|---|
| 文件格式 | TODO（GeoTIFF / HDF5） |
| 坐标系 | TODO |
| 分辨率建议 | TODO |
| 覆盖范围要求 | TODO |

### 2.3 其他可选输入

> TODO：如有轨道文件等，在此说明。

---

## 三、关键 runconfig 参数

> TODO：列出最重要的参数，说明每个参数的作用和典型取值。
>
> 重点列出：
> - 必须设置的参数
> - 常用调整的参数
> - 容易出错的参数

### 3.1 input_file_group（输入文件）

| 参数路径 | 类型 | 是否必填 | 说明 | 典型值 |
|---|---|---|---|---|
| `runconfig.groups.input_file_group.input_file_path` | string | 必填 | TODO | `/data/rslc.h5` |
| TODO | | | | |

### 3.2 dynamic_ancillary_file_group（辅助数据）

| 参数路径 | 类型 | 是否必填 | 说明 | 典型值 |
|---|---|---|---|---|
| `runconfig.groups.dynamic_ancillary_file_group.dem_file` | string | 必填 | TODO | `/data/dem.tif` |
| TODO | | | | |

### 3.3 product_path_group（输出路径）

| 参数路径 | 类型 | 是否必填 | 说明 | 典型值 |
|---|---|---|---|---|
| `runconfig.groups.product_path_group.product_path` | string | 必填 | TODO | `/output/` |
| `runconfig.groups.product_path_group.scratch_path` | string | 建议设置 | TODO | `/scratch/` |
| TODO | | | | |

### 3.4 worker（计算资源）

| 参数路径 | 类型 | 是否必填 | 说明 | 典型值 |
|---|---|---|---|---|
| `runconfig.groups.worker.gpu_enabled` | boolean | 否 | 是否启用 GPU | `false` |
| TODO | | | | |

### 3.5 其他重要参数组

> TODO：如有其他重要参数组，在此补充。

---

## 四、输出产物

> TODO：列出这个工作流会生成哪些文件，每个文件是什么、有什么用。

| 文件名或模式 | 格式 | 含义 | 推荐查看工具 |
|---|---|---|---|
| TODO | HDF5 | GSLC 产品 | h5py / QGIS |
| TODO | | | |

**输出目录结构：**

```
TODO：描述输出目录的典型结构
```

---

## 五、常见错误与排查

> TODO：记录实际使用中遇到的常见错误及解决方法。

### 错误 1

**现象：** TODO
**原因：** TODO
**解决方法：** TODO

---

## 六、示例 runconfig

> TODO：粘贴一个最小可用的 runconfig YAML 示例。

```yaml
# TODO：粘贴示例 runconfig
runconfig:
  name: gslc
  groups:
    input_file_group:
      input_file_path: /path/to/rslc.h5
    # ... 其余内容待填写
```

---

## 七、备注

> TODO：其他需要记录的操作经验，例如：
> - 与 insar 工作流的关系（是否作为 insar 的前置步骤）
> - 典型运行时长和硬件要求
> - 已知的版本差异或 bug
