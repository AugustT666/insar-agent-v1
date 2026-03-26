# insar-agent 交互工作流展示

本文展示用户、Claude Code（AI）和 insar-agent MCP 服务三方协作完成 NISAR InSAR 处理的完整交互过程。

---

## 一、三方角色

```
┌─────────────────────────────────────────────────────────┐
│                      用户（领域专家）                        │
│  提供：RSLC 路径、DEM、工作目录、conda 环境名                  │
│  接收：处理结果、日志摘要、输出文件列表                          │
└──────────────────────┬──────────────────────────────────┘
                       │  自然语言指令
                       ▼
┌─────────────────────────────────────────────────────────┐
│                 Claude Code（AI）                         │
│  加载 Skill → 读取约束 → 拆解步骤 → 调用 MCP 工具             │
│  解析返回值 → 汇报状态 → 轮询作业 → 摘要错误日志               │
└──────────────────────┬──────────────────────────────────┘
                       │  MCP 工具调用（stdio JSON-RPC）
                       ▼
┌─────────────────────────────────────────────────────────┐
│              insar-agent MCP Server                      │
│  工具：insar_create_project / set / validate / export /  │
│        run_workflow / get_job_status / get_job_logs /    │
│        list_outputs / prepare_stack / prepare_network /  │
│        extract_bbox / export_geotiff                     │
│  资源：insar://workflow-guide                             │
│         insar://allowed-fields/{workflow}                │
│  引擎：ISCE3 Adapter → conda run nisar.workflows.*       │
└─────────────────────────────────────────────────────────┘
```

---

## 二、会话启动：Skill 加载与约束读取

每次会话开始时，Claude 自动触发 `insar-agent` skill，读取工作流约束资源。

```
用户：帮我处理一对 NISAR RSLC 数据

  ↓ Claude 识别任务类型，触发 Skill

Claude → Skill("insar-agent-skills:insar-agent")
         读取路由表：单对 → d-insar-isce3

Claude → Skill("insar-agent-skills:d-insar-isce3")
         加载完整步骤约束：create → set×6 → validate → export → run → poll → list

Claude → 向用户确认缺失信息：
         "请提供：参考 RSLC 路径、辅助 RSLC 路径、DEM 路径、输出目录、conda 环境名"
```

---

## 三、MCP 内部执行链条

当 AI 调用一个 MCP 工具时，`insar-agent` MCP server（一个本地 Python 进程）内部发生以下事情：

### 3.1 `insar_run_workflow` 调用链

```
AI 发出调用
  {"tool": "insar_run_workflow", "args": {"project_id": "proj-abc"}}
  ↓
server.py: insar_run_workflow()
  1. Project.load("proj-abc")
     → 从 ~/.local/share/insar_agent/registry.json 查找
     → 加载 workspace_root、conda_env、runconfig_exported_path
  2. 检查 runconfig_exported_path 文件是否存在于磁盘
  3. validate_runconfig() — 再次校验必填路径字段
  4. build_workflow_command()
     → 构造：conda run -n <env> python -m nisar.workflows.insar /workspace/runconfig.yaml
  5. subprocess.Popen(command, stdout=log_file, stderr=STDOUT, cwd=workspace_root)
     → ISCE3 开始在后台运行，进程句柄存入内存
     → 返回 job_id（UUID）
  ↓
返回给 AI：
  {"job_id": "job-xyz", "status": "running",
   "poll": "insar_get_job_status(job_id='job-xyz', project_id='proj-abc')"}
```

### 3.2 `insar_get_job_status` 轮询链

```
AI 发出调用：{"tool": "insar_get_job_status", "args": {"job_id": "job-xyz", ...}}
  ↓
server.py: insar_get_job_status()
  1. Job.load("job-xyz", project.jobs_dir())
     → 从 <workspace>/jobs/job-xyz.json 读取 Job 对象
  2. 检查关联进程（job.exit_code / job.status）
     → None   = 还在运行 → status: "running"
     → 0      = 正常退出 → status: "done"
     → 非 0   = 错误退出 → status: "failed"
  ↓
返回：{"job_id": "job-xyz", "status": "running", "elapsed": "2m30s", ...}
```

### 3.3 `insar_set_runconfig_value` 内部链

```
AI 发出调用：{"tool": "insar_set_runconfig_value",
              "args": {"project_id": "proj-abc",
                       "key": "runconfig.groups.input_file_group.reference_rslc_file",
                       "value": "/data/ref.h5"}}
  ↓
server.py: insar_set_runconfig_value()
  1. 检查 key 是否在 ALLOWED_SET_FIELDS["insar"] 白名单
     → 不在 → 立即返回 {"error": "key_not_allowed", ...}（无法绕过）
  2. set_path(project.runconfig, key, value)
     → 按 . 分割键名，逐层遍历 runconfig dict，写入目标值
     → runconfig 保留在内存（Python dict）
  3. project.save()
     → 将整个 Project 序列化为 JSON，写入 <workspace>/project.json
  ↓
返回：{"project_id": "proj-abc", "key": "...", "value": "/data/ref.h5", "updated_at": "..."}
```

