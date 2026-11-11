import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, request } from "./api";
import { KeywordsTab } from "./components/KeywordsTab";
import { ReportTab } from "./components/ReportTab";
import { ScheduleTab } from "./components/ScheduleTab";
import { TokenDialog } from "./components/TokenDialog";
import type {
  PlatformCatalogResponse,
  StatusResponse,
  TabId,
  WebConfig,
  WebReport,
} from "./types";

interface ToastMessage {
  text: string;
  kind: "ok" | "err";
}

function savedToken(): string {
  return localStorage.getItem("tr_token") ?? "";
}

function formatTime(value: string): string {
  const formatted = value.replace("T", " ");
  return formatted.length >= 16 ? formatted.slice(5, 16) : formatted;
}

export default function App() {
  const [token, setToken] = useState(savedToken);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [config, setConfig] = useState<WebConfig | null>(null);
  const [catalog, setCatalog] = useState<PlatformCatalogResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [report, setReport] = useState<WebReport | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("keywords");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const notifyError = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) {
      setTokenDialogOpen(true);
      return;
    }
    setToast({
      text: error instanceof Error ? error.message : "发生未知错误",
      kind: "err",
    });
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await request<StatusResponse>("/api/status", token));
    } catch (error) {
      notifyError(error);
    }
  }, [notifyError, token]);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [platformData, configData] = await Promise.all([
        request<PlatformCatalogResponse>("/api/platforms", token),
        request<{ config: WebConfig }>("/api/config", token),
      ]);
      setCatalog(platformData);
      setConfig(configData.config);
      await loadStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "页面初始化失败";
      setLoadError(message);
      notifyError(error);
    } finally {
      setLoading(false);
    }
  }, [loadStatus, notifyError, token]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), toast.kind === "err" ? 6000 : 3000);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const saveConfig = async (nextConfig: WebConfig, message: string) => {
    setConfig(nextConfig);
    try {
      await request("/api/config", token, {
        method: "POST",
        body: { config: nextConfig },
      });
      setToast({ text: message, kind: "ok" });
      await loadStatus();
    } catch (error) {
      notifyError(error);
    }
  };

  const loadReport = async (refresh = false) => {
    try {
      const result = await request<{ report: WebReport }>(
        `/api/report${refresh ? "?refresh=1" : ""}`,
        token,
      );
      setReport(result.report);
      if (refresh) setToast({ text: "报告已刷新", kind: "ok" });
    } catch (error) {
      notifyError(error);
    }
  };

  const runCrawl = async () => {
    try {
      const result = await request<{
        ok: boolean;
        platforms_success: number;
        new_titles: number;
        error?: string;
      }>("/api/crawl", token, { method: "POST", body: {} });
      if (!result.ok) throw new Error(result.error || "抓取失败");
      setToast({
        text: `抓取完成：${result.platforms_success} 个平台成功，新增 ${result.new_titles} 条`,
        kind: "ok",
      });
      await loadReport(true);
    } catch (error) {
      notifyError(error);
    } finally {
      await loadStatus();
    }
  };

  const changeTab = (tab: TabId) => {
    setActiveTab(tab);
    if (tab === "schedule") void loadStatus();
    if (tab === "report") void loadReport();
  };

  const saveToken = (nextToken: string) => {
    localStorage.setItem("tr_token", nextToken);
    setToken(nextToken);
    setTokenDialogOpen(false);
    setToast({ text: "令牌已保存", kind: "ok" });
  };

  return (
    <>
      <header className="topbar">
        <div className="topbar-left">
          <span className="logo" aria-hidden="true">📡</span>
          <div>
            <h1>TrendRadar 热点监控</h1>
            <p className="subtitle">关注领域热榜 · 自动监控 · 整周汇总</p>
          </div>
        </div>
        <div className="topbar-right">
          <StatusBadges status={status} />
          <button className="btn btn-ghost" type="button" onClick={() => setTokenDialogOpen(true)}>
            🔑 令牌
          </button>
        </div>
      </header>

      <nav className="tabs" aria-label="监控页面">
        <TabButton id="keywords" active={activeTab} onSelect={changeTab}>🔍 监控关键词</TabButton>
        <TabButton id="schedule" active={activeTab} onSelect={changeTab}>⏰ 监控设置</TabButton>
        <TabButton id="report" active={activeTab} onSelect={changeTab}>📊 数据报告</TabButton>
      </nav>

      <main>
        {loading ? (
          <div className="empty" role="status">正在加载配置…</div>
        ) : loadError ? (
          <div className="empty" role="alert">
            <span className="big">⚠️</span>
            页面加载失败：{loadError}
            <div className="panel-actions retry-actions">
              <button className="btn btn-primary" type="button" onClick={() => void loadDashboard()}>
                重试
              </button>
            </div>
          </div>
        ) : config && catalog ? (
          <>
            {activeTab === "keywords" && (
              <KeywordsTab
                config={config}
                onChange={setConfig}
                onSave={(value) => void saveConfig(value, "词表已保存")}
              />
            )}
            {activeTab === "schedule" && (
              <ScheduleTab
                config={config}
                catalog={catalog}
                onChange={setConfig}
                onSave={(value) => void saveConfig(value, "监控设置已保存")}
                onError={(message) => setToast({ text: message, kind: "err" })}
              />
            )}
            {activeTab === "report" && (
              <ReportTab
                report={report}
                onRefresh={(force) => loadReport(force)}
                onCrawl={runCrawl}
              />
            )}
          </>
        ) : null}
      </main>

      <TokenDialog
        open={tokenDialogOpen}
        onCancel={() => setTokenDialogOpen(false)}
        onSave={saveToken}
      />

      {toast && (
        <div className={`toast ${toast.kind}`} role="status" aria-live="polite">
          {toast.text}
        </div>
      )}
    </>
  );
}

