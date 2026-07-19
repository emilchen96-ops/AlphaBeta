import { Alert, Empty } from "antd";

import { PageHeader } from "../components/PageHeader/PageHeader";

export function BacktestPage() {
  return (
    <section>
      <PageHeader
        title="回测"
        description="BT01 当前为独立分支中的部分实现，尚未进入 V0.1 集成基线。"
      />
      <Alert
        showIcon
        type="warning"
        title="部分完成，当前分支不可用"
        description="为避免 0011 Migration 冲突和误报结果，I01 不提供启动回测按钮。后续由 BT01-R 重建单一 Migration 链并完成专项验收。"
      />
      <div className="placeholder-panel">
        <Empty description="当前没有可运行的回测入口或回测结果" />
      </div>
    </section>
  );
}
