import { lazy, Suspense } from "react";
import type { RouteObject } from "react-router-dom";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "../components/AppLayout/AppLayout";
import { AuditPage } from "../pages/AuditPage";
import { BacktestDetailPage, BacktestPage } from "../pages/BacktestPage";
import { DashboardPage } from "../pages/DashboardPage";
import { GettingStartedPage } from "../pages/GettingStartedPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { ReplayRunDetailPage, ReplayRunsPage } from "../pages/ReplayPages";
import { MarketDataCenterPage } from "../pages/MarketDataCenterPage";
import { IntradayMarketDataPage } from "../pages/IntradayMarketDataPage";
import {
  InformationCenterPage,
  InformationDetailPage,
  MarketEventsPage,
} from "../pages/InformationPages";
import { OrdersPage } from "../pages/OrdersPage";
import {
  AIAnalysisDetailPage,
  AIResearchPage,
  ResearchInsightDetailPage,
  ResearchInsightsPage,
} from "../pages/AIResearchPages";
import { PortfolioPage } from "../pages/PortfolioPage";
import {
  RiskDecisionDetailPage,
  RiskDecisionsPage,
  RiskLimitsPage,
} from "../pages/RiskPages";
import { SettingsPage } from "../pages/SettingsPage";
import { ScannersPage } from "../pages/ScannersPage";
import { ScanRunDetailPage, ScanRunsPage } from "../pages/ScanRunsPage";
import { StrategiesPage } from "../pages/StrategiesPage";
import {
  StrategyExperimentDetailPage,
  StrategyExperimentsPage,
} from "../pages/StrategyExperimentsPage";
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

const FillsPage = lazy(() =>
  import("../pages/FillsPage").then((module) => ({
    default: module.FillsPage,
  })),
);

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "getting-started", element: <GettingStartedPage /> },
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
      { path: "market-data-center", element: <MarketDataCenterPage /> },
      { path: "intraday-market-data", element: <IntradayMarketDataPage /> },
      { path: "portfolio", element: <PortfolioPage /> },
      { path: "scanners", element: <ScannersPage /> },
      { path: "scan-runs", element: <ScanRunsPage /> },
      { path: "scan-runs/:runId", element: <ScanRunDetailPage /> },
      { path: "information", element: <InformationCenterPage /> },
      { path: "information/:itemId", element: <InformationDetailPage /> },
      { path: "market-events", element: <MarketEventsPage /> },
      {
        path: "market-events/:eventId",
        element: <InformationDetailPage eventMode />,
      },
      { path: "ai-research", element: <AIResearchPage /> },
      { path: "ai-analyses/:analysisId", element: <AIAnalysisDetailPage /> },
      { path: "research-insights", element: <ResearchInsightsPage /> },
      {
        path: "research-insights/:insightId",
        element: <ResearchInsightDetailPage />,
      },
      { path: "strategies", element: <StrategiesPage /> },
      { path: "strategy-experiments", element: <StrategyExperimentsPage /> },
      {
        path: "strategy-experiments/:experimentId",
        element: <StrategyExperimentDetailPage />,
      },
      { path: "strategy-runs", element: <StrategyRunsPage /> },
      { path: "strategy-runs/:runId", element: <StrategyRunDetailPage /> },
      { path: "signals", element: <SignalsPage /> },
      { path: "orders", element: <OrdersPage /> },
      {
        path: "fills",
        element: (
          <Suspense
            fallback={<div aria-label="成交页面加载中">加载成交记录…</div>}
          >
            <FillsPage />
          </Suspense>
        ),
      },
      { path: "risk", element: <RiskDecisionsPage /> },
      { path: "risk/decisions", element: <RiskDecisionsPage /> },
      {
        path: "risk/decisions/:decisionId",
        element: <RiskDecisionDetailPage />,
      },
      { path: "risk/limits", element: <RiskLimitsPage /> },
      { path: "backtest", element: <BacktestPage /> },
      { path: "backtest/:backtestId", element: <BacktestDetailPage /> },
      { path: "replays", element: <ReplayRunsPage /> },
      { path: "replays/:replayId", element: <ReplayRunDetailPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
