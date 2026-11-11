import { useState } from "react";
import type { WebReport } from "../types";

interface ReportTabProps {
  report: WebReport | null;
  onRefresh: (force: boolean) => Promise<void>;
  onCrawl: () => Promise<void>;
}

function formatTime(value: string): string {
  if (!value) return "";
  const formatted = value.replace("T", " ");
  return formatted.length >= 16 ? formatted.slice(5, 16) : formatted;
}

function safeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function ReportTab({ report, onRefresh, onCrawl }: ReportTabProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [crawling, setCrawling] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh(true);
    } finally {
      setRefreshing(false);
    }
  };

  const crawl = async () => {
    setCrawling(true);
    try {
      await onCrawl();
    } finally {
      setCrawling(false);
    }
  };

  return (
    <section className="tab-panel active">
      <div className="panel-head">
        <div>
          <h2>数据报告</h2>
          <p className="hint">按关注词组分组的命中新闻；同一新闻多次上榜会累计次数并显示上榜时间跨度。</p>
        </div>
        <div className="panel-actions">
          <button className="btn" type="button" disabled={crawling} onClick={() => void crawl()}>
            {crawling ? "⏳ 抓取中…" : "⚡ 立即抓取"}
          </button>
          <button className="btn btn-primary" type="button" disabled={refreshing} onClick={() => void refresh()}>
            {refreshing ? "⏳ 刷新中…" : "🔄 刷新报告"}
          </button>
        </div>
      </div>

      {report && (
        <>
          <div className="summary-cards">
            <SummaryCard value={`${report.range.days} 天`} label="统计范围" />
            <SummaryCard value={report.total_news} label="榜上新闻总数" />
            <SummaryCard value={report.total_matched} label="命中关注词" />
            <SummaryCard value={report.groups.length} label="关注词组" />
          </div>
          {!report.groups.length ? (
            <div className="empty">
              <span className="big">🌱</span>
              统计范围内还没有命中关注词的新闻。<br />
              点击「立即抓取」跑一轮，或等自动监控到点执行。
            </div>
          ) : report.groups.map((group) => (
            <section className="report-group" key={group.name}>
              <div className="report-group-head">
                <h3>{group.name}</h3>
                <span className="report-group-count">{group.count} 条</span>
              </div>
              <ul className="news-list">
                {group.news.map((news, index) => {
                  const rank = news.ranks.length ? Math.min(...news.ranks) : "-";
                  const url = safeUrl(news.url);
                  return (
                    <li className="news-item" key={`${news.platform}-${news.title}-${index}`}>
                      <span className={`news-rank${typeof rank === "number" && rank <= 3 ? " top" : ""}`}>
                        {rank}
                      </span>
                      <div className="news-main">
                        <div className="news-title">
                          {url
                            ? <a href={url} target="_blank" rel="noopener noreferrer">{news.title}</a>
                            : news.title}
                        </div>
                        <div className="news-meta">
                          <span className="tag">{news.platform}</span>
                          {formatTime(news.first_time)} 上榜
                          {news.count > 1 && ` · 累计 ${news.count} 次`}
                          {news.first_time !== news.last_time && ` · 至 ${formatTime(news.last_time)}`}
                        </div>
                      </div>
                      {news.count > 1 && <span className="news-count">×{news.count}</span>}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </>
      )}
    </section>
  );
}

function SummaryCard({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="summary-card">
      <div className="num">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}
