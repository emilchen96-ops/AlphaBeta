import {
  AutoComplete,
  Button,
  Card,
  Col,
  Divider,
  Input,
  InputNumber,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  FolderAddOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useMemo, useState } from "react";

import type {
  ScreeningConditionDefinition,
  ScreeningConditionGroupSpec,
  ScreeningConditionSpec,
  ScreeningParameterDefinition,
  ScreeningSpecSnapshot,
} from "../../types/screenings";

interface VisualScreeningEditorProps {
  definitions: ScreeningConditionDefinition[];
  value: ScreeningSpecSnapshot;
  onChange: (value: ScreeningSpecSnapshot) => void;
}

const enumLabels: Record<string, string> = {
  LATEST_VALID: "最近且数据完整的事件",
  EARLIEST_VALID: "最早且数据完整的事件",
  PRE_LIMIT_PREVIOUS_CLOSE: "涨停前一交易日收盘价",
  LIMIT_UP_DAY_VOLUME: "涨停日成交量",
  ABOVE: "高于",
  BELOW: "低于",
  GREATER_OR_EQUAL: "大于或等于",
  LESS_OR_EQUAL: "小于或等于",
  TRADING: "正常交易",
  SUSPENDED: "停牌",
};

const categoryLabels: Record<string, string> = {
  PRICE: "价格",
  TREND: "趋势",
  VOLUME: "成交量",
  CANDLE: "K线",
  LIQUIDITY: "流动性",
  TRADING: "交易状态",
  PATTERN: "复合形态",
  RETURN: "涨跌幅",
  AMOUNT: "成交额",
  MOVING_AVERAGE: "均线",
  BREAKOUT: "突破",
  LIMIT_UP_EVENT: "涨停事件",
  RANGE_POSITION: "区间位置",
  COMPOSITE_PATTERN: "复合形态",
};

const rankingLabels: Record<string, string> = {
  score: "标准条件得分",
  volume_multiple: "成交量倍数",
  range_position: "价格区间位置",
  distance_to_anchor: "距起涨价格的距离",
  current_close: "当前收盘价",
};

// eslint-disable-next-line react-refresh/only-export-components
export function initialScreeningParameters(
  definition: ScreeningConditionDefinition,
) {
  return Object.fromEntries(
    definition.parameter_schema.map((schema) => [schema.name, schema.default]),
  );
}

function asRoot(value: ScreeningSpecSnapshot): ScreeningConditionGroupSpec {
  return (
    value.root_group ?? {
      node_type: "GROUP",
      operator: "AND",
      children: value.conditions.map((item) => ({
        ...item,
        node_type: "CONDITION" as const,
      })),
    }
  );
}

function isGroup(
  node: ScreeningConditionSpec | ScreeningConditionGroupSpec,
): node is ScreeningConditionGroupSpec {
  return node.node_type === "GROUP";
}

function replaceNode(
  group: ScreeningConditionGroupSpec,
  path: number[],
  replacement:
    | ScreeningConditionSpec
    | ScreeningConditionGroupSpec
    | null,
): ScreeningConditionGroupSpec {
  if (path.length === 1) {
    return {
      ...group,
      children:
        replacement === null
          ? group.children.filter((_, index) => index !== path[0])
          : group.children.map((item, index) =>
              index === path[0] ? replacement : item,
            ),
    };
  }
  const [head, ...tail] = path;
  return {
    ...group,
    children: group.children.map((item, index) =>
      index === head && isGroup(item)
        ? replaceNode(item, tail, replacement)
        : item,
    ),
  };
}

function updateGroup(
  group: ScreeningConditionGroupSpec,
  path: number[],
  updater: (
    current: ScreeningConditionGroupSpec,
  ) => ScreeningConditionGroupSpec,
): ScreeningConditionGroupSpec {
  if (path.length === 0) return updater(group);
  const [head, ...tail] = path;
  return {
    ...group,
    children: group.children.map((item, index) =>
      index === head && isGroup(item) ? updateGroup(item, tail, updater) : item,
    ),
  };
}

function countAtoms(group: ScreeningConditionGroupSpec): number {
  return group.children.reduce(
    (total, child) => total + (isGroup(child) ? countAtoms(child) : 1),
    0,
  );
}

