# 阶段 2：AI 教练健身化验收

本轮阶段 2 代码和自动化测试已完成，需执行档案字段迁移后进行人工验收。迁移只增加可选列和约束，不删除或重写已有档案；应用不会自动修改数据库。

## 1. 执行档案迁移

在 PowerShell 中运行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'

$pgUser = (docker compose exec -T postgres printenv POSTGRES_USER).Trim()
$pgDb = (docker compose exec -T postgres printenv POSTGRES_DB).Trim()

docker compose cp .\migrations\20261026_02_extend_kh_fitness_profile.sql postgres:/tmp/20261026_02_extend_kh_fitness_profile.sql
docker compose exec -T postgres psql -U $pgUser -d $pgDb -v ON_ERROR_STOP=1 -f /tmp/20261026_02_extend_kh_fitness_profile.sql

docker compose exec -T postgres psql -U $pgUser -d $pgDb -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'kh_fitness_profile' AND column_name IN ('age', 'sex', 'weekly_training_days', 'equipment', 'limitations') ORDER BY column_name;"

docker compose up -d --build aiagent-end
```

查询结果应包含 `age`、`sex`、`weekly_training_days`、`equipment`、`limitations` 五列。若迁移执行失败，先停止后续页面验收并保留完整错误信息；不要手动删表或重建档案表。

## 2. 档案保存和隔离

1. 登录测试账号 A，打开“个人中心/健身档案”。填写年龄、性别、目标、训练经验、每周训练天数、可用器械和身体限制后保存。
2. 刷新页面，确认字段仍显示已保存值。
3. 登录账号 B，确认看不到账号 A 的档案；在 B 保存另一组测试值后切回 A，确认 A 的值未改变。
4. 可选字段留空后保存，确认留空字段保持空值，页面和 AI 不会自行补出年龄、性别、器械或身体限制。

## 3. AI 教练个性化

1. 在账号 A 档案中设置：目标“增肌”、经验“刚开始”、每周训练 3 天、器械“哑铃”、限制“避免跳跃动作”。在 AI 教练中问：“考虑我的器械和身体限制，训练安排需要注意什么？”
2. 回答应考虑已填写的哑铃和避免跳跃；不能声称用户有档案未填写的设备、伤病或其他身体情况。
3. 进入训练计划页面，确认可用器械、每周训练天数和身体限制输入框中直接显示账号档案的实际值，而不只是 placeholder 提示；修改任意值后再次进入该页，手动修改的值应保留。生成一份增肌草稿，确认修改后的值被采用，知识库支持的动作显示对应来源；知识库没有支持的安排应标为“一般建议”，不能伪造引用。生成后仍需用户确认才保存。
4. 登出账号 A 并登录账号 B，确认训练计划表单不残留 A 的档案值，而显示 B 的档案值；B 未填写的字段应保持空白，可手动填写，系统不猜测。
5. 将档案改为另一目标或器械并重新提问/生成，结果应随当前账号档案变化。

普通 JSON 问答和 SSE 流式问答都会从登录账号读取档案；自动化测试覆盖两条调用路径。页面人工验收主要确认当前 AI 教练流式体验。接口仍保持 `{content, sources}` 和既有 SSE 事件格式，本阶段没有引入新的结构化 JSON 回答协议。

## 4. 本次实现范围

- 健身安全提示词、知识来源边界和用户档案作为非指令背景数据。
- 档案新增五个可选字段，并通过增量 SQL 迁移写入 PostgreSQL。
- 普通问答、SSE 流式问答及 AI 训练计划草稿读取当前登录账号档案。
- 自动化测试覆盖档案校验、账号身份来源、问答消息上下文和计划来源过滤。

验收完成后请记录迁移执行结果、账号 A/B 隔离结果及 AI 个性化回答结果。阶段 5 和阶段 9 在你确认阶段 2、7.2 验收之前不会继续实施。
