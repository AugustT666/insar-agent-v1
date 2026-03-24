# ISCE3 InSAR 工作流说明

> **维护说明**：本文档由用户（InSAR 领域专家）填写。Claude 会读取本文档中的内容，将其转化为 `engines/isce3/` 中的代码（默认配置、参数校验、命令构建）。
>
> 请在每个 `TODO` 处填写你的实际知识。内容不需要是正式的技术文档，操作笔记、脚本注释、口述说明都可以。

---

## 一、工作流用途

**工作流名称：** `insar`
**ISCE3 模块：** `nisar.workflows.insar`
**调用命令：** `python -m nisar.workflows.insar <runconfig.yaml>`

**用途说明：**

> TODO：用一两句话说明这个工作流做什么、适合什么场景、输出什么产品。
>
> 示例：从两景 RSLC（参考景和辅景）生成干涉图，包括相干性图、缠绕相位和解缠相位。适合地表形变监测、地震同震形变分析等场景。

---

## 二、输入数据要求

### 2.1 参考景（Reference RSLC）

> TODO：说明参考景的文件格式、命名约定、路径要求。

| 项目 | 说明 |
|---|---|
| 文件格式 | TODO（HDF5 / .h5） |
| 文件命名示例 | TODO |
| 路径约定 | TODO |
| 其他要求 | TODO |

### 2.2 辅景（Secondary RSLC）

> TODO：说明辅景的要求，与参考景的不同之处。

| 项目 | 说明 |
|---|---|
| 文件格式 | TODO |
| 与参考景的时间间隔要求 | TODO |
| 其他要求 | TODO |

### 2.3 DEM（数字高程模型）

> TODO：说明 DEM 的格式、坐标系要求、分辨率建议。

| 项目 | 说明 |
|---|---|
| 文件格式 | TODO（GeoTIFF / HDF5） |
| 坐标系 | TODO |
| 分辨率建议 | TODO |
| 覆盖范围要求 | TODO |

### 2.4 其他可选输入

> TODO：如有轨道文件、电离层校正文件等，在此说明。

---

## 三、关键 runconfig 参数

> TODO：列出最重要的参数，说明每个参数的作用和典型取值。
>
> 按照 ISCE3 runconfig 的分组结构组织（groups 下的各个子节）。
> 不需要列出所有参数，重点列出：
> - 必须设置的参数（不设置会报错）
> - 常用调整的参数（影响结果质量或运行效率）
> - 容易出错的参数

### 3.1 input_file_group（输入文件）

| 参数路径 | 类型 | 是否必填 | 说明 | 典型值 |
|---|---|---|---|---|
| `runconfig.groups.input_file_group.reference_rslc_file` | string | 必填 | TODO | `/data/ref.h5` |
| `runconfig.groups.input_file_group.secondary_rslc_file` | string | 必填 | TODO | `/data/sec.h5` |
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
| `runconfig.groups.worker.num_process_frames` | integer | 否 | TODO | TODO |
| TODO | | | | |

### 3.5 其他重要参数组

> TODO：如有其他重要参数组（如 processing, geometry 等），在此补充。

---

## 四、输出产物

> TODO：列出这个工作流会生成哪些文件，每个文件是什么、有什么用。

| 文件名或模式 | 格式 | 含义 | 推荐查看工具 |
|---|---|---|---|
| TODO | HDF5 | TODO | h5py / QGIS |
| TODO | GeoTIFF | TODO | QGIS / GDAL |
| TODO | | | |

**输出目录结构：**

```
TODO：描述输出目录的典型结构，例如：

product_path/
  interferogram/
    wrapped_phase.h5
    coherence.h5
  unwrapped/
    unwrapped_phase.h5
```

---

## 五、常见错误与排查

> TODO：记录你在实际使用中遇到的常见错误，以及解决方法。
> 这些内容之后会被用来生成 `insar_validate_runconfig` 的校验规则和错误提示。

### 错误 1

**现象：** TODO
**原因：** TODO
**解决方法：** TODO

### 错误 2

**现象：** TODO
**原因：** TODO
**解决方法：** TODO

---

## 六、示例 runconfig

> TODO：粘贴一个最小可用的 runconfig YAML 示例（可以脱敏，用占位路径替换真实路径）。
> 这个示例之后会作为 `insar_create_project` 的默认模板。

```yaml
# TODO：粘贴示例 runconfig
runconfig:
  name: insar
  groups:
    input_file_group:
      reference_rslc_file: /path/to/reference.h5
      secondary_rslc_file: /path/to/secondary.h5
    # ... 其余内容待填写
```

---

## 七、备注

> TODO：其他需要记录的操作经验，例如：
> - 典型的运行时长
> - 对硬件的要求（内存、磁盘空间）
> - 与其他工作流的依赖关系（如 insar 是否需要先跑 gslc）
> - 已知的版本差异或 bug