function canRepresentAsFlatAnd(group: ScreeningConditionGroupSpec): boolean {
  return (
    group.operator === "AND" &&
    group.children.every((child) => !isGroup(child))
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function conditionFromDefinition(
  definition: ScreeningConditionDefinition,
  phrase: string,
): ScreeningConditionSpec {
  const parameters = initialScreeningParameters(definition);
  const number = Number(phrase.match(/\d+(?:\.\d+)?/)?.[0]);
  if (
    Number.isFinite(number) &&
    definition.condition_key === "AMOUNT_THRESHOLD"
  ) {
    parameters.minimum_amount = number * 100_000_000;
  }
  if (
    Number.isFinite(number) &&
    definition.condition_key === "RECENT_LIMIT_UP_EVENT"
  ) {
    parameters.lookback_days = Math.round(number);
  }
  return {
    node_type: "CONDITION",
    condition_key: definition.condition_key,
    condition_version: definition.version,
    parameters,
  };
}

function parameterDisplay(
  schema: ScreeningParameterDefinition,
  value: string | number | boolean | null | undefined,
) {
  if (schema.type === "boolean") return value ? "是" : "否";
  if (schema.type === "enum") return enumLabels[String(value)] ?? String(value);
  const numeric = Number(value);
  if (schema.type === "percentage")
    return `${Number.isFinite(numeric) ? numeric * 100 : "—"}%`;
  if (schema.type === "amount")
    return `${Number.isFinite(numeric) ? numeric / 100_000_000 : "—"}亿元`;
  return `${value ?? "—"}${schema.display_unit ?? schema.unit ?? ""}`;
}

function ConditionCard({
  node,
  definition,
  path,
  onReplace,
}: {
  node: ScreeningConditionSpec;
  definition: ScreeningConditionDefinition;
  path: number[];
  onReplace: (
    path: number[],
    value: ScreeningConditionSpec | ScreeningConditionGroupSpec | null,
  ) => void;
}) {
  const updateParameter = (
    schema: ScreeningParameterDefinition,
    next: string | number | boolean | null,
  ) => {
    let stored = next;
    if (typeof next === "number" && schema.type === "percentage")
      stored = next / 100;
    if (typeof next === "number" && schema.type === "amount")
      stored = next * 100_000_000;
    onReplace(path, {
      ...node,
      parameters: { ...node.parameters, [schema.name]: stored },
    });
  };
  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>{definition.display_name}</span>
          <Tag>{categoryLabels[definition.category] ?? definition.category}</Tag>
          <Typography.Text type="secondary">
            {definition.condition_key}
          </Typography.Text>
        </Space>
      }
      extra={
        <Button
          aria-label={`删除${definition.display_name}`}
          danger
          type="text"
          icon={<DeleteOutlined />}
          onClick={() => onReplace(path, null)}
        />
      }
    >
      <Typography.Paragraph type="secondary">
        {definition.description}
      </Typography.Paragraph>
      <Row gutter={[16, 14]}>
        {definition.parameter_schema.map((schema) => {
          const current = node.parameters[schema.name] ?? schema.default;
          const label = (
            <Tooltip title={schema.help_text ?? schema.description}>
              <span>{schema.display_name}</span>
            </Tooltip>
          );
          if (schema.type === "boolean") {
            return (
              <Col xs={24} md={12} xl={8} key={schema.name}>
                <Space>
                  <Switch
                    checked={Boolean(current)}
                    checkedChildren="是"
                    unCheckedChildren="否"
                    onChange={(checked) => updateParameter(schema, checked)}
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
                  style={{ width: "100%", marginTop: 6 }}
                  value={String(current ?? "")}
                  options={schema.enum_values.map((item) => ({
                    value: item,
                    label: enumLabels[item] ?? item,
                  }))}
                  onChange={(next) => updateParameter(schema, next)}
                />
              </Col>
            );
          }
          const multiplier =
            schema.type === "percentage"
              ? 100
              : schema.type === "amount"
                ? 1 / 100_000_000
                : 1;
          return (
            <Col xs={24} md={12} xl={8} key={schema.name}>
              <Typography.Text>{label}</Typography.Text>
              <InputNumber
                aria-label={schema.display_name}
                style={{ width: "100%", marginTop: 6 }}
                value={
                  current === null || current === undefined
                    ? null
                    : Number(current) * multiplier
                }
                min={
                  schema.min_value === null
                    ? undefined
                    : Number(schema.min_value) * multiplier
                }
                max={
                  schema.max_value === null
                    ? undefined
                    : Number(schema.max_value) * multiplier
                }
                precision={
                  schema.precision ??
                  (schema.type === "integer" ||
                  schema.type === "trading_day_window"
                    ? 0
                    : 4)
                }
                placeholder={schema.placeholder ?? undefined}
                suffix={schema.display_unit ?? schema.unit ?? undefined}
                onChange={(next) => updateParameter(schema, next)}
              />
            </Col>
          );
        })}
      </Row>
    </Card>
  );
}

