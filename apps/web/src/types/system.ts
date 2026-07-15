export type ServiceState = "online" | "offline";
export type WebSocketState = "connected" | "connecting" | "disconnected";

export interface SystemStatus {
  api: "online";
  postgresql: ServiceState;
  redis: ServiceState;
  environment: string;
  version: string;
  server_time: string;
  correlation_id: string;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: unknown;
    correlation_id: string;
    timestamp: string;
  };
}
