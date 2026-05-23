# 指标采集

## 采集命令（新 run-root 格式）

每个任务完成或失败后运行（`run_id` 和 `run_root` 从 `insar_run_workflow` 返回值获取）：

```bash
python /home/august/insar-agent/scripts/collect_experiment_metrics.py \
  --experiment-id <E2|E3|E4> \
  --engine <isce3|isce2> \
  --workflow <DInSAR|StackInSAR> \
  --workspace /mnt/HDD2T/August/insar-agent-integration-test/workspace \
  --metrics-csv /mnt/HDD2T/August/insar-agent-integration-test/metrics/experiment_log.csv \
  --status <completed|failed> \
  --notes "<短注记，如 '5x5 multilook, snaphu nlooks=5'>" \
  --project-id <project_id> \
  --job-id <job_id> \
  --task-id <E2|E3|E4> \
  --run-id <run_id> \
  --run-root <run_root>
```

---

## 各任务参数速查

### E2 — Sentinel-1 / ISCE2 / D-InSAR

```bash
  --experiment-id E2 \
  --engine isce2 \
  --workflow DInSAR \
  --task-id E2
```

### E3 — NISAR / ISCE3 / Stack-InSAR + MintPy

```bash
  --experiment-id E3 \
  --engine isce3 \
  --workflow StackInSAR \
  --task-id E3
```

### E4 — Sentinel-1 / ISCE2 / Stack-InSAR + MintPy

```bash
  --experiment-id E4 \
  --engine isce2 \
  --workflow StackInSAR \
  --task-id E4
```

---

## 输出文件

| 文件 | 内容 |
|------|------|
| `<run_root>/metrics/product_metrics.json` | 产品指标（coherence_mean、unwrapped_rms 等） |
| `<run_root>/metrics/experiment_metrics.json` | 实验级记录（含 paper/thesis 字段） |
| `metrics/experiment_log.csv` | 跨任务汇总表（追加写入，保留历史记录） |

传入 `--run-root` 时，指标脚本只统计该 run_root 下的文件；不要回退扫描 `workspace/outputs/<experiment_id>`，否则会把同一 task 下失败 run 的中间文件混入成功记录。

---

## 指标表字段

```
experiment_id, engine, workflow, start_time, end_time, duration_s,
tool_calls, param_advisor_calls, user_interventions,
coherence_mean, coherence_median, unwrapped_rms,
temporal_coherence_mean, velocity_rms_mm_yr,
peak_memory_gb, output_size_gb, status, notes
```

---

## 兼容旧格式（历史 run 可用）

```bash
  --output-root <run_root> \
  --metrics-json <run_root>/metrics/experiment_metrics.json
```

---

## 查看汇总表

```bash
column -t -s, metrics/experiment_log.csv | less -S
```