**关键点：** MCP server 是运行在用户本地机器上的 Python 进程。它操作本地文件系统、启动真实的 conda 进程、管理作业状态。AI 只看到 JSON 结果，看不到文件系统或 conda 环境。

---

## 四、Path A — 单对 D-InSAR（GUNW 产品）

**场景：** 用户有一对 RSLC 文件，要生成 GUNW 干涉图产品。

```mermaid
sequenceDiagram
    actor User as 用户
    participant AI as Claude Code
    participant MCP as insar-agent MCP
    participant ISCE3 as ISCE3 (conda)

    User->>AI: 处理 ref.h5 + sec.h5，输出到 /workspace，环境 isce3_env

    AI->>MCP: insar_create_project(engine="isce3", workflow="insar",<br/>workspace_root="/workspace", conda_env="isce3_env")
    MCP-->>AI: {project_id: "proj-abc", next_step: "set required fields"}

    AI->>MCP: insar_set_runconfig_value(project_id, "...reference_rslc_file", "/data/ref.h5")
    AI->>MCP: insar_set_runconfig_value(project_id, "...secondary_rslc_file", "/data/sec.h5")
    AI->>MCP: insar_set_runconfig_value(project_id, "...dem_file", "/data/dem.tif")
    AI->>MCP: insar_set_runconfig_value(project_id, "...product_path", "/workspace/outputs")
    AI->>MCP: insar_set_runconfig_value(project_id, "...scratch_path", "/workspace/scratch")
    AI->>MCP: insar_set_runconfig_value(project_id, "...sas_output_file", "GUNW_product.h5")
    MCP-->>AI: {status: "ok"} × 6

    AI->>MCP: insar_validate_runconfig(project_id)
    MCP-->>AI: {valid: true, next_step: "export runconfig"}

    AI->>MCP: insar_export_runconfig(project_id)
    MCP-->>AI: {path: "/workspace/runconfig.yaml", next_step: "run workflow"}

    AI->>MCP: insar_run_workflow(project_id)
    MCP->>ISCE3: conda run -n isce3_env python -m nisar.workflows.insar /workspace/runconfig.yaml
    MCP-->>AI: {job_id: "job-xyz", status: "running"}

    loop 每 30 秒轮询
        AI->>MCP: insar_get_job_status(job_id, project_id)
        MCP-->>AI: {status: "running", elapsed: "2m30s"}
    end

    MCP-->>AI: {status: "done"}

    AI->>MCP: insar_list_outputs(job_id, project_id)
    MCP-->>AI: {artifacts: ["GUNW_product.h5", "wrapped_phase.tif", "coherence.tif", "unwrapped_phase.tif"]}

    AI-->>User: 处理完成！输出目录：/workspace/outputs\n产品文件：GUNW_product.h5\n辅助文件：相位图、相干图、解缠相位图
```

---

## 四、Path B — 多景 Stack-InSAR（干涉图网络）

**场景：** 用户有一个目录的 RSLC 文件，要批量生成干涉图网络供 MintPy 时序分析。

```mermaid
sequenceDiagram
    actor User as 用户
    participant AI as Claude Code
    participant MCP as insar-agent MCP
    participant Shell as 用户本地 Shell

    User->>AI: 批量处理 /data/rslc/ 下所有 RSLC，时间基线阈值 36 天，并行 4 核

    AI->>MCP: insar_prepare_stack(data_dir="/data/rslc",<br/>base_runconfig="/data/insar_nisar.yaml",<br/>dem="/data/dem.tif", output_dir="/workspace/stack")
    MCP-->>AI: {n_secondary: 11, reference: "20240101",<br/>script: "/workspace/stack/run_parallel.sh",<br/>next_step: "user must run the shell script"}

    AI-->>User: Step 1 准备完成（11 景辅场景，参考日期 20240101）\n请执行：\nbash /workspace/stack/run_parallel.sh /workspace/stack 4

    User->>Shell: bash /workspace/stack/run_parallel.sh /workspace/stack 4
    Note over Shell: 并行运行 11 个单参考 insar 作业

    User->>AI: 运行完毕

    AI->>MCP: insar_prepare_network(data_dir="/data/rslc",<br/>base_runconfig="/data/insar_nisar.yaml",<br/>dem="/data/dem.tif", output_dir="/workspace/network",<br/>network_mode="tbase", max_temporal_baseline_days=36)
    MCP-->>AI: {n_pairs: 23, run_command: "bash /workspace/network/run_parallel.sh /workspace/network <N>",<br/>pair_list: "/workspace/network/pairs_manifest.txt",<br/>gunw_pattern: "/workspace/network/runs/*/products/*.h5"}

    AI-->>User: Step 2 准备完成（23 对干涉图，tbase ≤ 36 天）\n请执行：\nbash /workspace/network/run_parallel.sh /workspace/network 4

    User->>Shell: bash /workspace/network/run_parallel.sh /workspace/network 4
    Note over Shell: 并行运行 23 个干涉图对 insar 作业

    User->>AI: 全部完成

    AI-->>User: 输出结构：\n/workspace/network/runs/<日期对>/products/GUNW_*.h5\n共 23 个产品，可送入 MintPy 时序分析
```

