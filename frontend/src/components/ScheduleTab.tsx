import { useEffect, useMemo, useState } from "react";
import type { PlatformCatalogResponse, WebConfig } from "../types";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const QUICK_TIMES = ["08:00", "12:00", "20:00"];

interface ScheduleTabProps {
  config: WebConfig;
  catalog: PlatformCatalogResponse;
  onChange: (config: WebConfig) => void;
  onSave: (config: WebConfig) => void;
  onError: (message: string) => void;
}

export function ScheduleTab({ config, catalog, onChange, onSave, onError }: ScheduleTabProps) {
  const [search, setSearch] = useState("");
  const [newTime, setNewTime] = useState("08:00");
  const [rangeDays, setRangeDays] = useState(String(config.report.range_days || 7));

  useEffect(() => {
    setRangeDays(String(config.report.range_days || 7));
  }, [config.report.range_days]);

  const enabledCount = useMemo(
    () => config.platforms.filter((platform) => platform.enabled !== false).length,
    [config.platforms],
  );
  const visiblePlatforms = catalog.catalog.filter((platform) => {
    const query = search.trim().toLocaleLowerCase();
    return !query || platform.id.toLocaleLowerCase().includes(query) || platform.name.includes(query);
  });

  const updateSchedule = (schedule: Partial<WebConfig["schedule"]>) => {
    onChange({ ...config, schedule: { ...config.schedule, ...schedule } });
  };

  const updatePlatform = (id: string, name: string, enabled: boolean) => {
    const platforms = [...config.platforms];
    const index = platforms.findIndex((platform) => platform.id === id);
    if (index === -1) {
      platforms.push({ id, name, domain: catalog.domains[id] ?? "", enabled });
    } else {
      platforms[index] = { ...platforms[index], enabled };
    }
    onChange({ ...config, platforms });
  };

  const addTime = (time: string) => {
    if (!/^\d{2}:\d{2}$/.test(time)) {
      onError("时间格式应为 HH:MM");
      return;
    }
    if (config.schedule.times.includes(time)) {
      onError("该时间已存在");
      return;
    }
    updateSchedule({ times: [...config.schedule.times, time].sort() });
  };

  const save = () => {
    const days = Number.parseInt(rangeDays, 10);
    if (!days || days < 1 || days > 90) {
      onError("统计范围需在 1-90 天之间");
      return;
    }
    onSave({
      ...config,
      report: { ...config.report, range_days: days },
    });
  };

  return (
    <section className="tab-panel active">
      <div className="panel-head">
        <div>
          <h2>监控时间与开关</h2>
          <p className="hint">自动监控开启后，系统会在下方设定的时刻自动抓取；关闭则只在你手动点击「立即抓取」时运行。</p>
        </div>
        <div className="panel-actions">
          <button className="btn btn-primary" type="button" onClick={save}>保存设置</button>
        </div>
      </div>

      <div className="card">
        <div className="row-between">
          <div>
            <h3>自动监控</h3>
            <p className="hint-inline">总开关。开启后按「监控星期 + 监控时间」自动抓取</p>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={config.schedule.enabled}
              onChange={(event) => updateSchedule({ enabled: event.target.checked })}
            />
            <span className="slider" />
          </label>
        </div>
      </div>

      <div className="card">
        <h3>监控星期</h3>
        <div className="chips">
          {WEEKDAYS.map((label, index) => {
            const day = index + 1;
            const selected = config.schedule.weekdays.includes(day);
            return (
              <button
                className={`chip${selected ? " on" : ""}`}
                key={day}
                type="button"
                aria-pressed={selected}
                onClick={() => updateSchedule({
                  weekdays: selected
                    ? config.schedule.weekdays.filter((value) => value !== day)
                    : [...config.schedule.weekdays, day].sort(),
                })}
              >
                周{label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card">
        <h3>监控时间 <span className="hint-inline">每天在这些时刻自动抓取</span></h3>
        <div className="chips">
          {config.schedule.times.length ? [...config.schedule.times].sort().map((time) => (
            <span className="chip on" key={time}>
              🕐 {time}
              <button
                className="chip-del"
                type="button"
                title={`删除 ${time}`}
                aria-label={`删除监控时间 ${time}`}
                onClick={() => updateSchedule({
                  times: config.schedule.times.filter((value) => value !== time),
                })}
              >
                ×
              </button>
            </span>
          )) : <span className="hint-inline">尚未添加监控时间</span>}
        </div>
        <div className="row gap">
          <input
            type="time"
            className="input time-input"
            value={newTime}
            onChange={(event) => setNewTime(event.target.value)}
          />
          <button className="btn" type="button" onClick={() => addTime(newTime)}>添加时间</button>
          <span className="hint-inline">快捷：</span>
          {QUICK_TIMES.map((time) => (
            <button className="btn btn-ghost" key={time} type="button" onClick={() => addTime(time)}>
              {time}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="grid-2">
          <div>
            <h3>时区</h3>
            <select
              className="input"
              value={config.schedule.timezone || "Asia/Shanghai"}
              onChange={(event) => updateSchedule({ timezone: event.target.value })}
            >
              <option value="Asia/Shanghai">Asia/Shanghai（北京时间）</option>
              <option value="Asia/Tokyo">Asia/Tokyo（东京时间）</option>
              <option value="Asia/Singapore">Asia/Singapore（新加坡时间）</option>
              <option value="Europe/London">Europe/London（伦敦时间）</option>
              <option value="America/New_York">America/New_York（美东时间）</option>
              <option value="UTC">UTC</option>
            </select>
          </div>
          <div>
            <h3>报告统计范围（天）</h3>
            <input
              type="number"
              className="input"
              min="1"
              max="90"
              value={rangeDays}
              onChange={(event) => {
                setRangeDays(event.target.value);
              }}
            />
            <p className="hint-inline">整周汇总 = 7；整月 = 30。报告会合并这些天的数据</p>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="row-between">
          <h3>监控平台 <span className="hint-inline">已启用 {enabledCount} / {catalog.catalog.length}</span></h3>
          <div className="row gap platform-actions">
            <input
              className="input input-sm"
              type="search"
              placeholder="搜索平台…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => onChange({
                ...config,
                platforms: catalog.catalog.map((platform) => ({
                  ...platform,
                  domain: catalog.domains[platform.id] ?? "",
                  enabled: true,
                })),
              })}
            >
              全选
            </button>
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => onChange({
                ...config,
                platforms: config.platforms.map((platform) => ({ ...platform, enabled: false })),
              })}
            >
              全不选
            </button>
          </div>
        </div>
        <div className="platform-grid">
          {visiblePlatforms.map((platform) => {
            const selected = config.platforms.some(
              (item) => item.id === platform.id && item.enabled !== false,
            );
            return (
              <label className={`platform-item${selected ? " on" : ""}`} key={platform.id}>
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={(event) => updatePlatform(platform.id, platform.name, event.target.checked)}
                />
                {platform.name}
              </label>
            );
          })}
        </div>
      </div>
    </section>
  );
}
