# Draft: README/Docs Update + Project Intro Webpage

## Task Summary
1. 更新 README.md 和 docs/architecture.md（修正过时信息，补充 ISCE2 引擎）
2. 创建项目介绍网页，包含：
   - 架构拓扑图（User ↔ LLM ↔ Agent Client ↔ MCP Server ↔ Engines）
   - NISAR 线 D-InSAR 和 Stack InSAR 工作流动画
   - 局域网体验跳转链接 http://10.100.170.117:4096/

## Exploration Findings

### README Issues (confirmed from dev-plan.md 2026-04-05 review)
- "17 FastMCP tools" → should be **18**
- System description only mentions ISCE3/NISAR, missing ISCE2/Sentinel-1
- Quick Start uses PYTHONPATH workaround, should mention `pip install -e`

### Architecture Issues
- System Layers only shows `engines.isce3`, missing `engines.isce2`
- No mention of `insar_agent.runtime` layer

### Project Stats (current)
- 18 MCP tools, 2 resources, 2 prompts
- 11 skills (insar-agent entry + 10 workflow skills)
- 2 engines: ISCE3 (NISAR) + ISCE2 (Sentinel-1)
- 237 tests passing

### Webpage Design Requirements
- No existing frontend assets — build from scratch
- Architecture topology: User → LLM → Agent Client → MCP Server → Core → Engines → Conda
- Workflow animations: Path A (D-InSAR, 6 steps) and Path B (Stack InSAR, 6 steps)
- Link: http://10.100.170.117:4096/ (局域网体验)

## Open Questions
- [ ] 网页技术选型？
- [ ] 设计风格？
- [ ] 语言？
- [ ] 放置路径？
