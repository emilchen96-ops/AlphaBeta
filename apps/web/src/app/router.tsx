import type { RouteObject } from "react-router-dom";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "../components/AppLayout/AppLayout";
import { AuditPage } from "../pages/AuditPage";
import { BacktestPage } from "../pages/BacktestPage";
import { DashboardPage } from "../pages/DashboardPage";
import { MarketPage } from "../pages/MarketPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { OrdersPage } from "../pages/OrdersPage";
import { PortfolioPage } from "../pages/PortfolioPage";
import { RiskPage } from "../pages/RiskPage";
import { SettingsPage } from "../pages/SettingsPage";
import { StrategiesPage } from "../pages/StrategiesPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "market", element: <MarketPage /> },
      { path: "portfolio", element: <PortfolioPage /> },
      { path: "strategies", element: <StrategiesPage /> },
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