function GroupEditor({
  group,
  path,
  depth,
  definitions,
  onGroupChange,
  onReplace,
}: {
  group: ScreeningConditionGroupSpec;
  path: number[];
  depth: number;
  definitions: Map<string, ScreeningConditionDefinition>;
  onGroupChange: (
    path: number[],
    updater: (
      current: ScreeningConditionGroupSpec,
    ) => ScreeningConditionGroupSpec,
  ) => void;
  onReplace: (
    path: number[],
    value: ScreeningConditionSpec | ScreeningConditionGroupSpec | null,
  ) => void;
}) {
  return (
    <Card
      size="small"
      style={{
        borderColor: group.operator === "AND" ? "#91caff" : "#b7eb8f",
        background: depth === 1 ? "#fafcff" : undefined,
      }}
      title={
        <Space wrap>
          <span>{depth === 1 ? "条件组合" : `子条件组（第${depth}层）`}</span>
          <Segmented
            value={group.operator}
            options={[
              { value: "AND", label: "全部满足（AND）" },
              { value: "OR", label: "任一满足（OR）" },
            ]}
            onChange={(operator) =>
              onGroupChange(path, (current) => ({
                ...current,
                operator: operator as "AND" | "OR",
              }))
            }
          />
        </Space>
      }
      extra={
        depth > 1 ? (
          <Button
            danger
            type="text"
            icon={<DeleteOutlined />}
            onClick={() => onReplace(path, null)}
          >
            删除组
          </Button>
        ) : null
      }
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        {group.children.map((child, index) =>
          isGroup(child) ? (
            <GroupEditor
              key={`group-${path.join("-")}-${index}`}
              group={child}
              path={[...path, index]}
              depth={depth + 1}
              definitions={definitions}
              onGroupChange={onGroupChange}
              onReplace={onReplace}
            />
          ) : definitions.get(child.condition_key) ? (
            <ConditionCard
              key={`condition-${path.join("-")}-${index}`}
              node={child}
              definition={definitions.get(child.condition_key)!}
              path={[...path, index]}
              onReplace={onReplace}
            />
          ) : null,
        )}
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="向这个条件组添加原子条件"
          options={[...definitions.values()].map((definition) => ({
            value: definition.condition_key,
            label: `${definition.display_name} · ${
              categoryLabels[definition.category] ?? definition.category
            }`,
          }))}
          onChange={(conditionKey: string) => {
            const definition = definitions.get(conditionKey);
            if (!definition || countAtoms(group) >= 20) return;
            onGroupChange(path, (current) => ({
              ...current,
              children: [
                ...current.children,
                {
                  node_type: "CONDITION",
                  condition_key: conditionKey,
                  condition_version: definition.version,
                  parameters: initialScreeningParameters(definition),
                },
              ],
            }));
          }}
        />
        {depth < 3 ? (
          <Select
            suffixIcon={<FolderAddOutlined />}
            placeholder="新建子条件组，并选择第一个条件"
            disabled={countAtoms(group) >= 20}
            options={[...definitions.values()].map((definition) => ({
              value: definition.condition_key,
              label: definition.display_name,
            }))}
            onChange={(conditionKey: string) => {
              const definition = definitions.get(conditionKey);
              if (!definition) return;
              onGroupChange(path, (current) => ({
                ...current,
                children: [
                  ...current.children,
                  {
                    node_type: "GROUP",
                    operator: "AND",
                    children: [
                      {
                        node_type: "CONDITION",
                        condition_key: conditionKey,
                        condition_version: definition.version,
                        parameters: initialScreeningParameters(definition),
                      },
                    ],
                  },
                ],
              }));
            }}
          />
        ) : null}
      </Space>
    </Card>
  );
}

