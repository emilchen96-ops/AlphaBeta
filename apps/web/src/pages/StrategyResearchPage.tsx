import {
  ArrowRightOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  LineChartOutlined,
} from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Tag, Typography } from "antd";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader/PageHeader";

export function StrategyResearchPage() {
  return (
    <section>
      <PageHeader
        title="策略研究"
        description="从一个策略和一只股票开始，完成回测、查看结果，再按需要比较参数。"
      />
      <Card className="research-primary-card">
        <Space orientation="vertical" size={14}>
          <Space wrap>
            <Tag color="blue">推荐入口</Tag>
            <Typography.Text type="secondary">
              适合“选策略 → 设参数 → 运行 → 看收益与回撤”的完整研究流程
            </Typography.Text>
          </Space>
          <Typography.Title level={3}>快速回测</Typography.Title>
          <Typography.Paragraph>
            使用 MiniQMT
            已同步到本地的历史日线，模拟策略信号、风控、订单、成交和资金变化，并生成收益、回撤和交易记录。
          </Typography.Paragraph>
          <Link to="/backtest">
            <Button type="primary" size="large" icon={<LineChartOutlined />}>
              开始回测
            </Button>
          </Link>
        </Space>
      </Card>

      <Row gutter={[16, 16]} className="backtest-section">
        <Col xs={24} lg={8}>
          <Card title="选择策略模板" extra={<ExperimentOutlined />}>
            <Typography.Paragraph type="secondary">
              查看策略用途和参数说明。策略模板只定义研究逻辑，不会自动下单。
            </Typography.Paragraph>
            <Link to="/strategies">
              <Button icon={<ArrowRightOutlined />}>查看策略</Button>
            </Link>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="比较参数组合" extra={<ExperimentOutlined />}>
            <Typography.Paragraph type="secondary">
              批量比较不同参数产生的研究信号；这里不是完整收益回测，最终效果请回到快速回测确认。
            </Typography.Paragraph>
            <Link to="/strategy-experiments">
              <Button icon={<ArrowRightOutlined />}>进入参数比较</Button>
            </Link>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="高级研究记录" extra={<HistoryOutlined />}>
            <Typography.Paragraph type="secondary">
              查看策略运行、研究信号和逐日回放等底层记录，适合排查策略为什么在某天触发。
            </Typography.Paragraph>
            <Space wrap>
              <Link to="/strategy-runs">
                <Button>策略运行</Button>
              </Link>
              <Link to="/signals">
                <Button>研究信号</Button>
              </Link>
              <Link to="/replays">
                <Button>历史回放</Button>
              </Link>
            </Space>
          </Card>
        </Col>
      </Row>
    </section>
  );
}