---

## 五、错误处理：被锁参数 vs. 路径错误

### 5.1 核心参数被锁（key_not_allowed）

```
用户：把多视次数改成 5×5

  ↓ Claude 调用 MCP 工具

Claude → MCP: insar_set_runconfig_value(project_id,
               "runconfig.groups.processing.crossmul.range_looks", 5)

MCP → Claude: {error: "key_not_allowed"}

Claude → 用户：
  "multilook 参数属于核心处理参数，MCP 服务器禁止通过工具修改。
   这类参数会影响处理精度和可复现性。
   我可以告诉你它在 runconfig 中的路径，但需要您手动编辑 YAML 文件并确认。"
```

### 5.2 路径错误（path_not_found）

```
用户：参考 RSLC 路径填 /data/ref_typo.h5

  ↓
MCP → Claude: {error: "path_not_found",
               field: "reference_rslc_file",
               value: "/data/ref_typo.h5"}

Claude → 用户：
  "路径 /data/ref_typo.h5 不存在，请确认文件路径后重新提供。"

  ↓ 用户更正后
Claude → MCP: insar_set_runconfig_value(..., "/data/ref.h5")
MCP → Claude: {status: "ok"}
```

### 5.3 作业失败（日志摘要）

```
MCP → Claude: {status: "failed", job_id: "job-xyz"}

Claude → MCP: insar_get_job_logs(job_id, project_id, tail=50)
MCP → Claude: {logs: "...ERROR: DEM does not cover scene extent..."}

Claude → 用户：
  "作业失败，关键错误：DEM 覆盖范围不足，未覆盖全部场景范围。
   建议：重新下载覆盖更大范围的 DEM，然后重新提交。
   核心处理参数未涉及，您无需手动修改 runconfig。"
```

---

## 六、数据准备（data-prep-nisar skill）

当用户缺少 DEM 时，AI 自动切换到数据准备流程：

```
用户：我还没有 DEM

Claude → Skill("insar-agent-skills:data-prep-nisar")

Claude → MCP: insar_extract_bbox(rslc_paths=["/data/rslc/ref.h5", "/data/rslc/sec.h5"])
         ← 返回：{min_lon: 120.5, min_lat: 35.2, max_lon: 121.3, max_lat: 36.0}

Claude → 用户：
  "Step B2：下载 Copernicus 30m DEM"
  请执行：
  python knowledge-base/wangshuai/Scripts/ddem.py \
      --min-lon 120.5 --max-lon 121.3 \
      --min-lat 35.2  --max-lat 36.0 \
      --source copernicus_30 \
      -o /data/dem.tif

用户 → 确认文件已生成

Claude → 继续 d-insar-isce3 或 stack-insar-isce3 主流程
```

---

## 七、约束传播层次

```
弱 ──────────────────────────────── 强
│                                      │
│  skills/*.md              key_not_allowed
│  （工作流唯一指引来源）     （服务器硬拒绝，无法绕过）
```

**核心原则：**
- Skills 是工作流步骤和顺序的唯一来源。MCP 工具只执行动作、返回事实性结果。
- Claude **只修改路径类字段**（input、output、DEM、scratch 路径）
- 所有核心处理参数（multilook、filtering、unwrapping）**由用户手动编辑** runconfig YAML
- MCP 服务器是最终执行层，`key_not_allowed` 错误无法绕过

---

## 八、文件关系速查

| 组件 | 路径 | 作用 |
|------|------|------|
| MCP 服务 | `src/insar_agent/mcp/server.py` | 工具/资源/提示定义，JSON-RPC 入口 |
| ISCE3 适配器 | `src/insar_agent/engines/isce3/` | runconfig 验证、conda run 命令构造 |
| 工具扩展（M5） | `src/insar_agent/engines/isce3/bbox.py` + `geotiff.py` | 包围盒提取、GeoTIFF 导出 |
| 约束文档 | `docs/agent-guide.md` | 硬规则文档 = `insar://workflow-guide` 资源内容（server.py 直接读取） |
| Skill 路由 | `skills/insar-agent/SKILL.md` | 任务 → skill 映射表 |
| Path A Skill | `skills/d-insar-isce3/SKILL.md` | 单对流程步骤约束 |
| Path B Skill | `skills/stack-insar-isce3/SKILL.md` | 批量流程步骤约束 |
| 数据准备 Skill | `skills/data-prep-nisar/SKILL.md` | DEM + RSLC 准备流程 |
| 环境安装 Skill | `skills/env-setup-nisar/SKILL.md` | ISCE3 + MCP 安装指引（占位） |