export function VisualScreeningEditor({
  definitions,
  value,
  onChange,
}: VisualScreeningEditorProps) {
  const [searchText, setSearchText] = useState("");
  const root = asRoot(value);
  const byKey = useMemo(
    () =>
      new Map(
        definitions.map((definition) => [
          definition.condition_key,
          definition,
        ]),
      ),
    [definitions],
  );
  const emit = (nextRoot: ScreeningConditionGroupSpec) => {
    if (value.schema_version === 1 && canRepresentAsFlatAnd(nextRoot)) {
      onChange({
        ...value,
        origin: "USER_CORRECTED",
        conditions: nextRoot.children as ScreeningConditionSpec[],
        root_group: null,
      });
      return;
    }
    onChange({
      ...value,
      schema_version: 2,
      origin: "USER_CORRECTED",
      conditions: [],
      root_group: nextRoot,
    });
  };
  const addCondition = (conditionKey: string) => {
    if (countAtoms(root) >= 20) return;
    const definition = byKey.get(conditionKey);
    if (!definition) return;
    emit({
      ...root,
      children: [
        ...root.children,
        {
          ...conditionFromDefinition(definition, searchText),
        },
      ],
    });
    setSearchText("");
  };
  const searchOptions = definitions
    .filter((definition) => {
      const query = searchText.trim().toLowerCase();
      if (!query) return true;
      return [
        definition.display_name,
        definition.condition_key,
        definition.description,
        ...(definition.aliases ?? []),
      ]
        .join(" ")
        .toLowerCase()
        .includes(query.replace(/\d+(?:\.\d+)?/g, "").trim());
    })
    .map((definition) => ({
      value: definition.condition_key,
      label: `${definition.display_name} · ${
        categoryLabels[definition.category] ?? definition.category
      }`,
    }));
  const previewNode = (
    node: ScreeningConditionSpec | ScreeningConditionGroupSpec,
  ): string => {
    if (isGroup(node)) {
      const connector = node.operator === "AND" ? " 并且 " : " 或者 ";
      return `（${node.children.map(previewNode).join(connector)}）`;
    }
    const definition = byKey.get(node.condition_key);
    if (!definition) return node.condition_key;
    const parameters = definition.parameter_schema
      .map(
        (schema) =>
          `${schema.display_name}=${parameterDisplay(
            schema,
            node.parameters[schema.name] ?? schema.default,
          )}`,
      )
      .join("，");
    return `${definition.display_name}${parameters ? `（${parameters}）` : ""}`;
  };
  const updateUniverse = (
    name:
      | "exclude_st"
      | "exclude_bse"
      | "exclude_star_market"
      | "exclude_chinext",
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
        <Space wrap>
          {(
            [
              ["exclude_st", "排除ST及*ST"],
              ["exclude_bse", "排除北交所"],
              ["exclude_star_market", "排除科创板"],
              ["exclude_chinext", "排除创业板"],
            ] as const
          ).map(([key, label]) => (
            <Space key={key}>
              <Switch
                checked={value.universe_spec[key]}
                onChange={(checked) => updateUniverse(key, checked)}
              />
              <span>{label}</span>
            </Space>
          ))}
        </Space>
      </Card>

      <Card size="small" title="搜索并添加条件">
        <AutoComplete
          style={{ width: "100%" }}
          value={searchText}
          options={searchOptions}
          onSearch={setSearchText}
          onChange={setSearchText}
          onSelect={addCondition}
        >
          <Input
            prefix={<SearchOutlined />}
            placeholder="输入条件关键词，例如：成交额50亿、近5日涨停、均线、放量"
          />
        </AutoComplete>
        <Typography.Paragraph type="secondary" style={{ margin: "8px 0 0" }}>
          输入数字会自动带入对应参数；条件来自可审计的原子条件目录，不执行任意代码。
        </Typography.Paragraph>
      </Card>

      <GroupEditor
        group={root}
        path={[]}
        depth={1}
        definitions={byKey}
        onGroupChange={(path, updater) => emit(updateGroup(root, path, updater))}
        onReplace={(path, replacement) =>
          emit(replaceNode(root, path, replacement))
        }
      />

      <Card size="small" title="实时中文规则预览">
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          {root.children.length ? previewNode(root) : "请至少添加一个原子条件。"}
        </Typography.Paragraph>
      </Card>

      <Card size="small" title="结果排序">
        <Row gutter={[16, 12]}>
          <Col xs={24} md={10}>
            <Select
              style={{ width: "100%" }}
              value={value.ranking_rules[0]?.field ?? "score"}
              options={Object.entries(rankingLabels).map(([key, label]) => ({
                value: key,
                label,
              }))}
              onChange={(field) =>
                onChange({
                  ...value,
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
            <Select
              style={{ width: "100%" }}
              value={value.ranking_rules[0]?.direction ?? "DESC"}
              options={[
                { value: "DESC", label: "从高到低" },
                { value: "ASC", label: "从低到高" },
              ]}
              onChange={(direction) =>
                onChange({
                  ...value,
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
            <InputNumber
              style={{ width: "100%" }}
              min={1}
              max={10_000}
              precision={0}
              value={value.top_n}
              placeholder="最多保留（可选）"
              onChange={(top_n) => onChange({ ...value, top_n })}
            />
          </Col>
        </Row>
        <Divider style={{ margin: "16px 0 0" }} />
      </Card>
    </Space>
  );
}