function TabButton({
  id,
  active,
  onSelect,
  children,
}: {
  id: TabId;
  active: TabId;
  onSelect: (tab: TabId) => void;
  children: ReactNode;
}) {
  return (
    <button
      className={`tab${active === id ? " active" : ""}`}
      type="button"
      aria-pressed={active === id}
      onClick={() => onSelect(id)}
    >
      {children}
    </button>
  );
}

function StatusBadges({ status }: { status: StatusResponse | null }) {
  let backendLabel = "…";
  let backendClass = "badge";
  let backendTitle = "存储后端";
  if (status?.backend === "kv") {
    backendLabel = "☁️ Vercel KV";
    backendClass = "badge ok";
    backendTitle = "配置与数据持久化存储（Vercel KV）";
  } else if (status?.backend === "memory") {
    backendLabel = "⚠️ 临时存储";
    backendClass = "badge warn";
    backendTitle = "存储不可用，数据仅存内存，冷启动后丢失；请在 Vercel 控制台绑定 KV";
  } else if (status) {
    backendLabel = "💾 本地存储";
    backendTitle = status.persistent === false
      ? "临时存储：冷启动/重启后数据丢失，建议在 Vercel 控制台绑定 KV 持久化"
      : "配置与数据存于本地 web_data/ 目录";
  }

  const lastCrawl = status?.last_crawl;
  const crawlStats = lastCrawl?.stats;

  return (
    <>
      <span className={backendClass} title={backendTitle}>{backendLabel}</span>
      <span
        className={`badge${status?.schedule.enabled ? " ok" : " off"}`}
        title={status?.schedule.enabled ? `监控时刻：${status.schedule.times.join(" / ")}` : "自动监控关闭"}
      >
        {status ? (status.schedule.enabled ? "⏰ 自动监控 开" : "⏸ 自动监控 关") : "…"}
      </span>
      <span
        className={`badge${lastCrawl?.time ? (lastCrawl.status === "success" ? " ok" : " warn") : ""}`}
        title={crawlStats
          ? `${crawlStats.platforms_success}/${crawlStats.platforms_total} 平台成功，新增 ${crawlStats.new_titles} 条，耗时 ${crawlStats.duration_seconds}s`
          : "最近一次抓取"}
      >
        {lastCrawl?.time ? `最近抓取 ${formatTime(lastCrawl.time)}` : status ? "尚未抓取" : "…"}
      </span>
    </>
  );
}
