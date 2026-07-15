import { Alert } from "antd";

import { PageHeader } from "../components/PageHeader/PageHeader";

export function SettingsPage() {
  return (
    <section>
      <PageHeader title="设置" description="本地开发环境与应用信息。" />
      <Alert
        type="warning"
        showIcon
        title="认证尚未启用"
        description="M01 仅供本地开发，不包含用户、登录、JWT 或权限系统，禁止部署到公网。"
      />
      <div className="placeholder-panel">M01 基础页面，功能尚未实现</div>
    </section>
  );
}
