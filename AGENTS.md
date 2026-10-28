<!-- gitnexus:start -->
# GitNexus — Code Intelligence

GitNexus 用于辅助理解代码关系、调用链和执行流程，**按改动范围使用，不是每次改代码的必经门禁**。

## 何时使用

**建议使用：**跨多个模块/分层的功能改造；模块迁移、重构、拆分、移动或重命名；可能影响多个调用方的公共接口、鉴权、共享数据结构、数据库逻辑；需要追踪架构、执行流程或改动影响范围。

**通常跳过：**文档和注释、格式或配置说明、局部样式/文案、调用关系明确的单文件小修，以及不影响运行代码的测试数据调整。

小改动若涉及鉴权、共享接口、数据库结构等高影响区域，只对关键符号做一次定向分析。

## 使用流程（仅适用于上述需要分析的改动）

1. 修改前按目的选择 `query`（概念/流程）、`context`（符号详情）或 `impact`（影响范围），只查本次涉及的关键部分。
2. HIGH/CRITICAL 风险先确认影响再谨慎修改。`UNKNOWN` 不是低风险；用定向搜索和代码检查补充确认。
3. 实现中不重复分析；只有改动范围扩大或发现新的关键调用方时才补查。
4. 有实质性代码改动时，提交前可运行一次 `detect-changes`；纯文档、格式等无运行行为变化的改动跳过。比较主分支时使用 `--scope compare --base-ref main`。
5. GitNexus 不可用时不要反复重试：低风险改动用定向搜索和测试验证；高风险改动人工追踪调用方，并说明分析限制。

## CLI 参考

在项目根目录运行。PowerShell 若将查询短语拆成多个参数，概念查询改用 GitNexus MCP `query`，不要反复重试 CLI。

```powershell
node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .
node .gitnexus/run.cjs detect-changes --scope all --repo .
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo .
```

索引过期时，**仅在确实需要图分析时**运行 `node .gitnexus/run.cjs analyze --index-only`。`partial` / `truncated` 结果不完整，需补充检查。

## 参考

- MCP 资源：`gitnexus://repo/knowledge-agent/context`、`clusters`、`processes`、`process/{name}`。
- 通用技能：`.claude/skills/gitnexus-{exploring,impact-analysis,debugging,refactoring,guide,cli}/SKILL.md`。
- 区域技能：`.claude/skills/gitnexus-area-*/SKILL.md`。
<!-- gitnexus:end -->
