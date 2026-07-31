import { ExperimentOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Select,
  Space,
  Table,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getInstruments } from "../api/market";
import {
  createQuickBacktest,
  listStrategyTemplates,
} from "../api/strategySpecs";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { BacktestRun } from "../types/backtests";
import type { StrategySpec } from "../types/strategySpecs";
import { formatInstrument } from "../utils/display";

interface ComparisonValues {
  template: string;
  instrument_id: string;
  range: [Dayjs, Dayjs];
  breakout_windows: string;
  volume_multipliers: string;
  exit_windows: string;
}

interface ComparisonRow {
  key: string;
  breakout: number;
  volume: number;
  exit: number;
  run: BacktestRun;
}

const parseCandidates = (text: string) =>
  text
    .split(/[，,\s]+/)
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0);

function withParameters(
  source: StrategySpec,
  breakout: number,
  volume: number,
  exit: number,
): StrategySpec {
  const spec = structuredClone(source);
  for (const condition of spec.entry.conditions) {
    if (condition.type !== "comparison") continue;
    if (condition.right.indicator === "ROLLING_HIGHEST") {
      condition.right.window = breakout;
    }
    if (condition.right.indicator === "AVERAGE_VOLUME") {
      condition.right.window = breakout;
      condition.right.multiplier = String(volume);
    }
  }
  for (const condition of spec.exit.conditions) {
    if (
      condition.type === "comparison" &&
      condition.right.indicator === "SMA"
    ) {
      condition.right.window = exit;
    }
  }
  spec.name = `${breakout}日突破 + ${volume}倍量 + ${exit}日均线退出`;
  spec.origin = "VISUAL_EDITOR";
  return spec;
}

export function ParameterComparisonPage() {
  const [form] = Form.useForm<ComparisonValues>();
  const [keyword, setKeyword] = useState("长信科技");
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const templates = useQuery({
    queryKey: ["strategy-templates"],
    queryFn: listStrategyTemplates,
  });
  const instruments = useQuery({
    queryKey: ["comparison-instruments", keyword],
    queryFn: () => getInstruments(keyword),
  });
  const templateItems = Array.isArray(templates.data) ? templates.data : [];

  const submit = async (values: ComparisonValues) => {
    const template = templateItems.find((item) => item.key === values.template);
    if (!template?.spec) return;
    const breakouts = parseCandidates(values.breakout_windows);
    const volumes = parseCandidates(values.volume_multipliers);
    const exits = parseCandidates(values.exit_windows);
    const combinations = breakouts.flatMap((breakout) =>
      volumes.flatMap((volume) =>
        exits.map((exit) => ({ breakout, volume, exit })),
      ),
    );
    if (!combinations.length || combinations.length > 12) {
      setError("请输入有效候选值，参数组合总数不能超过 12 组。");
      return;
    }
    setRunning(true);
    setError(null);
    setRows([]);
    try {
      const next: ComparisonRow[] = [];
      for (const item of combinations) {
        const run = await createQuickBacktest({
          instrument_id: values.instrument_id,
          start_at: values.range[0].startOf("day").toISOString(),
          end_at: values.range[1].add(1, "day").startOf("day").toISOString(),
          initial_cash: "100000",
          spec: withParameters(
            template.spec,
            item.breakout,
            item.volume,
            item.exit,
          ),
          price_adjustment_mode: "QFQ",
          commission_rate: "0.0003",
          minimum_commission: "5",
          stamp_duty_rate: "0.0005",
          transfer_fee_rate: "0.00001",
          slippage_basis_points: "2",
          maximum_volume_participation: "0.1",
          execution_price_mode: "NEXT_OPEN",
          position_size_ratio: "1",
          maximum_entry_gap_ratio: "0.05",
          time_in_force: "DAY",
          idempotency_key: `parameter-comparison:${crypto.randomUUID()}`,
        });
        next.push({ key: run.id, ...item, run });
        setRows([...next]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "参数对比失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section>
      <PageHeader
        title="参数对比"
        description="对同一股票运行少量完整回测，比较收益、回撤和交易表现。"
      />
      <Alert
        showIcon
        type="info"
        title="每个组合都调用完整 BT01 历史模拟"
        description="为避免一次运行过久，当前最多比较 12 组；不会发送真实订单。"
        style={{ marginBottom: 16 }}
      />
      <Card title="设置比较范围">
        <Form<ComparisonValues>
          form={form}
          layout="vertical"
          initialValues={{
            range: [dayjs().subtract(2, "year"), dayjs()],
            breakout_windows: "10, 20",
            volume_multipliers: "1.2, 1.5",
            exit_windows: "5, 10",
            template: "price_volume_breakout_sma_exit",
          }}
          onFinish={(values) => void submit(values)}
        >
          <Form.Item
            name="template"
            label="策略模板"
            rules={[{ required: true }]}
          >
            <Select
              options={templateItems
                .filter((item) => item.spec)
                .map((item) => ({ value: item.key, label: item.name }))}
            />
          </Form.Item>
          <Form.Item
            name="instrument_id"
            label="股票"
            rules={[{ required: true }]}
          >
            <Select
              showSearch
              filterOption={false}
              onSearch={(value) => setKeyword(value)}
              options={(instruments.data?.items ?? []).map((item) => ({
                value: item.id,
                label: formatInstrument(item),
              }))}
            />
          </Form.Item>
          <Form.Item name="range" label="回测区间" rules={[{ required: true }]}>
            <DatePicker.RangePicker />
          </Form.Item>
          <Space wrap align="start">
            <Form.Item name="breakout_windows" label="突破周期候选（天）">
              <Input placeholder="10, 20, 30" />
            </Form.Item>
            <Form.Item name="volume_multipliers" label="成交量倍数候选">
              <Input placeholder="1.2, 1.5, 2.0" />
            </Form.Item>
            <Form.Item name="exit_windows" label="退出均线候选（天）">
              <Input placeholder="5, 10, 20" />
            </Form.Item>
          </Space>
          {error ? <Alert type="error" showIcon title={error} /> : null}
          <Button
            type="primary"
            htmlType="submit"
            loading={running}
            icon={<ExperimentOutlined />}
          >
            开始比较
          </Button>
        </Form>
      </Card>
      <Card title="比较结果" style={{ marginTop: 16 }}>
        <Table
          rowKey="key"
          dataSource={rows}
          pagination={false}
          columns={[
            { title: "突破周期", dataIndex: "breakout" },
            { title: "成交量倍数", dataIndex: "volume" },
            { title: "退出均线", dataIndex: "exit" },
            {
              title: "总收益率",
              render: (_, item) =>
                item.run.metrics
                  ? `${(Number(item.run.metrics.total_return) * 100).toFixed(2)}%`
                  : "—",
            },
            {
              title: "最大回撤",
              render: (_, item) =>
                item.run.metrics
                  ? `${(Number(item.run.metrics.maximum_drawdown) * 100).toFixed(2)}%`
                  : "—",
            },
            {
              title: "交易次数",
              render: (_, item) => item.run.metrics?.fill_count ?? 0,
            },
            {
              title: "胜率",
              render: (_, item) =>
                item.run.metrics?.win_rate
                  ? `${(Number(item.run.metrics.win_rate) * 100).toFixed(2)}%`
                  : "—",
            },
            {
              title: "最终资产",
              render: (_, item) => item.run.metrics?.final_equity ?? "—",
            },
          ]}
        />
      </Card>
    </section>
  );
}
