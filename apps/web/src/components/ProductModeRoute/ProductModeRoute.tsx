import { Alert, Button, Card, Space, Spin, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { Link, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../AppLayout/AppLayout";

export function ProductModeRoute({ children }: { children: ReactNode }) {
  const { status, isLoading } = useOutletContext<AppOutletContext>();

  if (isLoading) {
    return <Spin description="正在确认产品模式…" fullscreen />;
  }
  if (status?.product_mode !== "FULL_SIMULATION") {
    return (
      <Card>
        <Alert
          showIcon
          type="info"
          title="当前为研究模式，交易类页面未启用"
          description={
            <Space orientation="vertical" size={4}>
              <Tag color="blue">MiniQMT（只读）</Tag>
              <Typography.Text>
                只提供行情。模拟账户、订单、成交与风控事实仍保留在底层，但不会出现在普通研究流程中，更不会发送给券商。
              </Typography.Text>
            </Space>
          }
          action={
            <Link to="/research/backtest">
              <Button type="primary">返回策略回测</Button>
            </Link>
          }
        />
      </Card>
    );
  }
  return children;
}
