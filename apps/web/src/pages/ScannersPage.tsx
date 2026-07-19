import { FilterOutlined } from "@ant-design/icons";
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
import { createScanRun, getScannerCatalog } from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  ScannerParameterDefinition,
  ScannerParameterValue,
} from "../types/scanners";

interface RunFormValues {
  scanner_key: string;
  instrument_ids: string[];
  timeframe: string;
  as_of: string;
  parameters: Record<string, ScannerParameterValue>;
  idempotency_key: string;
}

function ParameterInput({
  definition,
}: {
  definition: ScannerParameterDefinition;
}) {
  if (definition.type === "boolean") return <Switch />;
  if (definition.type === "integer") {
    return (
      <InputNumber
        precision={0}
        min={Number(definition.min_value ?? undefined)}
        max={Number(definition.max_value ?? undefined)}
        style={{ width: "100%" }}
      />
    );
  }
  return (
    <Input
      inputMode="decimal"
      placeholder={definition.nullable ? "可留空" : undefined}
    />
  );
}

export function ScannersPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<RunFormValues>();
  const [selectedKey, setSelectedKey] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const catalog = useQuery({
    queryKey: ["scanner-catalog"],
    queryFn: getScannerCatalog,
  });
  const instruments = useQuery({
    queryKey: ["scanner-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const selected = useMemo(
    () => catalog.data?.find((item) => item.scanner_key === selectedKey),
    [catalog.data, selectedKey],
  );
  const mutation = useMutation({
    mutationFn: createScanRun,
    onSuccess: (run) => {
      void message.success(
        run.replayed ? "已返回原扫描运行" : "历史日线扫描已完成",
      );
      void navigate(`/scan-runs/${run.scan_run_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const openRun = (key: string) => {
    const scanner = catalog.data?.find((item) => item.scanner_key === key);
    setSelectedKey(key);
    form.setFieldsValue({
      scanner_key: key,
      timeframe: scanner?.supported_timeframes[0] ?? "DAY_1",
      parameters: Object.fromEntries(
        scanner?.parameters
          .filter((item) => item.default !== null)
          .map((item) => [item.name, item.default]) ?? [],
      ),
      idempotency_key: `scan:${crypto.randomUUID()}`,
    });
  };
  const submit = async () => {
    const values = await form.validateFields();
    mutation.mutate({
      ...values,
      as_of: new Date(values.as_of).toISOString(),
      parameters: Object.fromEntries(
        Object.entries(values.parameters ?? {}).filter(
          ([, value]) => value !== "",
        ),
      ),
    });
  };

  return (
    <section>
      <PageHeader
        title="条件扫描器"
        description="使用本地已有 A 股历史日线执行确定性规则筛选。"
      />
      <Alert
        showIcon
        type="warning"
        title="扫描结果仅为规则筛选结果，不代表投资建议"
        description="当前使用历史日线数据，不是实时扫描；扫描器不会自动创建 Signal 或订单，也不会修改资金、持仓和账本。"
      />
      <Space wrap style={{ marginTop: 16 }}>
        <Button onClick={() => void navigate("/scan-runs")}>
          查看扫描运行
        </Button>
        <Button onClick={() => void navigate("/market")}>
          查看 Instrument 与行情
        </Button>
        <Button onClick={() => void navigate("/strategies")}>查看策略</Button>
        <Button onClick={() => void navigate("/signals")}>
          查看研究 Signal
        </Button>
      </Space>
      <Space
        orientation="vertical"
        size="middle"
        style={{ display: "flex", marginTop: 16 }}
      >
        {catalog.data?.map((item) => (
          <Card
            key={item.scanner_key}
            title={item.display_name}
            extra={
              <Button
                icon={<FilterOutlined />}
                onClick={() => openRun(item.scanner_key)}
              >
                创建扫描运行
              </Button>
            }
          >
            <Typography.Paragraph>{item.description}</Typography.Paragraph>
            <Space wrap>
              <Tag>{item.scanner_key}</Tag>
              <Tag color="blue">v{item.version}</Tag>
              <Tag>历史日线</Tag>
              <Tag color="orange">非实时</Tag>
            </Space>
            <Typography.Title level={5}>参数定义</Typography.Title>
            {item.parameters.map((parameter) => (
              <Typography.Paragraph key={parameter.name}>
                <code>{parameter.name}</code> · {parameter.type} ·{" "}
                {parameter.description}
              </Typography.Paragraph>
            ))}
          </Card>
        ))}
      </Space>
      {selected ? (
        <Card
          title={`创建 ${selected.display_name} 扫描运行`}
          style={{ marginTop: 16 }}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="scanner_key" label="扫描器">
              <Input disabled />
            </Form.Item>
            <Form.Item
              name="instrument_ids"
              label="Instrument 股票池"
              rules={[{ required: true }]}
            >
              <Select
                mode="multiple"
                showSearch
                filterOption={false}
                onSearch={setInstrumentSearch}
                options={instruments.data?.items.map((item) => ({
                  value: item.id,
                  label: `${item.symbol}.${item.exchange} · ${item.name}`,
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
              name="as_of"
              label="扫描截止时间"
              rules={[{ required: true }]}
            >
              <Input type="datetime-local" />
            </Form.Item>
            {selected.parameters.map((definition) => (
              <Form.Item
                key={definition.name}
                name={["parameters", definition.name]}
                label={`${definition.name} · ${definition.description}`}
                valuePropName={
                  definition.type === "boolean" ? "checked" : "value"
                }
                rules={[{ required: definition.required }]}
              >
                <ParameterInput definition={definition} />
              </Form.Item>
            ))}
            <Form.Item
              name="idempotency_key"
              label="幂等键"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Button
              type="primary"
              loading={mutation.isPending}
              onClick={() => void submit()}
            >
              运行历史日线扫描
            </Button>
          </Form>
        </Card>
      ) : null}
    </section>
  );
}
