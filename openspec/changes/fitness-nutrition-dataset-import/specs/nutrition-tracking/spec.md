## MODIFIED Requirements

（修改现有需求；英文标题和场景标识保留，以便 OpenSpec 与原规格对应。固定标记说明：MUST 表示“必须”，MUST NOT 表示“不得”，WHEN 表示“当……时”，THEN 表示“则……”。）

### Requirement: Users can create and manage private nutrition records
（用户可以创建和管理自己的饮食记录）
系统 MUST（必须）允许已登录用户创建、查看、更新和删除归属自己的饮食记录。每条记录 MUST（必须）包含日期、餐次、食物名称、数量和单位、千卡热量，以及克为单位的蛋白质、碳水化合物和脂肪。营养值可以由用户填写，也可以从已批准且标注来源的食材或菜谱目录中预填；但用户 MUST（必须）能够检查和修改这些数值，并且 MUST（必须）明确确认后才能保存。系统 MUST NOT（不得）静默推断或替换数值。请求 MUST NOT（不得）指定或更改记录所属用户。读取或修改其他用户的记录时 MUST（必须）返回“未找到”。

#### Scenario: Create a nutrition record
（创建饮食记录）
- **WHEN** 已登录用户提交有效的食物、日期、餐次、数量和营养值
- **THEN** 系统将记录保存到当前账号并返回已保存的数值

#### Scenario: Create a nutrition record from a confirmed catalog draft
（确认目录预填内容后创建饮食记录）
- **WHEN** 已登录用户选择一条已批准的目录记录、检查来源和数值，并明确提交完整表单
- **THEN** 系统将已确认的数值保存到当前账号

#### Scenario: Reject invalid nutrition data
（拒绝无效营养数据）
- **WHEN** 请求的食物名称为空、日期或餐次无效、数量不是正数、营养值为负数，或包含不支持的字段
- **THEN** 系统拒绝请求且不保存记录

#### Scenario: List records for a selected date
（查看指定日期的记录）
- **WHEN** 已登录用户请求查看某个日期的饮食记录
- **THEN** 系统按稳定的时间顺序，只返回该用户当天的记录

#### Scenario: Update or delete an owned record
（更新或删除自己的记录）
- **WHEN** 已登录用户更新或删除自己的其中一条记录
- **THEN** 系统只修改或删除该记录，之后的查询会反映此更改

#### Scenario: Prevent cross-account access
（阻止跨账号访问）
- **WHEN** 用户尝试读取、更新或删除其他用户的记录，或访问不存在的记录
- **THEN** 系统返回“未找到”，并且不更改任何记录
