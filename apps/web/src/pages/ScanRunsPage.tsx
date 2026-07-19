import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getScannerCatalog,
  getScanResults,
  getScanRun,
  getScanRuns,
} from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { ScanResult, ScanRun } from "../types/scanners";

const statusText: Record<string, string> = {
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "运行失败",
};

const warning = (
  <Alert
    showIcon
    type="info"
    title="历史规则筛选，不代表投资建议"
    description="当前不是实时扫描，不会自动创建订单、调用风控或 Broker，也不会修改账户和账本。"
  />
);

export function ScanRunsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [scannerKey, setScannerKey] = useState<string>();
  const [status, setStatus] = useState<string>();
  const catalog = useQuery({
    queryKey: ["scanner-catalog"],
    queryFn: getScannerCatalog,
  });
  const runs = useQuery({
    queryKey: ["scan-runs", page, scannerKey, status],
    queryFn: () =>
      getScanRuns({ page, page_size: 20, scanner_key: scannerKey, status }),
  });
  return (
    <section>
      <PageHeader title="扫描运行" description="可审计的历史日线扫描记录。" />
      {warning}
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Button onClick={() => void navigate("/scanners")}>新建扫描</Button>
          <Select<string>
            allowClear
            placeholder="扫描器筛选"
            style={{ width: 220 }}
            options={catalog.data?.map((item) => ({
              value: item.scanner_key,
              label: item.display_name,
            }))}
            onChange={(value) => {
              setPage(1);
              setScannerKey(value);
            }}
          />
          <Select<string>
            allowClear
            placeholder="状态筛选"
            style={{ width: 160 }}
            options={Object.entries(statusText).map(([value, label]) => ({
              value,
              label,
            }))}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
          />
        </Space>
        <Table<ScanRun>
          rowKey="scan_run_id"
          dataSource={runs.data?.items ?? []}
          loading={runs.isLoading}
          locale={{ emptyText: <Empty description="暂无扫描运行" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: runs.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: "运行",
              render: (_, item) => item.scan_run_id.slice(0, 8),
            },
            { title: "扫描器", dataIndex: "scanner_key" },
            {
              title: "状态",
              render: (_, item) => <Tag>{statusText[item.status]}</Tag>,
            },
            {
              title: "股票池",
              render: (_, item) => item.instrument_ids.length,
            },
            { title: "已扫描", dataIndex: "instruments_scanned" },
            { title: "匹配", dataIndex: "matches_found" },
            {
              title: "截止时间",
              render: (_, item) => new Date(item.as_of).toLocaleString(),
            },
            {
              title: "操作",
              render: (_, item) => (
                <Button
                  size="small"
                  onClick={() =>
                    void navigate(`/scan-runs/${item.scan_run_id}`)
                  }
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function ScanRunDetailPage() {
  const navigate = useNavigate();
  const { runId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["scan-run", runId],
    queryFn: () => getScanRun(runId),
    enabled: Boolean(runId),
  });
  const results = useQuery({
    queryKey: ["scan-results", runId],
    queryFn: () => getScanResults(runId),
    enabled: Boolean(runId),
  });
  const item = detail.data;
  return (
    <section>
      <PageHeader title="扫描运行详情" description={runId} />
      {warning}
      <Space wrap style={{ marginTop: 16 }}>
        <Button onClick={() => void navigate("/market")}>
          Instrument 与行情
        </Button>
        <Button onClick={() => void navigate("/strategies")}>策略目录</Button>
        <Button onClick={() => void navigate("/signals")}>研究 Signal</Button>
      </Space>
      {item ? (
        <Card style={{ marginTop: 16 }}>
          {item.status === "FAILED" ? (
            <Alert
              type="error"
              title="扫描失败"
              description={item.error?.message ?? "扫描运行失败"}
            />
          ) : null}
          <Descriptions
            bordered
            column={2}
            items={[
              {
                key: "scanner",
                label: "扫描器",
                children: `${item.scanner_key} v${item.scanner_version}`,
              },
              {
                key: "status",
                label: "状态",
                children: statusText[item.status],
              },
              { key: "asof", label: "截止时间", children: item.as_of },
              { key: "timeframe", label: "周期", children: item.timeframe },
              {
                key: "universe",
                label: "股票池",
                children: `${item.instrument_ids.length} 个 Instrument`,
              },
              {
                key: "count",
                label: "结果",
                children: `${item.matches_found} / ${item.instruments_scanned}`,
              },
              {
                key: "params",
                label: "规范化参数",
                children: <pre>{JSON.stringify(item.parameters, null, 2)}</pre>,
              },
              {
                key: "completed",
                label: "完成时间",
                children: item.completed_at ?? "—",
              },
            ]}
          />
          <Typography.Title level={4}>ScanResult</Typography.Title>
          <Table<ScanResult>
            rowKey="scan_result_id"
            dataSource={results.data?.items ?? []}
            pagination={false}
            locale={{ emptyText: <Empty description="本次扫描无匹配结果" /> }}
            columns={[
              { title: "排名", dataIndex: "rank" },
              {
                title: "标的",
                render: (_, value) =>
                  `${value.instrument.symbol}.${value.instrument.exchange} · ${value.instrument.name}`,
              },
              { title: "评分", dataIndex: "score" },
              { title: "参考价", dataIndex: "reference_price" },
              {
                title: "匹配时间",
                render: (_, value) =>
                  new Date(value.matched_at).toLocaleString(),
              },
              { title: "规则说明", dataIndex: "reason" },
              {
                title: "指标",
                render: (_, value) => (
                  <pre>{JSON.stringify(value.metrics, null, 2)}</pre>
                ),
              },
            ]}
          />
        </Card>
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
