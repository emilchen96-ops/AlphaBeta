import {
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Typography,
} from "antd";
import { useEffect } from "react";

import type {
  LogicalOperator,
  StrategyComparison,
  StrategySpec,
} from "../../types/strategySpecs";

interface RuleForm {
  name: string;
  entry_operator: LogicalOperator;
  breakout_window: number;
  volume_multiplier: number;
  exit_window: number;
  quantity: number;
  data_range_years: number;
}

function comparisonAt(
  spec: StrategySpec,
  group: "entry" | "exit",
  index: number,
) {
  return spec[group].conditions[index] as StrategyComparison;
}

export function StrategyRuleEditor({
  open,
  spec,
  onCancel,
  onSave,
}: {
  open: boolean;
  spec: StrategySpec | null;
  onCancel: () => void;
  onSave: (spec: StrategySpec) => void;
}) {
  const [form] = Form.useForm<RuleForm>();

  useEffect(() => {
    if (!open || spec === null) return;
    form.setFieldsValue({
      name: spec.name,
      entry_operator: spec.entry.operator,
      breakout_window: comparisonAt(spec, "entry", 0).right.window ?? 10,
      volume_multiplier: Number(
        comparisonAt(spec, "entry", 1).right.multiplier,
      ),
      exit_window: comparisonAt(spec, "exit", 0).right.window ?? 5,
      quantity: Number(spec.quantity),
      data_range_years: spec.data_range_years,
    });
  }, [form, open, spec]);

  return (
    <Modal
      open={open}
      title="可视化规则编辑"
      okText="应用修改"
      cancelText="取消"
      onCancel={onCancel}
      onOk={() => void form.submit()}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        普通用户只需调整业务参数；英文技术键和内部编号不会作为主要信息展示。
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        onFinish={(values) => {
          if (spec === null) return;
          const next = structuredClone(spec);
          next.name = values.name;
          next.entry.operator = values.entry_operator;
          comparisonAt(next, "entry", 0).right.window = values.breakout_window;
          comparisonAt(next, "entry", 1).right.window = values.breakout_window;
          comparisonAt(next, "entry", 1).right.multiplier = String(
            values.volume_multiplier,
          );
          comparisonAt(next, "exit", 0).right.window = values.exit_window;
          next.quantity = String(values.quantity);
          next.data_range_years = values.data_range_years;
          onSave(next);
        }}
      >
        <Form.Item
          name="name"
          label="策略名称"
          rules={[{ required: true, message: "请输入策略名称" }]}
        >
          <Input maxLength={128} />
        </Form.Item>
        <Form.Item name="entry_operator" label="买入条件关系">
          <Select
            options={[
              { value: "AND", label: "同时满足（AND）" },
              { value: "OR", label: "满足任一（OR）" },
            ]}
          />
        </Form.Item>
        <Space wrap align="start">
          <Form.Item name="breakout_window" label="价格突破周期（日）">
            <InputNumber min={2} max={500} precision={0} />
          </Form.Item>
          <Form.Item name="volume_multiplier" label="成交量放大倍数">
            <InputNumber min={0.01} max={100} step={0.1} />
          </Form.Item>
          <Form.Item name="exit_window" label="退出均线周期（日）">
            <InputNumber min={1} max={500} precision={0} />
          </Form.Item>
          <Form.Item name="data_range_years" label="历史数据范围（年）">
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
          <Form.Item name="quantity" label="系统参考数量（股）">
            <InputNumber min={100} step={100} precision={0} />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}
