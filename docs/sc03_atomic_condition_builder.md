# SC03-A 可搜索原子条件目录与组合选股编辑器

## 目标

SC03-A 将完全自由的自然语言选股收敛为可搜索、可参数化、可审计的条件积木。用户输入
“成交额50亿”或“近5日涨停”等关键词后，从系统登记的原子条件中选择，再用“全部满足
（AND）”或“任一满足（OR）”组合。系统不会执行用户代码、SQL、文件、网络或交易指令。

## 条件目录

每个条件包含稳定的 `condition_key`、中文名称、说明、别名、分类、版本、参数元数据、
行情字段和历史窗口。参数元数据包含类型、默认值、上下界、业务与展示单位、精度、
占位提示和帮助文案。计算器只能由后端登记，客户端不能指定或上传。

目录接口：

- `GET /api/v1/screening-conditions`
- `GET /api/v1/screening-conditions/{condition_key}`
- `/api/v1/research/...` 下的相同只读别名路由

列表接口支持 `query`、`category`、`limit` 和 `offset`。

## 近期涨停事件

`RECENT_LIMIT_UP_EVENT` 判断最近共同市场交易日窗口内是否出现指定次数的可靠涨停。
参数为回看交易日数、最少次数、事件选择方式和是否要求可靠涨停价。窗口以交易日历
为准；停牌不伪造K线。无法取得正式涨停价时返回 `INDETERMINATE`，不会按固定比例猜测。

## 首板断板缩量回调

目录键 `FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK` 可用“首板”“次日断板”“三日不破”、
“四日不破”或“缩量回调”搜索。参数允许调整首板回看交易日数、观察交易日数和观察期末
最大成交量比例；观察期为断板后的 3 至 20 个共同市场交易日。单次筛选中的所有股票仍使用同一市场日历窗口，
不会因个股停牌或缺数而向前错位。

## ScreeningSpec v2

v2 使用递归 `root_group`，组节点包含 `AND` 或 `OR`，叶节点包含条件键、条件版本和
参数快照。最多嵌套3层、最多20个原子条件，本阶段不开放 `NOT`。v1 的 `conditions`
数组继续读取，并自动解释为隐式 `AND`。两种版本继续保存于现有 JSONB 规格快照，
因此 SC03-A 不需要数据库迁移。

示例：

```json
{
  "schema_version": 2,
  "conditions": [],
  "root_group": {
    "node_type": "GROUP",
    "operator": "AND",
    "children": [
      {
        "node_type": "CONDITION",
        "condition_key": "RECENT_LIMIT_UP_EVENT",
        "condition_version": "1.0.0",
        "parameters": {
          "lookback_days": 5,
          "minimum_occurrences": 1,
          "event_selection": "LATEST_VALID",
          "require_reliable_limit_price": true
        }
      },
      {
        "node_type": "CONDITION",
        "condition_key": "AMOUNT_THRESHOLD",
        "condition_version": "1.0.0",
        "parameters": {"minimum_amount": "5000000000"}
      }
    ]
  }
}
```

## 三值逻辑与审计

原子结果分为 `MATCHED`、`NOT_MATCHED` 和 `INDETERMINATE`。AND 中任一不满足则整体
不满足；没有不满足但存在无法判断时整体无法判断。OR 中任一满足则整体满足；没有满足
但存在无法判断时整体无法判断。结果的 `metrics.condition_evaluations` 保存每个原子
条件的名称、结果、原因和指标，前端可逐项展开。

## 前端操作

智能选股页支持搜索名称、别名或说明，选择原子条件，编辑参数，切换 AND/OR，创建最多
三层子组，并实时查看中文规则。“成交额50亿”会预填50亿元，“近5日涨停”会预填5个
交易日。确认后继续复用现有校验、预览、方案保存、运行、历史结果、自选股和快速回测。

## 数据准备与边界

数据准备器对整棵条件树取字段和历史窗口并集，复用 SC02-D 和 CAL01-R 的 MiniQMT
增量补数、交易日历、停牌、新股和质量语义。SC03-A 不新增行情源，不改变订单、风控、
Broker、账本或回测引擎，也不提供实盘交易能力。

## 验收

`test_sc03a_condition_builder.py` 覆盖40个目录搜索、参数边界、v1兼容、v2往返、
AND/OR、嵌套限制、近期涨停、成交额、三值逻辑和短语预填场景。既有 SC02-A/B 测试
继续作为兼容回归基线。
