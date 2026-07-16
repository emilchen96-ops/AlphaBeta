import { lazy, Suspense } from "react";
import type { RouteObject } from "react-router-dom";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "../components/AppLayout/AppLayout";
import { AuditPage } from "../pages/AuditPage";
import { BacktestPage } from "../pages/BacktestPage";
import { DashboardPage } from "../pages/DashboardPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { OrdersPage } from "../pages/OrdersPage";
import { PortfolioPage } from "../pages/PortfolioPage";
import { RiskPage } from "../pages/RiskPage";
import { SettingsPage } from "../pages/SettingsPage";
import { StrategiesPage } from "../pages/StrategiesPage";
import { SignalsPage } from "../pages/SignalsPage";
import {
  StrategyRunDetailPage,
  StrategyRunsPage,
} from "../pages/StrategyRunsPage";

const MarketPage = lazy(() =>
  import("../pages/MarketPage").then((module) => ({
    default: module.MarketPage,
  })),
);

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      {
        path: "market",
        element: (
          <Suspense
            fallback={<div aria-label="行情页面加载中">加载行情工作台…</div>}
          >
            <MarketPage />
          </Suspense>
        ),
      },
      { path: "portfolio", element: <PortfolioPage /> },
      { path: "strategies", element: <StrategiesPage /> },
      { path: "strategy-runs", element: <StrategyRunsPage /> },
      { path: "strategy-runs/:runId", element: <StrategyRunDetailPage /> },
      { path: "signals", element: <SignalsPage /> },
      { path: "orders", element: <OrdersPage /> },
      { path: "risk", element: <RiskPage /> },
      { path: "backtest", element: <BacktestPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
