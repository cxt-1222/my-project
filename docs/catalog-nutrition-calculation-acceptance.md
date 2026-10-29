# 目录营养计算验收

## 计量规则

- 食材响应始终保留来源声明的原始计量基准和原始营养字段。
- 仅当原始基准明确为 `per_100g` 时，响应中的 `nutrition.per_100g` 才提供每 100 克值。
- `per_serving`、`other` 或未知基准没有可靠克重依据，不自动换算，规范化的每 100 克值为 `null`。
- 菜谱仅使用状态为 `active`、许可为 `approved`，且所属导入批次已完成的食材。
- 菜谱食材必须具有明确数量和可换算为克的单位；当前支持 `g`、`克`、`kg`、`千克`。
- 菜谱计算使用 Python `Decimal`，不经过浮点数；最终值按 `ROUND_HALF_UP` 保留 6 位小数。

## 计算公式

```text
某营养素总和 = Σ(食材每 100 克值 × 食材克数 ÷ 100)
每份营养素 = 营养素总和 ÷ 菜谱份数
```

### 不完整数据

以下任一情况都会令受影响营养素的合计为 `null`，并将菜谱标记为
`nutrition.complete = false`：

- 食材未匹配或匹配关系尚未获准；
- 关联食材已停用、未获准或不属于已完成的导入批次；
- 食材数量缺失、无效或单位无法可靠换算为克；
- 食材营养基准不是 `per_100g`；
- 任一食材缺少对应营养字段。

不会用部分食材合计冒充完整菜谱营养，也不会调用 AI 补估缺失数值。

## 自动化验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_catalog.py tests\test_nutrition_catalog.py -q
```

## 接口检查

登录后请求：

```text
GET /catalog/foods?exact_name=true&query=燕麦
GET /catalog/recipes?exact_name=true&query=燕麦粥
```

应核对：

1. `source.dataset`、`source.revision` 和 `source.source_record_id` 可追溯。
2. 食材的 `nutrition.basis` 与原始基准一致。
3. 不可换算的食材不出现 `nutrition.per_100g` 数值。
4. 菜谱的 `nutrition.total`、`nutrition.per_serving` 和 `nutrition.complete` 与公式一致。
5. 缺少食材时 `nutrition.missing_ingredients` 包含位置、名称和具体原因。
