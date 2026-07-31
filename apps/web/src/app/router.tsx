import { lazy, Suspense } from "react";
import type { RouteObject } from "react-router-dom";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "../components/AppLayout/AppLayout";
import { ProductModeRoute } from "../components/ProductModeRoute/ProductModeRoute";
import { LegacyFullSimulationRoute } from "../components/ProductModeRoute/LegacyFullSimulationRoute";
import { AuditPage } from "../pages/AuditPage";
import { BacktestDetailPage, BacktestPage } from "../pages/BacktestPage";
import { DashboardPage } from "../pages/DashboardPage";
import { GettingStartedPage } from "../pages/GettingStartedPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { ReplayRunDetailPage, ReplayRunsPage } from "../pages/ReplayPages";
import { MarketDataCenterPage } from "../pages/MarketDataCenterPage";
import { InformationDetailPage } from "../pages/InformationPages";
import { OrdersPage } from "../pages/OrdersPage";
import {
  AIAnalysisDetailPage,
  ResearchInsightDetailPage,
  ResearchInsightsPage,
} from "../pages/AIResearchPages";
import {
  AIResearchReportPage,
  AIResearchTaskPage,
  AIResearchWorkbenchPage,
} from "../pages/AIWorkbenchPages";
import { PortfolioPage } from "../pages/PortfolioPage";
import {
  RiskDecisionDetailPage,
  RiskDecisionsPage,
  RiskLimitsPage,
} from "../pages/RiskPages";
import { SettingsPage } from "../pages/SettingsPage";
import { ScannersPage } from "../pages/ScannersPage";
import { StrategiesPage } from "../pages/StrategiesPage";
import {
  StrategyExperimentDetailPage,
  StrategyExperimentsPage,
} from "../pages/StrategyExperimentsPage";
import {
  StrategyRunDetailPage,
  StrategyRunsPage,
} from "../pages/StrategyRunsPage";
import { SignalsPage } from "../pages/SignalsPage";
import { StrategyResearchPage } from "../pages/StrategyResearchPage";
import { ResearchHistoryPage } from "../pages/ResearchHistoryPage";
import { QuickBacktestPage } from "../pages/QuickBacktestPage";
import { BacktestBatchPage } from "../pages/BacktestBatchPage";
import { ParameterComparisonPage } from "../pages/ParameterComparisonPage";
import { ResearchWorkspace } from "../components/ResearchWorkspace/ResearchWorkspace";

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
      {
        path: "watchlists",
        element: <Navigate to="/market?focus=watchlists" replace />,
      },
      { path: "market-data-center", element: <MarketDataCenterPage /> },
      {
        path: "intraday-market-data",
        element: <Navigate to="/market-data-center?tab=minute" replace />,
      },
      {
        path: "miniqmt-market-data",
        element: <Navigate to="/market" replace />,
      },
      {
        path: "portfolio",
        element: (
          <ProductModeRoute>
            <PortfolioPage />
          </ProductModeRoute>
        ),
      },
      { path: "scanners", element: <ScannersPage /> },
      {
        path: "scan-runs",
        element: <Navigate to="/scanners?tab=history" replace />,
      },
      {
        path: "scan-runs/:runId",
        element: <Navigate to="/scanners?tab=history" replace />,
      },
      {
        path: "information",
        element: <Navigate to="/ai-research?tab=materials" replace />,
      },
      { path: "information/:itemId", element: <InformationDetailPage /> },
      {
        path: "market-events",
        element: <Navigate to="/ai-research?tab=materials" replace />,
      },
      {
        path: "market-events/:eventId",
        element: <InformationDetailPage eventMode />,
      },
      { path: "ai-research", element: <AIResearchWorkbenchPage /> },
      { path: "ai-research/tasks/:taskId", element: <AIResearchTaskPage /> },
      { path: "ai-research/tasks/:taskId/report", element: <AIResearchReportPage /> },
      { path: "ai-analyses/:analysisId", element: <AIAnalysisDetailPage /> },
      { path: "research-insights", element: <ResearchInsightsPage /> },
      {
        path: "research-insights/:insightId",
        element: <ResearchInsightDetailPage />,
      },
      {
        path: "strategy-research",
        element: <Navigate to="/research/backtest" replace />,
      },
      {
        path: "strategies",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/templates">
            <StrategiesPage />
          </LegacyFullSimulationRoute>
        ),
      },
      {
        path: "strategy-experiments",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/parameter-comparison">
            <StrategyExperimentsPage />
          </LegacyFullSimulationRoute>
        ),
      },
      {
        path: "strategy-experiments/:experimentId",
        element: <StrategyExperimentDetailPage />,
      },
      {
        path: "strategy-runs",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/archive?tab=backtests">
            <StrategyRunsPage />
          </LegacyFullSimulationRoute>
        ),
      },
      { path: "strategy-runs/:runId", element: <StrategyRunDetailPage /> },
      {
        path: "signals",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/archive?tab=backtests">
            <SignalsPage />
          </LegacyFullSimulationRoute>
        ),
      },
      {
        path: "orders",
        element: (
          <ProductModeRoute>
            <OrdersPage />
          </ProductModeRoute>
        ),
      },
      {
        path: "fills",
        element: (
          <ProductModeRoute>
            <Suspense
              fallback={<div aria-label="成交页面加载中">加载成交记录…</div>}
            >
              <FillsPage />
            </Suspense>
          </ProductModeRoute>
        ),
      },
      {
        path: "risk",
        element: (
          <ProductModeRoute>
            <RiskDecisionsPage />
          </ProductModeRoute>
        ),
      },
      {
        path: "risk/decisions",
        element: (
          <ProductModeRoute>
            <RiskDecisionsPage />
          </ProductModeRoute>
        ),
      },
      {
        path: "risk/decisions/:decisionId",
        element: (
          <ProductModeRoute>
            <RiskDecisionDetailPage />
          </ProductModeRoute>
        ),
      },
      {
        path: "risk/limits",
        element: (
          <ProductModeRoute>
            <RiskLimitsPage />
          </ProductModeRoute>
        ),
      },
      {
        path: "backtest",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/backtest">
            <BacktestPage />
          </LegacyFullSimulationRoute>
        ),
      },
      {
        path: "backtest/:backtestId",
        element: <BacktestDetailPage />,
      },
      {
        path: "replays",
        element: (
          <LegacyFullSimulationRoute researchPath="/research/archive?tab=backtests">
            <ReplayRunsPage />
          </LegacyFullSimulationRoute>
        ),
      },
      { path: "replays/:replayId", element: <ReplayRunDetailPage /> },
      {
        path: "research",
        element: <ResearchWorkspace />,
        children: [
          { index: true, element: <Navigate to="backtest" replace /> },
          { path: "backtest", element: <QuickBacktestPage /> },
          { path: "templates", element: <StrategiesPage /> },
          {
            path: "parameter-comparison",
            element: <ParameterComparisonPage />,
          },
          { path: "my-strategies", element: <StrategyResearchPage /> },
        ],
      },
      {
        path: "research/history",
        element: <Navigate to="/research/archive" replace />,
      },
      { path: "research/archive", element: <ResearchHistoryPage /> },
      {
        path: "research/backtests/:backtestId",
        element: <BacktestDetailPage />,
      },
      {
        path: "research/backtest-batches/:batchId",
        element: <BacktestBatchPage />,
      },
      {
        path: "research/backtests/:backtestId/replay",
        element: <ReplayRunsPage />,
      },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
