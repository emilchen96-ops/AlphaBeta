import { FilterOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getInstruments } from "../api/market";
import {
  createScanRun,
  getScannerCatalog,
  getScannerSessionDefault,
  getScanRuns,
} from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  ScannerParameterDefinition,
  ScannerParameterValue,
} from "../types/scanners";
import {
  displayParameter,
  displayScanner,
  formatInstrument,
} from "../utils/display";

interface RunFormValues {
  scanner_key: string;
  scan_date: string;
  universe_filters: {
    exclude_st: boolean;
    exclude_suspended: boolean;
    exclude_insufficient_history: boolean;
    exclude_bse: boolean;
    exclude_star_market: boolean;
    exclude_chinext: boolean;
    minimum_listing_trading_days?: number;
    excluded_instrument_ids: string[];
  };
  parameters: Record<string, ScannerParameterValue | undefined>;
}

const percentParameters = new Set([
  "limit_up_threshold",
  "baseline_tolerance",
  "minimum_daily_return",
  "maximum_daily_return",
]);

const runStatusText: Record<string, string> = {
  QUEUED: "等待中",
  RESOLVING: "正在解析股票范围",
  CHECKING_DATA: "正在检查历史数据",
  BACKFILLING: "正在补齐历史数据",
  RUNNING: "正在扫描",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "运行失败",
  CANCELED: "已取消",
};

function parameterDefaultValue(definition: ScannerParameterDefinition) {
  if (definition.default === null) {
    return undefined;
  }
  return percentParameters.has(definition.name)
    ? Number(definition.default) * 100
    : definition.default;
}

