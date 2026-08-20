# prompts/ 状态说明

> 更新: 2026-08-20（架构评审 #14，第 4 批）

`01_researcher.md ~ 05_chief_editor.md` 是**五角色 Agent 流水线的设计稿**
（对应接口 IF-003 与《接口定义总览.md》），定义了
ResearchEvent → FactCheckedEvent → ClassifiedEvent → ReportItem → DailyReport 的完整链路。

**当前实现（V1）的职责映射**：

| 设计稿角色 | V1 实际承担者 | 位置 |
|-----------|--------------|------|
| 01 研究员 + 03 分类器 + 04 编辑 | AnalystAgent（一体化，内联 prompt） | app/agents/pipeline.py |
| 02 事实核查员 | ground_key_data（确定性溯源）+ FactCheckerAgent（≥85 分 LLM 复核） | app/agents/factcheck.py |
| 05 总编辑 | ChiefEditorAgent（Python 做排序/栏目，LLM 只写导读） | app/agents/pipeline.py |

- app/agents/base.py 的 BaseAgent 会自动加载本目录 prompt 文件，
  供未来按设计稿拆分角色时直接继承使用。
- 设计稿对应的中间模型（ResearchEvent/FactCheckedEvent/ClassifiedEvent）
  已于第 4 批从 app/schemas/models.py 移除；若实现完整五角色流水线，
  需按设计稿重新引入。
