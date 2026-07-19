import { Alert, Empty } from "antd";

import { PageHeader } from "../components/PageHeader/PageHeader";

export function AuditPage() {
  return (
    <section>
      <PageHeader title="审计" description="完整审计中心尚未实现。" />
      <Alert
        showIcon
        type="info"
        title="计划开发"
        description="数据库已保存部分 DomainEvent、AuditLog 和业务完整性事实，但当前没有统一审计查询 API 或可用操作。"
      />
      <div className="placeholder-panel">
        <Empty description="尚未实现统一审计中心" />
      </div>
    </section>
  );
}
