import {
  Card,
  Col,
  Divider,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Tooltip,
  Typography,
} from "antd";

import type {
  ScreeningConditionDefinition,
  ScreeningParameterDefinition,
  ScreeningSpecSnapshot,
} from "../../types/screenings";

interface VisualScreeningEditorProps {
  definitions: ScreeningConditionDefinition[];
  value: ScreeningSpecSnapshot;
  onChange: (value: ScreeningSpecSnapshot) => void;
}

const percentageParameters = new Set([
  "maximum_distance_pct",
  "minimum_price_ratio_to_anchor",
  "maximum_volume_ratio",
  "bottom_ratio",
  "maximum_position",
  "minimum_return",
  "maximum_return",
]);

const enumLabels: Record<string, string> = {
  LATEST_VALID: "最近且数据完整的涨停事件",
  PRE_LIMIT_PREVIOUS_CLOSE: "涨停前一交易日收盘价",
  LIMIT_UP_DAY_VOLUME: "涨停日成交量",
  ABOVE: "高于",
  BELOW: "低于",
  GREATER_OR_EQUAL: "大于或等于",
  LESS_OR_EQUAL: "小于或等于",
  TRADING: "正常交易",
  SUSPENDED: "停牌",
};

const rankingLabels: Record<string, string> = {
  score: "标准条件得分",
  volume_multiple: "成交量倍数",
  range_position: "价格区间位置",
  distance_to_anchor: "距起涨价格的距离",
  current_close: "当前收盘价",
};

