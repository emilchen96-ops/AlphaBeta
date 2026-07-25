import { Spin } from "antd";
import type { ReactNode } from "react";
import { Navigate, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../AppLayout/AppLayout";

export function LegacyFullSimulationRoute({
  children,
  researchPath,
}: {
  children: ReactNode;
  researchPath: string;
}) {
  const { status, isLoading } = useOutletContext<AppOutletContext>();
  if (isLoading) {
    return <Spin description="正在确认产品模式…" fullscreen />;
  }
  // Older deployments did not expose product_mode. Preserve their legacy
  // routes; only the explicit RESEARCH_ONLY mode performs product redirects.
  if (status?.product_mode === "RESEARCH_ONLY") {
    return <Navigate to={researchPath} replace />;
  }
  return children;
}
