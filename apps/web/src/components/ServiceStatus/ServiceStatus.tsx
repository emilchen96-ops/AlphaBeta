import { Badge, Space, Typography } from "antd";

import type { ServiceState, WebSocketState } from "../../types/system";

type Status = ServiceState | WebSocketState | "normal";

const labels: Record<Status, string> = {
  online: "在线",
  offline: "离线",
  connected: "已连接",
  connecting: "连接中",
  disconnected: "已断开",
  normal: "正常",
};

const badgeStatuses: Record<
  Status,
  "success" | "error" | "processing" | "default"
> = {
  online: "success",
  offline: "error",
  connected: "success",
  connecting: "processing",
  disconnected: "error",
  normal: "success",
};

interface ServiceStatusProps {
  name: string;
  status: Status;
  compact?: boolean;
}

export function ServiceStatus({
  name,
  status,
  compact = false,
}: ServiceStatusProps) {
  return (
    <Space size={compact ? 5 : 8} aria-label={`${name}：${labels[status]}`}>
      <Badge status={badgeStatuses[status]} />
      <Typography.Text
        className={compact ? "service-status-compact" : undefined}
      >
        {name} · {labels[status]}
      </Typography.Text>
    </Space>
  );
}
