import { lazy, Suspense } from "react";
import type { RouteObject } from "react-router-dom";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "../components/AppLayout/AppLayout";
import { ProductModeRoute } from "../components/ProductModeRoute/ProductModeRoute";
import { AuditPage } from "../pages/AuditPage";
import { BacktestDetailPage, BacktestPage } from "../pages/BacktestPage";
import { DashboardPage } from "../pages/DashboardPage";
import { GettingStartedPage } from "../pages/GettingStartedPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { ReplayRunDetailPage } from "../pages/ReplayPages";
import { MarketDataCenterPage } from "../pages/MarketDataCenterPage";
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
import { StrategyRunDetailPage } from "../pages/StrategyRunsPage";
import { StrategyResearchPage } from "../pages/StrategyResearchPage";
import { ResearchHistoryPage } from "../pages/ResearchHistoryPage";
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
      { path: "watchlists", element: <Navigate to="/market?focus=watchlists" replace /> },
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
      { path: "strategy-research", element: <Navigate to="/research/backtest" replace /> },
      { path: "strategies", element: <Navigate to="/research/templates" replace /> },
      {
        path: "strategy-experiments",
        element: <Navigate to="/research/parameter-comparison" replace />,
      },
      {
        path: "strategy-experiments/:experimentId",
        element: <StrategyExperimentDetailPage />,
      },
      {
        path: "strategy-runs",
        element: <Navigate to="/research/history?tab=runs" replace />,
      },
      { path: "strategy-runs/:runId", element: <StrategyRunDetailPage /> },
      {
        path: "signals",
        element: <Navigate to="/research/history?tab=backtests" replace />,
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
      { path: "backtest", element: <Navigate to="/research/backtest" replace /> },
      {
        path: "backtest/:backtestId",
        element: <BacktestDetailPage />,
      },
      {
        path: "replays",
        element: <Navigate to="/research/history?tab=backtests" replace />,
      },
      { path: "replays/:replayId", element: <ReplayRunDetailPage /> },
      {
        path: "research",
        element: <ResearchWorkspace />,
        children: [
          { index: true, element: <Navigate to="backtest" replace /> },
          { path: "backtest", element: <BacktestPage /> },
          { path: "templates", element: <StrategiesPage /> },
          {
            path: "parameter-comparison",
            element: <StrategyExperimentsPage />,
          },
          { path: "my-strategies", element: <StrategyResearchPage /> },
        ],
      },
      { path: "research/history", element: <ResearchHistoryPage /> },
      {
        path: "research/backtests/:backtestId",
        element: <BacktestDetailPage />,
      },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
