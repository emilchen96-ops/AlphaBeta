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
  Modal,
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
import { systemCapabilitiesQueryOptions } from "../api/system";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  ScannerParameterDefinition,
  ScannerParameterValue,
} from "../types/scanners";
import {
  displayEnum,
  displayParameter,
  displayScanner,
  formatInstrument,
} from "../utils/display";

interface RunFormValues {
  scanner_key: string;
  instrument_ids: string[];
  timeframe: string;
  as_of: string;
  parameters: Record<string, ScannerParameterValue>;
  idempotency_key: string;
  price_adjustment_mode: "RAW" | "QFQ";
}

function ParameterInput({
  definition,
}: {
  definition: ScannerParameterDefinition;
}) {
  if (definition.type === "boolean")
    return <Switch checkedChildren="是" unCheckedChildren="否" />;
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
  const percent = scannerPercentParameters.has(definition.name);
  if (definition.type === "decimal") {
    return (
      <InputNumber
        stringMode
        min={
          definition.min_value === null
            ? undefined
            : Number(definition.min_value) * (percent ? 100 : 1)
        }
        max={
          definition.max_value === null
            ? undefined
            : Number(definition.max_value) * (percent ? 100 : 1)
        }
        suffix={percent ? "%" : undefined}
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

const scannerPercentParameters = new Set([
  "limit_up_threshold",
  "baseline_tolerance",
  "minimum_current_volume_ratio",
]);

export function ScannersPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<RunFormValues>();
  const [selectedKey, setSelectedKey] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const capabilities = useQuery(systemCapabilitiesQueryOptions);
  const unavailable =
    capabilities.data?.items?.find((item) => item.module_key === "scanner")
      ?.available === false;
  const unavailableReason = capabilities.data?.items?.find(
    (item) => item.module_key === "scanner",
  )?.reason;
  const qfqReady =
    capabilities.data?.items?.find(
      (item) => item.module_key === "adjusted_strategy_data",
    )?.available === true;
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
          .map((item) => [
            item.name,
            scannerPercentParameters.has(item.name)
              ? Number(item.default) * 100
              : item.default,
          ]) ?? [],
      ),
      idempotency_key: `scan:${crypto.randomUUID()}`,
      price_adjustment_mode: "RAW",
    });
  };
  const submit = async () => {
    const values = await form.validateFields();
    mutation.mutate({
      ...values,
      as_of: new Date(values.as_of).toISOString(),
      parameters: Object.fromEntries(
        Object.entries(values.parameters ?? {})
          .filter(([, value]) => value !== "")
          .map(([name, value]) => [
            name,
            scannerPercentParameters.has(name) && value !== null
              ? String(Number(value) / 100)
              : value,
          ]),
      ),
    });
  };

  const restoreDefaults = () => {
    if (selected) openRun(selected.scanner_key);
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
      {unavailable ? (
        <Alert
          showIcon
          type="info"
          title="当前缺少可扫描的历史行情"
          description={unavailableReason}
          style={{ marginTop: 16 }}
        />
      ) : null}
      <Space wrap style={{ marginTop: 16 }}>
        <Button onClick={() => void navigate("/scan-runs")}>
          查看扫描运行
        </Button>
        <Button onClick={() => void navigate("/market")}>查看标的与行情</Button>
        <Button onClick={() => void navigate("/strategies")}>查看策略</Button>
        <Button onClick={() => void navigate("/signals")}>查看研究信号</Button>
      </Space>
      <Space
        orientation="vertical"
        size="middle"
        style={{ display: "flex", marginTop: 16 }}
      >
        {catalog.data?.map((item) => (
          <Card
            key={item.scanner_key}
            title={displayScanner(item.scanner_key)}
            extra={
              <Button
                icon={<FilterOutlined />}
                disabled={unavailable}
                onClick={() => openRun(item.scanner_key)}
              >
                创建扫描运行
              </Button>
            }
          >
            <Typography.Paragraph>{item.description}</Typography.Paragraph>
            <Space wrap>
              <Tag>{displayScanner(item.scanner_key)}</Tag>
              <Tag color="blue">v{item.version}</Tag>
              <Tag>历史日线</Tag>
              <Tag color="orange">非实时</Tag>
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
      <Modal
        open={Boolean(selected)}
        title={
          selected
            ? `创建${displayScanner(selected.scanner_key)}扫描运行`
            : "创建扫描运行"
        }
        width={760}
        okText="开始扫描"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        okButtonProps={{ disabled: unavailable || mutation.isPending }}
        onCancel={() => {
          setSelectedKey(undefined);
          form.resetFields();
        }}
        onOk={() => void submit()}
        destroyOnHidden
      >
        {selected ? (
          <Form form={form} layout="vertical">
            <Alert
              showIcon
              type="info"
              title="配置历史日线扫描"
              description="选择研究股票池、截止时间和规则参数。扫描结果仅供研究，不会创建信号或订单。"
              style={{ marginBottom: 16 }}
            />
            <Form.Item
              name="instrument_ids"
              label="研究股票池"
              rules={[{ required: true, message: "请至少选择一只股票" }]}
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
                placeholder="按股票代码或名称搜索并选择"
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
              label="价格复权模式"
              tooltip={
                selected.scanner_key === "limit_up_pullback"
                  ? "涨停识别必须使用真实 RAW 价格。"
                  : "volume 使用原始成交量；价格过滤可使用 RAW 或 QFQ。"
              }
              rules={[{ required: true }]}
            >
              <Select
                disabled={selected.scanner_key === "limit_up_pullback"}
                options={[
                  { value: "RAW", label: "不复权（RAW）" },
                  {
                    value: "QFQ",
                    label: qfqReady
                      ? "前复权（QFQ）"
                      : "前复权（QFQ，数据未就绪）",
                    disabled:
                      !qfqReady || selected.scanner_key === "limit_up_pullback",
                  },
                ]}
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
            <Button onClick={restoreDefaults}>恢复默认参数</Button>
          </Form>
        ) : null}
      </Modal>
    </section>
  );
}
