import {
  CopyOutlined,
  EditOutlined,
  InboxOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Popconfirm,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  archiveUserStrategy,
  cloneUserStrategy,
  createUserStrategy,
  listUserStrategies,
  updateUserStrategy,
} from "../api/strategySpecs";
import { NaturalLanguageStrategyBuilder } from "../components/StrategyBuilder/NaturalLanguageStrategyBuilder";
import { StrategyRuleEditor } from "../components/StrategyBuilder/StrategyRuleEditor";
import type { StrategySpec, UserStrategy } from "../types/strategySpecs";
import { formatDateTime } from "../utils/display";

export function StrategyResearchPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<UserStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<UserStrategy | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems((await listUserStrategies()).items);
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "无法加载我的策略",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // The page owns this small CRUD list and refreshes it when the loader changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const create = async (spec: StrategySpec) => {
    try {
      await createUserStrategy({
        name: spec.name,
        description: spec.description,
        spec,
      });
      setCreateOpen(false);
      void message.success("策略已保存");
      await load();
    } catch (reason) {
      void message.error(
        reason instanceof ApiError ? reason.message : "保存策略失败",
      );
    }
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        showIcon
        type="info"
        title="我的策略会保留每次修改的版本"
        description="历史回测关联运行时的不可变规则快照，之后修改策略不会改变过去的结果。"
      />
      <div className="research-section-toolbar">
        <div>
          <Typography.Title level={3}>我的策略</Typography.Title>
          <Typography.Text type="secondary">
            保存、复制和复用自然语言或可视化规则。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新建策略
        </Button>
      </div>
      {error !== null && <Alert showIcon type="error" title={error} />}
      {!loading && items.length === 0 ? (
        <Card>
          <Empty description="还没有保存的策略">
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              用一句话创建第一个策略
            </Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {items.map((item) => (
            <Col key={item.id} xs={24} lg={12}>
              <Card
                title={item.name}
                loading={loading}
                extra={<Tag color="blue">版本 {item.current_version}</Tag>}
              >
                <Typography.Paragraph type="secondary">
                  {item.description || "用户保存的规则策略"}
                </Typography.Paragraph>
                <ul className="research-rule-preview">
                  {item.preview.slice(0, 3).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <Typography.Text type="secondary">
                  更新于 {formatDateTime(item.updated_at)}
                </Typography.Text>
                <div className="research-card-actions">
                  <Link to={`/research/backtest?user_strategy_id=${item.id}`}>
                    <Button type="primary">使用此策略回测</Button>
                  </Link>
                  <Button
                    icon={<EditOutlined />}
                    onClick={() => setEditing(item)}
                  >
                    编辑
                  </Button>
                  <Button
                    icon={<CopyOutlined />}
                    onClick={() =>
                      void cloneUserStrategy(item.id).then(async () => {
                        void message.success("已创建策略副本");
                        await load();
                      })
                    }
                  >
                    复制
                  </Button>
                  <Popconfirm
                    title="归档这个策略？"
                    description="归档后默认不再显示，历史回测不受影响。"
                    onConfirm={() =>
                      void archiveUserStrategy(item.id).then(async () => {
                        void message.success("策略已归档");
                        await load();
                      })
                    }
                  >
                    <Button icon={<InboxOutlined />}>归档</Button>
                  </Popconfirm>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
      <Modal
        open={createOpen}
        title="创建策略"
        footer={null}
        width={800}
        destroyOnHidden
        onCancel={() => setCreateOpen(false)}
      >
        <NaturalLanguageStrategyBuilder
          onConfirmed={(spec) => void create(spec)}
        />
      </Modal>
      <StrategyRuleEditor
        open={editing !== null}
        spec={editing?.spec ?? null}
        onCancel={() => setEditing(null)}
        onSave={(spec) => {
          if (editing === null) return;
          void updateUserStrategy(editing.id, {
            name: spec.name,
            description: spec.description,
            spec,
          })
            .then(async () => {
              setEditing(null);
              void message.success("已保存为新版本");
              await load();
            })
            .catch((reason: unknown) => {
              void message.error(
                reason instanceof ApiError ? reason.message : "更新策略失败",
              );
            });
        }}
      />
    </Space>
  );
}