function ParameterInput({
  definition,
  value,
  checked,
  onChange,
}: {
  definition: ScannerParameterDefinition;
  value?: ScannerParameterValue;
  checked?: boolean;
  onChange?: (value: ScannerParameterValue | null) => void;
}) {
  if (definition.type === "boolean") {
    return (
      <Switch
        checked={checked}
        checkedChildren="是"
        unCheckedChildren="否"
        onChange={(next) => onChange?.(next)}
      />
    );
  }
  const percent = percentParameters.has(definition.name);
  return (
    <InputNumber
      value={typeof value === "boolean" || value === null ? undefined : value}
      onChange={(next) => onChange?.(next)}
      stringMode={definition.type === "decimal"}
      precision={definition.type === "integer" ? 0 : undefined}
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
      suffix={percent ? "%" : definition.unit || undefined}
      placeholder={definition.nullable ? "可留空，表示不限制" : undefined}
      style={{ width: "100%" }}
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
  const sessionDefault = useQuery({
    queryKey: ["scanner-session-default"],
    queryFn: getScannerSessionDefault,
  });
  const recentRuns = useQuery({
    queryKey: ["scan-runs", "scanner-cards"],
    queryFn: () => getScanRuns({ page: 1, page_size: 100 }),
    refetchInterval: 5000,
  });
  const instruments = useQuery({
    queryKey: ["scanner-excluded-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
    enabled: Boolean(selectedKey),
  });
  const selected = useMemo(
    () => catalog.data?.find((item) => item.scanner_key === selectedKey),
    [catalog.data, selectedKey],
  );
  const latestByScanner = useMemo(
    () =>
      new Map(
        catalog.data?.map((scanner) => [
          scanner.scanner_key,
          recentRuns.data?.items.find(
            (run) => run.scanner_key === scanner.scanner_key,
          ),
        ]) ?? [],
      ),
    [catalog.data, recentRuns.data],
  );
  const mutation = useMutation({
    mutationFn: createScanRun,
    onSuccess: (run) => {
      void message.success(
        run.replayed ? "已返回相同扫描任务" : "全市场扫描任务已创建",
      );
      setSelectedKey(undefined);
      form.resetFields();
      void navigate(`/scan-runs/${run.scan_run_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const openRun = (key: string) => {
    const scanner = catalog.data?.find((item) => item.scanner_key === key);
    setSelectedKey(key);
    form.resetFields();
    form.setFieldsValue({
      scanner_key: key,
      scan_date: sessionDefault.data?.scan_date,
      universe_filters: {
        exclude_st: true,
        exclude_suspended: true,
        exclude_insufficient_history: true,
        exclude_bse: false,
        exclude_star_market: false,
        exclude_chinext: false,
        excluded_instrument_ids: [],
      },
      parameters: Object.fromEntries(
        scanner?.parameters
          .filter((item) => item.default !== null)
          .map((item) => [item.name, parameterDefaultValue(item)]) ?? [],
      ),
    });
  };

  const submit = async () => {
    const values = await form.validateFields();
    mutation.mutate({
      scanner_key: values.scanner_key,
      universe_type: "ALL_ACTIVE_A_SHARES",
      scan_date: values.scan_date,
      universe_filters: values.universe_filters,
      parameters: Object.fromEntries(
        Object.entries(values.parameters ?? {})
          .filter(([, value]) => value !== "" && value !== undefined)
          .map(([name, value]) => [
            name,
            percentParameters.has(name) && value !== null
              ? String(Number(value) / 100)
              : value,
          ]),
      ),
    });
  };

  return (
    <section>
      <PageHeader
        title="条件扫描器"
        description="使用MiniQMT历史日线，对全部正常上市A股执行后台批量筛选。"
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Button onClick={() => void navigate("/scan-runs")}>
          查看扫描运行
        </Button>
        <Button onClick={() => void navigate("/market")}>查看行情</Button>
      </Space>
      <Space orientation="vertical" size="middle" style={{ display: "flex" }}>
        {catalog.data?.map((item) => {
          const latest = latestByScanner.get(item.scanner_key);
          return (
            <Card
              key={item.scanner_key}
              title={displayScanner(item.scanner_key)}
              extra={
                <Button
                  type="primary"
                  icon={<FilterOutlined />}
                  onClick={() => openRun(item.scanner_key)}
                >
                  开始全市场扫描
                </Button>
              }
            >
              <Typography.Paragraph>{item.description}</Typography.Paragraph>
              <Space wrap>
                <Tag color="green">数据来源：MiniQMT</Tag>
                <Tag color="blue">范围：全部A股</Tag>
                <Tag>周期：日线</Tag>
                <Tag>后台批量运行</Tag>
                <Tag color="purple">v{item.version}</Tag>
              </Space>
              <Descriptions
                size="small"
                column={{ xs: 1, sm: 3 }}
                style={{ marginTop: 16 }}
                items={[
                  {
                    key: "latest-status",
                    label: "最近状态",
                    children: latest
                      ? (runStatusText[latest.status] ?? latest.status)
                      : "尚未运行",
                  },
                  {
                    key: "latest-date",
                    label: "最近扫描日期",
                    children: latest?.as_of.slice(0, 10) ?? "—",
                  },
                  {
                    key: "latest-matches",
                    label: "最近命中",
                    children: latest ? `${latest.matches_found}只` : "—",
                  },
                ]}
              />
            </Card>
          );
        })}
      </Space>
      <Modal
        open={Boolean(selected)}
        title={
          selected
            ? `${displayScanner(selected.scanner_key)}：全A股扫描`
            : "全A股扫描"
        }
        width={860}
        okText="开始扫描"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onCancel={() => {
          setSelectedKey(undefined);
          form.resetFields();
        }}
        onOk={() => void submit()}
        destroyOnHidden
      >
        {selected ? (
          <Form form={form} layout="vertical">
            <Form.Item name="scanner_key" hidden>
              <Input />
            </Form.Item>
            <Descriptions
              bordered
              size="small"
              column={2}
              style={{ marginBottom: 20 }}
              items={[
                {
                  key: "universe",
                  label: "扫描范围",
                  children: "全部正常上市A股",
                },
                {
                  key: "source",
                  label: "数据来源",
                  children: "MiniQMT",
                },
                {
                  key: "timeframe",
                  label: "数据周期",
                  children: "日线",
                },
                {
                  key: "execution",
                  label: "运行方式",
                  children: "后台分批运行",
                },
              ]}
            />
            <Form.Item
              name="scan_date"
              label="扫描日期"
              rules={[{ required: true, message: "请选择扫描日期" }]}
              tooltip="默认为最近一个已经完成的A股交易日"
            >
              <Input type="date" />
            </Form.Item>
            <Typography.Title level={5}>排除条件</Typography.Title>
            <Row gutter={16}>
              {[
                ["exclude_st", "排除ST及*ST股票"],
                ["exclude_suspended", "排除扫描日停牌股票"],
                ["exclude_insufficient_history", "排除历史数据不足股票"],
                ["exclude_bse", "排除北交所股票"],
                ["exclude_star_market", "排除科创板股票"],
                ["exclude_chinext", "排除创业板股票"],
              ].map(([name, label]) => (
                <Col xs={24} md={12} key={name}>
                  <Form.Item
                    name={["universe_filters", name]}
                    label={label}
                    valuePropName="checked"
                  >
                    <Switch checkedChildren="是" unCheckedChildren="否" />
                  </Form.Item>
                </Col>
              ))}
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item
                  name={["universe_filters", "minimum_listing_trading_days"]}
                  label="排除上市不足指定交易日的股票"
                  tooltip="留空表示不按上市时间排除"
                >
                  <InputNumber
                    min={1}
                    max={5000}
                    precision={0}
                    suffix="交易日"
                    placeholder="可留空"
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name={["universe_filters", "excluded_instrument_ids"]}
                  label="手动排除股票"
                  tooltip="按代码或名称搜索；这里只排除，不需要建立研究股票池"
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
                    placeholder="可选：搜索需要排除的股票"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Collapse
              items={[
                {
                  key: "advanced",
                  label: "高级参数（已填入推荐默认值）",
                  children: (
                    <Row gutter={16}>
                      {selected.parameters.map((definition) => (
                        <Col xs={24} md={12} key={definition.name}>
                          <Form.Item
                            name={["parameters", definition.name]}
                            initialValue={parameterDefaultValue(definition)}
                            label={`${definition.display_name || displayParameter(definition.name)}（${definition.name}）`}
                            tooltip={definition.description}
                            valuePropName={
                              definition.type === "boolean"
                                ? "checked"
                                : "value"
                            }
                          >
                            <ParameterInput definition={definition} />
                          </Form.Item>
                        </Col>
                      ))}
                    </Row>
                  ),
                },
              ]}
            />
          </Form>
        ) : null}
      </Modal>
    </section>
  );
}
