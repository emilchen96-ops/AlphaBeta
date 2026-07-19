import { Alert } from "antd";

import { PageHeader } from "../components/PageHeader/PageHeader";

export function SettingsPage() {
  return (
    <section>
      <PageHeader
        title="设置（只读）"
        description="本地开发环境与能力状态说明。"
      />
      <Alert
        type="warning"
        showIcon
        title="认证尚未启用"
        description="M01 仅供本地开发，不包含用户、登录、JWT 或权限系统，禁止部署到公网。"
      />
      <div className="placeholder-panel">
        当前没有可编辑或可保存的设置。AI、行情、回测和 MiniQMT
        的权威状态请在“系统总览 / 功能可用性”查看。
      </div>
    </section>
  );
}
