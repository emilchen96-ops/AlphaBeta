import {
  CheckCircleOutlined,
  EditOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Input, List, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  parseStrategyText,
  validateStrategySpec,
} from "../../api/strategySpecs";
import type { StrategySpec } from "../../types/strategySpecs";
import { StrategyRuleEditor } from "./StrategyRuleEditor";

const EXAMPLE = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线";

const errorMessage = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : "操作失败，请稍后重试";

export function NaturalLanguageStrategyBuilder({
  initialText = EXAMPLE,
  onConfirmed,
}: {
  initialText?: string;
  onConfirmed: (spec: StrategySpec, preview: string[]) => void;
}) {
  const [text, setText] = useState(initialText);
  const [spec, setSpec] = useState<StrategySpec | null>(null);
  const [preview, setPreview] = useState<string[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [validating, setValidating] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);

  const parse = async () => {
    setParsing(true);
    setError(null);
    try {
      const result = await parseStrategyText(text);
      setSpec(result.spec);
      setPreview(result.preview);
      setMissing(result.missing_fields);
      if (result.status === "PARTIAL") {
        setError(result.warnings[0] ?? "请补齐策略条件");
      }
    } catch (reason) {
      setSpec(null);
      setPreview([]);
      setError(errorMessage(reason));
    } finally {
      setParsing(false);
    }
  };

  const confirm = async () => {
    if (spec === null) return;
    setValidating(true);
    setError(null);
    try {
      const result = await validateStrategySpec(spec);
      setSpec(result.spec);
      setPreview(result.preview);
      onConfirmed(result.spec, result.preview);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setValidating(false);
    }
  };

  return (
    <>
      <Card
        title="用一句话描述策略"
        extra={<Tag color="blue">本地安全解析</Tag>}
      >
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Paragraph type="secondary">
            例如：{EXAMPLE}
          </Typography.Paragraph>
          <Input.TextArea
            aria-label="自然语言策略描述"
            value={text}
            rows={4}
            maxLength={1000}
            showCount
            onChange={(event) => setText(event.target.value)}
          />
          <Space wrap>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={parsing}
              onClick={() => void parse()}
            >
              解析策略
            </Button>
            <Button onClick={() => setText(EXAMPLE)}>使用示例</Button>
          </Space>
          {error !== null && (
            <Alert
              showIcon
              type={spec === null ? "warning" : "error"}
              title={error}
              description={
                missing.length > 0 ? `还缺少：${missing.join("、")}` : undefined
              }
            />
          )}
          {spec !== null && (
            <Card size="small" title={spec.name}>
              <List
                dataSource={preview}
                renderItem={(item) => (
                  <List.Item>
                    <CheckCircleOutlined
                      style={{ color: "#52c41a", marginRight: 8 }}
                    />
                    {item}
                  </List.Item>
                )}
              />
              <Space wrap>
                <Button
                  icon={<EditOutlined />}
                  onClick={() => setEditorOpen(true)}
                >
                  编辑规则
                </Button>
                <Button
                  type="primary"
                  loading={validating}
                  onClick={() => void confirm()}
                >
                  确认并使用
                </Button>
              </Space>
            </Card>
          )}
        </Space>
      </Card>
      <StrategyRuleEditor
        open={editorOpen}
        spec={spec}
        onCancel={() => setEditorOpen(false)}
        onSave={(next) => {
          setSpec(next);
          setEditorOpen(false);
          setPreview([]);
          setError("规则已修改，请点击“确认并使用”进行后端校验。");
        }}
      />
    </>
  );
}
