import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import type { ScreeningConditionDefinition } from "../../types/screenings";

interface AtomicConditionCatalogProps {
  definitions: ScreeningConditionDefinition[];
  naturalLanguageText: string;
  addedConditionKeys: Set<string>;
  onAdd: (definition: ScreeningConditionDefinition, phrase: string) => void;
}

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

const ignoredWords = new Set([
  "过去",
  "最近",
  "目前",
  "股票",
  "个股",
  "条件",
  "筛选",
  "大于",
  "小于",
  "高于",
  "低于",
  "达到",
  "出现",
  "以内",
  "之内",
  "并且",
  "或者",
  "交易日",
]);

function normalize(value: string) {
  return value
    .toLowerCase()
    .replace(/\d+(?:\.\d+)?/g, " ")
    .replace(/[，。；、：:（）()％%亿元万元天日内个只的与和]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function fragments(value: string) {
  const normalized = normalize(value);
  const words = normalized
    .split(" ")
    .filter((word) => word.length >= 2 && !ignoredWords.has(word));
  const compact = normalized.replace(/\s+/g, "");
  for (let index = 0; index < compact.length - 1; index += 1) {
    words.push(compact.slice(index, index + 2));
  }
  return [...new Set(words)];
}

function relevance(
  definition: ScreeningConditionDefinition,
  phrase: string,
) {
  if (!phrase.trim()) return 0;
  const haystack = normalize(
    [
      definition.display_name,
      definition.description,
      definition.category,
      definition.condition_key,
      ...(definition.aliases ?? []),
      ...definition.parameter_schema.flatMap((parameter) => [
        parameter.display_name,
        parameter.description,
      ]),
    ].join(" "),
  ).replace(/\s+/g, "");
  return fragments(phrase).reduce(
    (score, fragment) => score + (haystack.includes(fragment) ? 1 : 0),
    0,
  );
}

function ConditionTile({
  definition,
  added,
  phrase,
  onAdd,
}: {
  definition: ScreeningConditionDefinition;
  added: boolean;
  phrase: string;
  onAdd: AtomicConditionCatalogProps["onAdd"];
}) {
  return (
    <Card
      size="small"
      style={{ height: "100%" }}
      title={
        <Space size={8} wrap>
          <span>{definition.display_name}</span>
          <Tag>
            {categoryLabels[definition.category] ?? definition.category}
          </Tag>
        </Space>
      }
      extra={
        <Button
          size="small"
          type={added ? "default" : "primary"}
          icon={added ? undefined : <PlusOutlined />}
          disabled={added}
          aria-label={`添加${definition.display_name}`}
          onClick={() => onAdd(definition, phrase)}
        >
          {added ? "已添加" : "添加"}
        </Button>
      }
    >
      <Typography.Paragraph style={{ marginBottom: 8 }}>
        {definition.description}
      </Typography.Paragraph>
      <Typography.Text type="secondary">
        {definition.parameter_schema.length
          ? `可设置：${definition.parameter_schema
              .map((parameter) => parameter.display_name)
              .join("、")}`
          : "无需设置参数"}
      </Typography.Text>
      {(definition.aliases ?? []).length ? (
        <div style={{ marginTop: 8 }}>
          {(definition.aliases ?? []).slice(0, 4).map((alias) => (
            <Tag key={alias}>{alias}</Tag>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

export function AtomicConditionCatalog({
  definitions,
  naturalLanguageText,
  addedConditionKeys,
  onAdd,
}: AtomicConditionCatalogProps) {
  const [catalogSearch, setCatalogSearch] = useState("");
  const activeDefinitions = useMemo(
    () =>
      definitions
        .filter((definition) => definition.enabled && !definition.deprecated)
        .sort((left, right) =>
          left.display_name.localeCompare(right.display_name, "zh-CN"),
        ),
    [definitions],
  );
  const recommended = useMemo(
    () =>
      activeDefinitions
        .map((definition) => ({
          definition,
          score: relevance(definition, naturalLanguageText),
        }))
        .filter((item) => item.score > 0)
        .sort(
          (left, right) =>
            right.score - left.score ||
            left.definition.display_name.localeCompare(
              right.definition.display_name,
              "zh-CN",
            ),
        )
        .slice(0, 4)
        .map((item) => item.definition),
    [activeDefinitions, naturalLanguageText],
  );
  const visibleDefinitions = useMemo(() => {
    const query = normalize(catalogSearch).replace(/\s+/g, "");
    if (!query) return activeDefinitions;
    return activeDefinitions.filter((definition) =>
      normalize(
        [
          definition.display_name,
          definition.description,
          definition.condition_key,
          ...(definition.aliases ?? []),
          ...definition.parameter_schema.map(
            (parameter) => parameter.display_name,
          ),
        ].join(" "),
      )
        .replace(/\s+/g, "")
        .includes(query),
    );
  }, [activeDefinitions, catalogSearch]);

  const renderTiles = (items: ScreeningConditionDefinition[]) => (
    <Row gutter={[12, 12]}>
      {items.map((definition) => (
        <Col xs={24} md={12} xl={8} key={definition.condition_key}>
          <ConditionTile
            definition={definition}
            added={addedConditionKeys.has(definition.condition_key)}
            phrase={naturalLanguageText}
            onAdd={onAdd}
          />
        </Col>
      ))}
    </Row>
  );

  return (
    <Card
      title={`原子条件目录（共${activeDefinitions.length}项）`}
      style={{ marginTop: 16 }}
    >
      <Typography.Paragraph type="secondary">
        输入选股描述时，系统会从下列条件中实时推荐；也可以不写完整句子，直接搜索并添加条件积木。
        每个条件的数字参数都能在添加后继续修改。
      </Typography.Paragraph>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        aria-label="搜索原子条件"
        value={catalogSearch}
        onChange={(event) => setCatalogSearch(event.target.value)}
        placeholder="搜索全部原子条件，例如：涨停、成交额、均线、放量"
        style={{ marginBottom: 16 }}
      />

      {naturalLanguageText.trim() ? (
        <>
          <Typography.Title level={5}>根据当前描述推荐</Typography.Title>
          {recommended.length ? (
            renderTiles(recommended)
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="没有直接匹配项，请从下面的完整目录搜索或选择"
            />
          )}
        </>
      ) : null}

      <Typography.Title
        level={5}
        style={{ marginTop: naturalLanguageText.trim() ? 24 : 0 }}
      >
        全部原子条件
      </Typography.Title>
      {visibleDefinitions.length ? (
        renderTiles(visibleDefinitions)
      ) : (
        <Empty description="没有匹配的原子条件，请换一个关键词" />
      )}
    </Card>
  );
}