function numberValue(
  value: string | number | boolean | null | undefined,
  percentage: boolean,
) {
  if (typeof value === "boolean" || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed * (percentage ? 100 : 1) : null;
}

function schemaUnit(schema: ScreeningParameterDefinition) {
  if (percentageParameters.has(schema.name)) return "%";
  if (schema.name.includes("multiple") || schema.name === "minimum_ratio")
    return "倍";
  return schema.unit ?? undefined;
}

export function VisualScreeningEditor({
  definitions,
  value,
  onChange,
}: VisualScreeningEditorProps) {
  const byKey = new Map(
    definitions.map((definition) => [definition.condition_key, definition]),
  );

  const updateParameter = (
    conditionIndex: number,
    schema: ScreeningParameterDefinition,
    next: string | number | boolean | null,
  ) => {
    const percentage = percentageParameters.has(schema.name);
    const stored = typeof next === "number" && percentage ? next / 100 : next;
    onChange({
      ...value,
      origin: "USER_CORRECTED",
      conditions: value.conditions.map((condition, index) =>
        index === conditionIndex
          ? {
              ...condition,
              parameters: {
                ...condition.parameters,
                [schema.name]: stored,
              },
            }
          : condition,
      ),
    });
  };

  const updateUniverse = (
    name:
      "exclude_st" | "exclude_bse" | "exclude_star_market" | "exclude_chinext",
    checked: boolean,
  ) =>
    onChange({
      ...value,
      origin: "USER_CORRECTED",
      universe_spec: { ...value.universe_spec, [name]: checked },
    });

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="股票范围">
        <Typography.Paragraph>
          筛选日期当时存在的全部A股（沪、深、北）
        </Typography.Paragraph>
        <Space wrap>
          <Switch
            aria-label="排除ST及*ST"
            checked={value.universe_spec.exclude_st}
            onChange={(checked) => updateUniverse("exclude_st", checked)}
          />
          <span>排除ST及*ST</span>
          <Switch
            aria-label="排除北交所"
            checked={value.universe_spec.exclude_bse}
            onChange={(checked) => updateUniverse("exclude_bse", checked)}
          />
          <span>排除北交所</span>
          <Switch
            aria-label="排除科创板"
            checked={value.universe_spec.exclude_star_market}
            onChange={(checked) =>
              updateUniverse("exclude_star_market", checked)
            }
          />
          <span>排除科创板</span>
          <Switch
            aria-label="排除创业板"
            checked={value.universe_spec.exclude_chinext}
            onChange={(checked) => updateUniverse("exclude_chinext", checked)}
          />
          <span>排除创业板</span>
        </Space>
      </Card>

      {value.conditions.map((condition, conditionIndex) => {
        const definition = byKey.get(condition.condition_key);
        if (!definition) return null;
        return (
          <Card
            size="small"
            key={`${condition.condition_key}-${conditionIndex}`}
            title={definition.display_name}
          >
            <Typography.Paragraph type="secondary">
              {definition.description}
            </Typography.Paragraph>
            <Row gutter={[20, 16]}>
              {definition.parameter_schema.map((schema) => {
                const current = condition.parameters[schema.name];
                const label = (
                  <Tooltip title={schema.description}>
                    <span>{schema.display_name}</span>
                  </Tooltip>
                );
                if (schema.type === "boolean") {
                  return (
                    <Col xs={24} md={12} xl={8} key={schema.name}>
                      <Space>
                        <Switch
                          aria-label={schema.display_name}
                          checked={Boolean(current)}
                          checkedChildren="是"
                          unCheckedChildren="否"
                          onChange={(checked) =>
                            updateParameter(conditionIndex, schema, checked)
                          }
                        />
                        {label}
                      </Space>
                    </Col>
                  );
                }
                if (schema.type === "enum") {
                  return (
                    <Col xs={24} md={12} xl={8} key={schema.name}>
                      <Typography.Text>{label}</Typography.Text>
                      <Select
                        aria-label={schema.display_name}
                        style={{ width: "100%", marginTop: 6 }}
                        value={String(current ?? schema.default ?? "")}
                        options={schema.enum_values.map((item) => ({
                          value: item,
                          label: enumLabels[item] ?? item,
                        }))}
                        onChange={(next) =>
                          updateParameter(conditionIndex, schema, next)
                        }
                      />
                    </Col>
                  );
                }
                const percentage = percentageParameters.has(schema.name);
                const min =
                  schema.min_value === null
                    ? undefined
                    : Number(schema.min_value) * (percentage ? 100 : 1);
                const max =
                  schema.max_value === null
                    ? undefined
                    : Number(schema.max_value) * (percentage ? 100 : 1);
                return (
                  <Col xs={24} md={12} xl={8} key={schema.name}>
                    <Typography.Text>{label}</Typography.Text>
                    <div
                      style={{
                        alignItems: "stretch",
                        display: "flex",
                        marginTop: 6,
                      }}
                    >
                      <InputNumber
                        aria-label={schema.display_name}
                        style={{ flex: 1, width: "100%" }}
                        value={numberValue(current, percentage)}
                        min={min}
                        max={max}
                        precision={schema.type === "integer" ? 0 : 4}
                        onChange={(next) =>
                          updateParameter(conditionIndex, schema, next)
                        }
                      />
                      {schemaUnit(schema) ? (
                        <span
                          style={{
                            alignItems: "center",
                            border: "1px solid #d9d9d9",
                            borderInlineStart: 0,
                            borderRadius: "0 6px 6px 0",
                            display: "flex",
                            paddingInline: 11,
                          }}
                        >
                          {schemaUnit(schema)}
                        </span>
                      ) : null}
                    </div>
                  </Col>
                );
              })}
            </Row>
          </Card>
        );
      })}

      <Card size="small" title="结果排序">
        <Row gutter={[20, 16]}>
          <Col xs={24} md={10}>
            <Typography.Text>排序依据</Typography.Text>
            <Select
              aria-label="排序依据"
              style={{ width: "100%", marginTop: 6 }}
              value={value.ranking_rules[0]?.field ?? "score"}
              options={Object.entries(rankingLabels).map(([key, label]) => ({
                value: key,
                label,
              }))}
              onChange={(field) =>
                onChange({
                  ...value,
                  origin: "USER_CORRECTED",
                  ranking_rules: [
                    {
                      field,
                      direction: value.ranking_rules[0]?.direction ?? "DESC",
                    },
                  ],
                })
              }
            />
          </Col>
          <Col xs={24} md={8}>
            <Typography.Text>排序方向</Typography.Text>
            <Select
              aria-label="排序方向"
              style={{ width: "100%", marginTop: 6 }}
              value={value.ranking_rules[0]?.direction ?? "DESC"}
              options={[
                { value: "DESC", label: "从高到低" },
                { value: "ASC", label: "从低到高" },
              ]}
              onChange={(direction) =>
                onChange({
                  ...value,
                  origin: "USER_CORRECTED",
                  ranking_rules: [
                    {
                      field: value.ranking_rules[0]?.field ?? "score",
                      direction,
                    },
                  ],
                })
              }
            />
          </Col>
          <Col xs={24} md={6}>
            <Typography.Text>最多保留（可选）</Typography.Text>
            <div
              style={{
                alignItems: "stretch",
                display: "flex",
                marginTop: 6,
              }}
            >
              <InputNumber
                aria-label="最多保留"
                style={{ flex: 1, width: "100%" }}
                min={1}
                max={10000}
                precision={0}
                value={value.top_n}
                onChange={(top_n) =>
                  onChange({
                    ...value,
                    origin: "USER_CORRECTED",
                    top_n,
                  })
                }
              />
              <span
                style={{
                  alignItems: "center",
                  border: "1px solid #d9d9d9",
                  borderInlineStart: 0,
                  borderRadius: "0 6px 6px 0",
                  display: "flex",
                  paddingInline: 11,
                }}
              >
                只
              </span>
            </div>
          </Col>
        </Row>
        <Divider style={{ margin: "16px 0 0" }} />
      </Card>
    </Space>
  );
}
