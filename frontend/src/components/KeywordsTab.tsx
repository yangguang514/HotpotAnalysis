import { useState } from "react";
import { keywordsToText, textToKeywords } from "../keywordFormat";
import type { WebConfig } from "../types";

interface KeywordsTabProps {
  config: WebConfig;
  onChange: (config: WebConfig) => void;
  onSave: (config: WebConfig) => void;
}

export function KeywordsTab({ config, onChange, onSave }: KeywordsTabProps) {
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");
  const groups = config.keywords.groups ?? [];

  const updateGroups = (nextGroups: typeof groups) => {
    onChange({ ...config, keywords: { ...config.keywords, groups: nextGroups } });
  };

  const toggleRawMode = () => {
    if (rawMode) {
      onChange({
        ...config,
        keywords: { ...config.keywords, ...textToKeywords(rawText) },
      });
      setRawMode(false);
    } else {
      setRawText(keywordsToText(config.keywords));
      setRawMode(true);
    }
  };

  const save = () => {
    const nextConfig = rawMode
      ? { ...config, keywords: { ...config.keywords, ...textToKeywords(rawText) } }
      : config;
    if (rawMode) setRawMode(false);
    onSave(nextConfig);
  };

  return (
    <section className="tab-panel active">
      <div className="panel-head">
        <div>
          <h2>关注关键词</h2>
          <p className="hint">每个词组内的多行是「或」的关系，任一行命中即算关注；标题需避开「全局排除词」。</p>
        </div>
        <div className="panel-actions">
          <button
            className="btn"
            type="button"
            onClick={() => updateGroups([...groups, { display_name: "", lines: [""] }])}
          >
            ＋ 添加词组
          </button>
          <button className="btn btn-primary" type="button" onClick={save}>保存词表</button>
        </div>
      </div>

      <div className="groups-editor">
        {groups.map((group, index) => (
          <div className="group-card" key={index}>
            <div className="group-card-head">
              <span className="group-index">{index + 1}</span>
              <input
                className="group-name"
                type="text"
                aria-label={`词组 ${index + 1} 显示名`}
                placeholder="词组显示名"
                value={group.display_name}
                onChange={(event) => updateGroups(groups.map((item, i) =>
                  i === index ? { ...item, display_name: event.target.value } : item))}
              />
              <button
                className="group-del"
                type="button"
                title="删除该词组"
                aria-label={`删除词组 ${index + 1}`}
                onClick={() => updateGroups(groups.filter((_, i) => i !== index))}
              >
                🗑
              </button>
            </div>
            <textarea
              className="textarea mono"
              rows={3}
              aria-label={`词组 ${index + 1} 关键词`}
              placeholder={"每行一个关键词，例如：\n/大熊猫|熊猫|旅韩大熊猫/ => 大熊猫"}
              value={(group.lines ?? []).join("\n")}
              onChange={(event) => updateGroups(groups.map((item, i) =>
                i === index ? { ...item, lines: event.target.value.split("\n") } : item))}
            />
          </div>
        ))}
      </div>

      <div className="card">
        <h3>全局排除词 <span className="hint-inline">每行一个，命中任一词的新闻不会出现</span></h3>
        <textarea
          className="textarea mono"
          rows={2}
          placeholder="例如：震惊"
          value={(config.keywords.global_filters ?? []).join("\n")}
          onChange={(event) => onChange({
            ...config,
            keywords: {
              ...config.keywords,
              global_filters: event.target.value.split("\n").filter((line) => line.trim()),
            },
          })}
        />
      </div>

      <details className="card">
        <summary>高级语法说明 &amp; 原始文本模式</summary>
        <div className="syntax-help">
          <table>
            <tbody>
              <tr><td><code>熊猫</code></td><td>普通词，标题包含即命中</td></tr>
              <tr><td><code>/词A|词B|词C/</code></td><td>正则匹配多个词</td></tr>
              <tr><td><code>/词A|词B/ =&gt; 显示名</code></td><td>自定义词组在报告里的名字</td></tr>
              <tr><td><code>+必须词</code></td><td>该行必须同时包含（如 <code>+熊猫</code>）</td></tr>
              <tr><td><code>!排除词</code></td><td>组内排除（如 <code>!猫</code>）</td></tr>
              <tr><td><code>@5</code></td><td>该词组在报告中最多显示 5 条</td></tr>
            </tbody>
          </table>
        </div>
        <div className="panel-actions">
          <button className="btn btn-ghost" type="button" onClick={toggleRawMode}>
            {rawMode ? "切换回可视化编辑" : "切换到原始文本编辑"}
          </button>
        </div>
        {rawMode && (
          <textarea
            className="textarea mono raw-editor"
            rows={16}
            aria-label="原始词表文本"
            value={rawText}
            onChange={(event) => setRawText(event.target.value)}
          />
        )}
      </details>
    </section>
  );
}
