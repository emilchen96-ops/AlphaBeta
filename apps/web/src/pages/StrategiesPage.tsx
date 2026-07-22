import { ExperimentOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getInstruments } from "../api/market";
import { createStrategyRun, getStrategyCatalog } from "../api/strategies";
import { systemCapabilitiesQueryOptions } from "../api/system";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { StrategyParameterDefinition } from "../types/strategies";
import {
  displayEnum,
  displayParameter,
  displayStrategy,
  formatInstrument,
} from "../utils/display";

interface RunFormValues {
  strategy_key: string;
  instrument_ids: string[];
  timeframe: string;
  start_at: string;
  end_at: string;
  parameters: Record<string, string | number | boolean>;
  idempotency_key: string;
  price_adjustment_mode: "RAW" | "QFQ";
}

function ParameterInput({
  definition,
}: {
  definition: StrategyParameterDefinition;
}) {
  if (definition.type === "boolean") return <Switch />;
  if (definition.type === "enum")
    return <Select options={definition.choices.map((value) => ({ value }))} />;
  if (definition.type === "integer")
    return (
      <InputNumber
        precision={0}
        min={Number(definition.min_value ?? undefined)}
        max={Number(definition.max_value ?? undefined)}
        style={{ width: "100%" }}
      />
    );
  return (
    <Input inputMode={definition.type === "decimal" ? "decimal" : "text"} />
  );
}

export function StrategiesPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [selectedKey, setSelectedKey] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const capabilities = useQuery(systemCapabilitiesQueryOptions);
  const unavailable =
    capabilities.data?.items?.find(
      (item) => item.module_key === "strategy_research",
    )?.available === false;
  const unavailableReason = capabilities.data?.items?.find(
    (item) => item.module_key === "strategy_research",
  )?.reason;
  const qfqReady =
    capabilities.data?.items?.find(
      (item) => item.module_key === "adjusted_strategy_data",
    )?.available === true;
  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const instruments = useQuery({
    queryKey: ["strategy-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const selected = useMemo(
    () => catalog.data?.find((item) => item.strategy_key === selectedKey),
    [catalog.data, selectedKey],
  );
  const mutation = useMutation({
    mutationFn: createStrategyRun,
    onSuccess: (run) => {
      void message.success(
        run.replayed ? "已返回原研究运行" : "历史研究运行已完成",
      );
      void navigate(`/strategy-runs/${run.run_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const openRun = (key: string) => {
    const strategy = catalog.data?.find((item) => item.strategy_key === key);
    setSelectedKey(key);
    const parameters = Object.fromEntries(
      strategy?.parameters
        .filter((item) => item.default !== null)
        .map((item) => [item.name, item.default]) ?? [],
    );
    form.setFieldsValue({
      strategy_key: key,
      timeframe: strategy?.supported_timeframes[0],
      parameters,
      idempotency_key: `research:${crypto.randomUUID()}`,
      price_adjustment_mode: "RAW",
    });
  };
  const submit = async () => {
    const values = (await form.validateFields()) as RunFormValues;
    mutation.mutate({
      strategy_key: values.strategy_key,
      instrument_ids: values.instrument_ids,
      timeframe: values.timeframe,
      parameters: values.parameters,
      idempotency_key: values.idempotency_key,
      price_adjustment_mode: values.price_adjustment_mode,
      start_at: new Date(values.start_at).toISOString(),
      end_at: new Date(values.end_at).toISOString(),
    });
  };

  return (
    <section>
      <PageHeader
        title="策略目录"
        description="选择受信任策略与历史数据，生成可审计的研究信号（Signal）。"
      />
      <Alert
        showIcon
        type="warning"
        title="研究信号（Signal）是研究输出，不是订单"
        description="不会创建订单、调用风控或券商接口（Broker），也不会修改资金和持仓。参考价格（reference_price）仅供研究；当前不是绩效回测，也没有实时策略调度。"
      />
      {unavailable ? (
        <Alert
          showIcon
          type="info"
          title="当前缺少可研究的历史行情"
          description={unavailableReason}
          style={{ marginTop: 16 }}
        />
      ) : null}
      <Space
        orientation="vertical"
        size="middle"
        style={{ display: "flex", marginTop: 16 }}
      >
        {catalog.data?.map((item) => (
          <Card
            key={item.strategy_key}
            title={displayStrategy(item.strategy_key)}
            extra={
              <Space wrap>
                <Button
                  icon={<ExperimentOutlined />}
                  disabled={unavailable}
                  onClick={() =>
                    void navigate(
                      `/strategy-experiments?strategy_key=${encodeURIComponent(item.strategy_key)}`,
                    )
                  }
                >
                  批量研究
                </Button>
                <Button
                  icon={<ExperimentOutlined />}
                  disabled={unavailable}
                  onClick={() => openRun(item.strategy_key)}
                >
                  创建研究运行
                </Button>
              </Space>
            }
          >
            <Typography.Paragraph>{item.description}</Typography.Paragraph>
            <Space wrap>
              <Tag>{displayStrategy(item.strategy_key)}</Tag>
              <Tag color="blue">v{item.version}</Tag>
              {item.supported_timeframes.map((value) => (
                <Tag key={value}>{displayEnum(value)}</Tag>
              ))}
            </Space>
            <Typography.Title level={5}>参数定义</Typography.Title>
            {item.parameters.map((parameter) => (
              <Typography.Paragraph key={parameter.name}>
                <strong>{displayParameter(parameter.name)}</strong> ·{" "}
                {displayEnum(parameter.type)} · {parameter.description}
              </Typography.Paragraph>
            ))}
          </Card>
        ))}
      </Space>
      {selected ? (
        <Card
          title={`创建${displayStrategy(selected.strategy_key)}历史研究运行`}
          style={{ marginTop: 16 }}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="strategy_key" label="策略">
              <Input disabled />
            </Form.Item>
            <Form.Item
              name="instrument_ids"
              label="标的"
              rules={[{ required: true }]}
            >
              <Select
                mode="multiple"
                showSearch
                filterOption={false}
                onSearch={setInstrumentSearch}
                options={instruments.data?.items.map((item) => ({
                  value: item.id,
                  label: formatInstrument(item),
                }))}
              />
            </Form.Item>
            <Form.Item
              name="timeframe"
              label="周期"
              rules={[{ required: true }]}
            >
              <Select
                options={selected.supported_timeframes.map((value) => ({
                  value,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="price_adjustment_mode"
              label="策略价格模式"
              tooltip="前复权（QFQ）只用于指标和研究信号参考价；不会作为成交或账本价格。"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  { value: "RAW", label: "不复权（RAW，兼容模式）" },
                  {
                    value: "QFQ",
                    label: qfqReady
                      ? "前复权（QFQ）"
                      : "前复权（QFQ，数据未就绪）",
                    disabled: !qfqReady,
                  },
                ]}
              />
            </Form.Item>
            <Space wrap>
              <Form.Item
                name="start_at"
                label="开始时间"
                rules={[{ required: true }]}
              >
                <Input type="datetime-local" />
              </Form.Item>
              <Form.Item
                name="end_at"
                label="结束时间"
                rules={[{ required: true }]}
              >
                <Input type="datetime-local" />
              </Form.Item>
            </Space>
            {selected.parameters.map((definition) => (
              <Form.Item
                key={definition.name}
                name={["parameters", definition.name]}
                label={displayParameter(definition.name)}
                tooltip={definition.description}
                valuePropName={
                  definition.type === "boolean" ? "checked" : "value"
                }
                rules={[{ required: definition.required }]}
              >
                <ParameterInput definition={definition} />
              </Form.Item>
            ))}
            <Button
              type="primary"
              loading={mutation.isPending}
              disabled={unavailable || mutation.isPending}
              onClick={() => void submit()}
            >
              开始研究
            </Button>
          </Form>
        </Card>
      ) : null}
    </section>
  );
}
