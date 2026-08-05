import React, { useEffect, useMemo, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { createRoot } from "react-dom/client";
import {
  App as AntApp,
  Button,
  ConfigProvider,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Popover,
  Select,
  Slider,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message,
} from "antd";
import "./styles.css";

const MISSION = window.__MISSION__?.taskCode ? window.__MISSION__ : null;
const $json = (value) => JSON.stringify(value, null, 2);
const esc = (value) => String(value ?? "");

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options });
  } catch (error) {
    return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
  }
  let body;
  try {
    body = await response.json();
  } catch {
    body = { error: `接口返回异常(${response.status})` };
  }
  if (!response.ok && !body.error) body.error = body.msg || `请求失败(${response.status})`;
  if (response.status === 401) body.error = body.error || "未获取到外部本体平台登录态，请从本体平台进入";
  return body;
}

function missionQuery(extra = {}) {
  if (!MISSION) return "";
  const query = new URLSearchParams({ repositoryId: MISSION.repositoryId, taskCode: MISSION.taskCode, ...extra });
  return `&${query.toString()}`;
}

function relativeTime(timestamp) {
  const seconds = Math.max(0, Date.now() / 1000 - Number(timestamp || 0));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function truncateTitle(value, max = 15) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function isExpiredApprovalError(error) {
  const text = String(error || "");
  return /没有待确认.*(?:请求|操作)|请求已过期/.test(text);
}

function normalizeFiles(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => (typeof item === "string" ? item : item?.path || item?.filename)).filter(Boolean);
}

function normalizeEvents(task) {
  const source = Array.isArray(task?.log) ? task.log : Array.isArray(task?.events) ? task.events : [];
  return source.map((event) => {
    if (!event || typeof event !== "object") return { type: "text", text: String(event ?? "") };
    const content = event.text ?? event.content;
    return { ...event, text: typeof content === "string" ? content : content == null ? "" : $json(content) };
  });
}

function eventTitle(event) {
  const names = { Read: "读取文件", Write: "写入文件", Edit: "修改文件", Bash: "执行命令", Glob: "查找文件", Grep: "搜索内容", Agent: "调用子智能体", TaskCreate: "创建任务" };
  if (event.type === "thinking") return "思考中";
  if (event.type === "model_switch") return "模型切换";
  if (event.type === "tool_result") return "工具结果";
  return names[event.name] || event.name || event.type || "执行步骤";
}

function eventStatus(event) {
  if (event.type === "error" || event.is_error) return "error";
  if (event.type === "approval_request") return "warning";
  if (event.type === "done" || event.type === "approval_result") return "success";
  return "process";
}

function eventDescription(event) {
  if (event.type === "thinking" || event.type === "text" || event.type === "assistant") return event.text || "";
  if (event.type === "tool_result") return String(event.content || "").slice(0, 1200);
  if (event.type === "error") return event.error || "执行失败";
  if (event.type === "approval_request") return `${event.summary || "需要确认"}${event.detail ? `：${event.detail}` : ""}`;
  if (event.type === "approval_result") return event.approved ? "已允许执行" : "已拒绝执行";
  if (event.type === "model_switch") return `${event.from || "当前模型"} → ${event.to || "备用模型"}（${event.reason || "自动切换"}）`;
  if (event.input) return typeof event.input === "string" ? event.input : $json(event.input);
  return event.text || "";
}

function EventFileText({ text, files, onFile }) {
  const source = String(text || "");
  const paths = (files || []).map((file) => file.path).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!paths.length || !onFile) return <>{source}</>;
  const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`(${paths.map(escapeRegExp).join("|")})`, "g");
  return <>{source.split(pattern).map((part, index) => paths.includes(part)
    ? <button type="button" className="event-file-link" key={`${part}-${index}`} onClick={() => onFile(part)}>{part}</button>
    : <React.Fragment key={index}>{part}</React.Fragment>)}</>;
}

function compactEventSummary(value) {
  const source = String(value || "");
  const trimmed = source.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      const first = Array.isArray(parsed) ? parsed[0] : Object.entries(parsed)[0];
      if (Array.isArray(first)) return `${first[0]}: ${typeof first[1] === "string" ? first[1] : JSON.stringify(first[1])}`;
      if (first !== undefined) return typeof first === "string" ? first : JSON.stringify(first);
    } catch { /* 多行非标准 JSON，继续按首行处理 */ }
  }
  const firstLine = trimmed.split(/\r?\n/).map((line) => line.trim()).find((line) => line && !/^[{}[\],]+$/.test(line)) || "";
  return firstLine.replace(/^[{"'`\s]+|[}"'`,\s]+$/g, "").replace(/^([^:]+):\s*["']?(.*?)["']?$/, "$1: $2");
}

function ThoughtEvent({ event, onApprove, files, onFile, loading = false, approvalResult = null }) {
  const [expanded, setExpanded] = useState(false);
  const kind = event.type === "thinking" ? "thinking" : event.type === "model_switch" ? "model-switch" : event.type === "tool_result" ? "tool-result" : event.name === "TaskCreate" ? "task-create" : event.type === "approval_request" ? "approval" : "tool-use";
  const icon = event.type === "thinking" && loading ? <Spin size="small" /> : event.type === "thinking" ? "·" : event.type === "model_switch" ? "↻" : event.type === "tool_result" ? "✓" : event.name === "TaskCreate" ? "＋" : event.type === "approval_request" ? "!" : "·";
  const detail = eventDescription(event);
  const approved = event.type === "approval_request" && approvalResult?.approved === true;
  const toggleExpanded = () => setExpanded((value) => !value);
  return (
    <div className={`chain-event chain-event-${kind}`}>
      <div className="thought-collapsed-row">
        <div className="thought-header">
          <span className={`thought-icon thought-icon-${kind}`}>{icon}</span>
          <button type="button" className="thought-toggle" onClick={(clickEvent) => { clickEvent.stopPropagation(); toggleExpanded(); }}>{eventTitle(event)}</button>
        </div>
        {!expanded && detail && <div className="thought-summary"><EventFileText text={compactEventSummary(detail)} files={files} onFile={onFile} /></div>}
      </div>
      {expanded && <div className="thought-detail"><EventFileText text={detail} files={files} onFile={onFile} /></div>}
      {event.type === "approval_request" && (
        <div className="approval-actions">
          {approved ? <Button type="primary" size="small" disabled>✓ 已允许执行</Button> : <>
            <Button type="primary" size="small" onClick={() => onApprove(event.id, true)}>允许执行</Button>
            <Button size="small" onClick={() => onApprove(event.id, false)}>拒绝</Button>
          </>}
        </div>
      )}
    </div>
  );
}

function inlineMarkdown(value) {
  const text = String(value || "");
  const token = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g;
  return text.split(token).map((part, index) => {
    if (/^\*\*.*\*\*$|^__.*__$/.test(part)) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (/^\*.*\*$|^_.*_$/.test(part)) return <em key={index}>{part.slice(1, -1)}</em>;
    if (/^`.*`$/.test(part)) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^\)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <React.Fragment key={index}>{part.split("\n").map((line, lineIndex) => <React.Fragment key={lineIndex}>{lineIndex ? <br /> : null}{line}</React.Fragment>)}</React.Fragment>;
  });
}

function markdownTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function AssistantText({ text }) {
  const lines = String(text || "").split("\n");
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) { index += 1; continue; }
    if (/^```/.test(trimmed)) {
      const code = []; index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre className="markdown-code" key={`code-${index}`}><code>{code.join("\n")}</code></pre>); continue;
    }
    if (/^\|/.test(trimmed) && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const head = markdownTableRow(line); index += 2; const rows = [];
      while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(markdownTableRow(lines[index++]));
      blocks.push(<table className="markdown-table" key={`table-${index}`}><thead><tr>{head.map((cell, cellIndex) => <th key={cellIndex}>{inlineMarkdown(cell)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, cellIndex) => <td key={cellIndex}>{inlineMarkdown(row[cellIndex] || "")}</td>)}</tr>)}</tbody></table>); continue;
    }
    if (/^#{1,3}\s/.test(trimmed)) { blocks.push(<h3 key={`heading-${index}`}>{inlineMarkdown(trimmed.replace(/^#{1,3}\s*/, ""))}</h3>); index += 1; continue; }
    if (/^[-*]\s/.test(trimmed)) { const items = []; while (index < lines.length && /^\s*[-*]\s/.test(lines[index])) items.push(lines[index++].replace(/^\s*[-*]\s+/, "")); blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item)}</li>)}</ul>); continue; }
    const paragraph = [line]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^```|^#{1,3}\s|^\s*[-*]\s|^\s*\|/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(paragraph.join("\n"))}</p>);
  }
  return <div className="assistant-text">{blocks}</div>;
}

function EventFeed({ events, onApprove, files, onFile, busy = false }) {
  const lastEvent = events[events.length - 1];
  const waitingForNextEvent = busy && !["done", "error", "approval_request"].includes(lastEvent?.type);
  const approvalResults = events.reduce((result, event) => {
    if (event.type === "approval_result" && event.id) result[event.id] = event;
    return result;
  }, {});
  return (
    <div className="feed-list">
      {events.map((event, index) => {
        if (event.type === "user") return <div className="user-message" key={`${index}-user`}>{event.text}</div>;
        if (["text", "assistant"].includes(event.type)) return <div className="assistant-message" key={`${index}-assistant`}><AssistantText text={event.text} /></div>;
        if (event.type === "done") return <div className="done-note" key={`${index}-done`}>本轮执行结束 · {event.status || "完成"}</div>;
        const loading = busy && index === events.length - 1 && event.type === "thinking";
        return <ThoughtEvent event={event} approvalResult={event.type === "approval_request" ? approvalResults[event.id] : null} onApprove={onApprove} files={files} onFile={onFile} loading={loading} key={`${index}-${event.id || event.type}`} />;
      })}
      {waitingForNextEvent && lastEvent?.type !== "thinking" && (
        <ThoughtEvent event={{ type: "thinking", text: "" }} files={files} onFile={onFile} loading />
      )}
    </div>
  );
}

function parseCsv(text) {
  const source = String(text || "").replace(/^\uFEFF/, "");
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(cell); cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); if (row.some((value) => value !== "")) rows.push(row); }
  return rows;
}

function CsvPreview({ text }) {
  const rows = parseCsv(text);
  const headers = rows[0] || [];
  const body = rows.slice(1);
  return <div className="csv-preview"><div className="csv-preview-meta">CSV 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th key={index}>{header || `列 ${index + 1}`}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] || ""}</td>)}</tr>)}</tbody></table></div></div>;
}

function SpreadsheetPreview({ sheets }) {
  const [active, setActive] = useState(0);
  const current = sheets[active] || { name: "Sheet1", rows: [] };
  const headers = current.rows[0] || [];
  const body = current.rows.slice(1);
  return <div className="csv-preview"><div className="sheet-tabs">{sheets.map((sheet, index) => <button type="button" className={index === active ? "sheet-tab active" : "sheet-tab"} key={sheet.name} onClick={() => setActive(index)}>{sheet.name}</button>)}</div><div className="csv-preview-meta">Excel 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th key={index}>{String(header || `列 ${index + 1}`)}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, columnIndex) => <td key={columnIndex}>{String(row[columnIndex] ?? "")}</td>)}</tr>)}</tbody></table></div></div>;
}

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0B";
  if (bytes < 1000) return `${bytes}B`;
  const units = ["K", "M", "G"]; let size = bytes; let index = -1;
  while (size >= 1000 && index < units.length - 1) { size /= 1000; index += 1; }
  return `${size.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1")}${units[index]}`;
}

const MISSION_LABELS = {
  repositoryId: "本体库 ID", taskCode: "任务编码", taskName: "任务名称", modelName: "模型名称",
  taskType: "任务类型", prompt: "提示词", parseElements: "解析要素", expectedFiles: "期望输出文件",
  outputPrefix: "输出路径前缀", sourceMode: "来源模式", checkTypes: "校验类型", dbType: "数据库类型",
  host: "主机", port: "端口", database: "数据库", username: "用户名", password: "密码",
  sourceSchema: "Schema", selectedTables: "选中数据表", databaseSourceId: "数据源 ID",
  fileSourceId: "文件源 ID", fileType: "文件类型", objectKey: "对象存储 Key", items: "条目",
  mode: "模式", generateAlignmentReport: "生成对齐报告", generate_alignment_report: "生成对齐报告",
  autoMergeStrategy: "自动合并策略", auto_merge_strategy: "自动合并策略", alignmentStrategy: "对齐策略",
  mergeStrategy: "整合策略", conflictResolutionStrategy: "冲突处理策略", pendingConfirmationStrategy: "待确认策略",
  modelingPlan: "分层建模计划", identity: "任务身份", artifacts: "Artifact 清单",
  artifactType: "Artifact 类型", layer: "层级", requested: "是否请求", source: "来源",
  status: "状态", dependsOn: "依赖", outputs: "输出文件", key: "身份键",
  modelVersion: "模型版本", inputFingerprint: "输入指纹", requestedElements: "请求解析要素",
  executionOrder: "执行顺序", valid: "依赖校验通过", dependencyErrors: "依赖错误",
};
const MISSION_SECTION_LABELS = {
  database: "数据源", document: "文档", sourceModels: "来源模型", integrationStrategy: "整合策略",
  validationRules: "校验规则",
};
const missionLabel = (key) => MISSION_LABELS[key] || MISSION_SECTION_LABELS[key] || key;

function RecursiveInfo({ value, level = 0, field = "" }) {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return <div className="info-tags">{value.map((item, index) => <Tag key={index}>{typeof item === "object" ? $json(item) : String(item)}</Tag>)}</div>;
  if (typeof value === "object") return <div className="info-nested">{Object.entries(value).map(([key, item]) => <div className="info-row" key={`${level}-${key}`}><span className="info-key">{missionLabel(key)}</span><div className="info-value"><RecursiveInfo value={item} level={level + 1} field={key} /></div></div>)}</div>;
  return <span>{field === "password" ? "••••••••" : String(value)}</span>;
}

function MissionInfo({ open, context, loading, onClose }) {
  return (
    <Modal open={open} title="当前任务信息" footer={null} onCancel={onClose} width={680} destroyOnClose>
      {loading ? <Spin /> : context ? <div className="mission-info"><RecursiveInfo value={context} /></div> : <Empty description="暂未获取到任务信息" />}
    </Modal>
  );
}

function SettingsModal({ open, onClose, meta, model, onModel, params, onParams, provider, keyValue, setKeyValue, onSaveKey }) {
  const models = (meta?.models || []).map((item) => ({ value: item.id, label: `${item.label || item.id} · ${item.provider || ""}` }));
  return (
    <Modal open={open} title="大语言模型设置" footer={null} onCancel={onClose} width={560}>
      <div className="settings-section"><div className="settings-label">模型</div><Select showSearch value={model} options={models} onChange={onModel} /></div>
      <Divider />
      <div className="settings-section"><div className="settings-label">模型参数</div>
        <div className="settings-grid">
          <label>最大输出 token<InputNumber min={1} value={params.max_tokens} onChange={(value) => onParams({ max_tokens: value })} /></label>
          <label>温度<Slider min={0} max={2} step={0.1} value={params.temperature ?? 0} onChange={(value) => onParams({ temperature: value })} /></label>
          <label>扩展思考<Switch checked={Boolean(params.thinking)} onChange={(value) => onParams({ thinking: value })} /></label>
          <label>思考预算 token<InputNumber min={1024} step={512} value={params.thinking_budget} onChange={(value) => onParams({ thinking_budget: value })} /></label>
        </div>
      </div>
      <Divider />
      <div className="settings-section"><div className="settings-label">当前用户模型密钥 · {provider || "—"}</div>
        <Input.Password value={keyValue} onChange={(event) => setKeyValue(event.target.value)} placeholder="粘贴该模型对应的 API Key" addonAfter={<Button type="link" onClick={onSaveKey}>保存</Button>} />
      </div>
    </Modal>
  );
}

function ModelPicker({ model, models, onModel, onOpenSettings }) {
  const [open, setOpen] = useState(false);
  const content = <div className="model-picker">
    <div className="model-picker-list">{(models || []).map((item) => <button type="button" className={item.id === model ? "model-option active" : "model-option"} key={item.id} onClick={() => { onModel(item.id); setOpen(false); }}><span>{item.label || item.id}</span><small>{item.provider || ""}</small></button>)}</div>
    <Button type="link" className="model-params-link" onClick={() => { setOpen(false); onOpenSettings(); }}>⚙ 修改模型参数</Button>
  </div>;
  const modelText = String(model || "模型");
  return <Popover open={open} onOpenChange={setOpen} trigger="click" placement="topRight" content={content} title="选择大语言模型"><button type="button" className="model-hint" aria-label={`当前模型：${model || "未选择"}`} title={model || "未选择模型"}><span className="model-name">⚙ {modelText.length > 10 ? `${modelText.slice(0, 10)}...` : modelText}</span><span className="model-arrow">⌄</span></button></Popover>;
}

function Composer({ value, onChange, onSend, onAttach, pendingFiles, mission, busy, hasConversation, model, models, onModel, onOpenSettings, placeholder, projects, project, onProject }) {
  const start = mission && !hasConversation && !value.trim();
  return (
    <div className="composer">
      <Input.TextArea value={value} onChange={(event) => onChange(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); onSend(); } }} autoSize={{ minRows: 1, maxRows: 8 }} placeholder={placeholder} disabled={busy} />
      {!!pendingFiles.length && <div className="pending-files">{pendingFiles.map((file) => <Tag key={file.name}>📎 {file.name}</Tag>)}</div>}
      <div className="composer-row">
        <Button type="text" onClick={onAttach} title="上传文件到项目">📎 <span>上传文件</span></Button>
        {!mission && projects?.length > 0 && <Select size="small" value={project} options={projects.map((item) => ({ value: item.name, label: item.name }))} onChange={onProject} className="project-select" placeholder="选择项目" />}
        <ModelPicker model={model} models={models} onModel={onModel} onOpenSettings={onOpenSettings} />
        <Button type={start ? "primary" : "default"} className={start ? "start-button" : "send-button"} onClick={onSend} disabled={busy}>{start ? (mission?.taskType === "integration" ? "开始智能消歧与整合" : "开始智能建模") : "↑"}</Button>
      </div>
    </div>
  );
}

function FilePanel({ open, files, loading, selected, onSelect, onSelectGroup, onOpen, onDownload, onUploadToMinio, uploadingToMinio, onClose, onRefresh, mission, focusPath }) {
  const [collapsedDirs, setCollapsedDirs] = useState(() => new Set([""]));
  const groups = useMemo(() => {
    const map = new Map();
    files.forEach((file) => { const dir = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : ""; if (!map.has(dir)) map.set(dir, []); map.get(dir).push(file); });
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [files]);
  const toggleDir = (dir) => setCollapsedDirs((current) => {
    const next = new Set(current);
    if (next.has(dir)) next.delete(dir); else next.add(dir);
    return next;
  });
  const groupLabel = (dir) => dir === "mission-input" ? "📥 mission-input/"
    : dir === "mission-output" ? "📤 mission-output/"
    : dir === "project-shared" ? "📚 项目公共文件/" : `📁 ${dir || "项目根目录"}`;
  useEffect(() => {
    if (!focusPath) return;
    const dir = focusPath.includes("/") ? focusPath.slice(0, focusPath.lastIndexOf("/")) : "";
    setCollapsedDirs((current) => { const next = new Set(current); next.delete(dir); return next; });
  }, [focusPath]);
  if (!open) return null;
  return <aside className="file-panel">
    <div className="panel-head"><strong>项目文件</strong><Button size="small" onClick={onRefresh}>⟳</Button><Button size="small" onClick={onClose}>✕</Button></div>
    <div className="file-actions"><Button size="small" disabled={!selected.length} onClick={onDownload}>⬇ 下载所选</Button>{mission && <Tooltip title="上传选中的任务结果"><Button size="small" type="primary" loading={uploadingToMinio} disabled={!selected.length || uploadingToMinio} onClick={onUploadToMinio}>☁ 上传到 MinIO</Button></Tooltip>}{mission && <span className="panel-note">当前任务范围</span>}</div>
    {loading ? <Spin /> : !files.length ? <Empty description="暂无文件" /> : <div className="file-list">{groups.map(([dir, items]) => {
      const collapsed = collapsedDirs.has(dir);
      const paths = items.map((file) => file.path);
      const allSelected = paths.length > 0 && paths.every((path) => selected.includes(path));
      const partiallySelected = !allSelected && paths.some((path) => selected.includes(path));
      return <div className="file-group" key={dir || "root"}>
        <div className="file-group-title">
          <input className="folder-select" type="checkbox" checked={allSelected} ref={(node) => { if (node) node.indeterminate = partiallySelected; }} onChange={() => onSelectGroup(paths)} aria-label={`选择 ${dir || "项目根目录"} 下全部文件`} />
          <button type="button" className="file-group-toggle" onClick={() => toggleDir(dir)} aria-expanded={!collapsed}>{collapsed ? "›" : "⌄"} {groupLabel(dir)}</button>
          <span>({items.length})</span>
        </div>
        {!collapsed && items.map((file) => <div className={`file-row ${focusPath === file.path ? "file-row-focused" : ""}`} key={file.path}><input type="checkbox" checked={selected.includes(file.path)} onChange={() => onSelect(file.path)} /><button onClick={() => onOpen(file.path)}>{file.path.split("/").pop()}</button><small>{formatFileSize(file.size)}</small></div>)}
      </div>;
    })}</div>}
  </aside>;
}

function App() {
  const [meta, setMeta] = useState({ models: [], projects: [], params: {} });
  const [tasks, setTasks] = useState([]);
  const [active, setActive] = useState(null);
  const [events, setEvents] = useState([]);
  const [view, setView] = useState(MISSION ? "home" : "home");
  const [text, setText] = useState("");
  const [pendingFiles, setPendingFiles] = useState([]);
  const [files, setFiles] = useState([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesLoading, setFilesLoading] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [focusFile, setFocusFile] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [minioUploading, setMinioUploading] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [missionInfoOpen, setMissionInfoOpen] = useState(false);
  const [missionContext, setMissionContext] = useState(null);
  const [missionLoading, setMissionLoading] = useState(Boolean(MISSION));
  const [keyValue, setKeyValue] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("oc_auto_approve") === "1");
  const autoApproveRef = useRef(autoApprove);
  const approvalInFlightRef = useRef(new Set());
  const [messageApi, contextHolder] = message.useMessage();
  const fileInput = useRef(null);

  const model = meta.model || "";
  const params = meta.params || { temperature: null, max_tokens: null, thinking: false, thinking_budget: 8000 };
  const provider = meta.provider || "";
  const hasConversation = Boolean(active?.hasConversation || events.some((event) => ["user", "assistant"].includes(event.type) && String(event.text || "").trim()));
  const placeholder = view === "task" ? "继续对这个任务下指令…" : MISSION ? "点击开始任务，或者描述一个任务" : "描述一个任务，例如：帮我分析这个项目…";

  const loadMeta = async () => { const result = await api("/api/meta"); if (!result.error) setMeta(result); else messageApi.error(result.error); };
  const loadTasks = async () => { const result = await api(`/api/tasks${MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}` : ""}`); if (!result.error) setTasks(result.tasks || []); };
  const loadMission = async () => {
    if (!MISSION) return;
    setMissionLoading(true);
    const query = new URLSearchParams({ repositoryId: MISSION.repositoryId, taskCode: MISSION.taskCode, ...(MISSION.taskType ? { taskType: MISSION.taskType } : {}) });
    const result = await api(`/api/mission/task?${query}`);
    // 任务信息只是侧栏的辅助内容；上游任务已完成、删除或暂不可查时，
    // 保持空态即可，不能在打开历史对话时弹出错误打断用户。
    if (!result.error) {
      setMissionContext(result.task);
    } else {
      setMissionContext(null);
    }
    setMissionLoading(false);
  };

  useEffect(() => { loadMeta(); loadTasks(); loadMission(); }, []);
  useEffect(() => { if (!selectedProject && meta.projects?.length) setSelectedProject(meta.projects[0].name); }, [meta.projects, selectedProject]);
  useEffect(() => {
    if (!MISSION || !tasks.length || active) return;
    const saved = localStorage.getItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`);
    const task = tasks.find((item) => item.id === saved) || tasks[0];
    if (task) openTask(task);
  }, [tasks, active]);
  useEffect(() => { if (active && filesOpen) loadFiles(); }, [active, filesOpen]);

  const openTask = async (task) => {
    const detailQuery = MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}` : "";
    const result = await api(`/api/tasks/${task.id}${detailQuery}`);
    if (result.error) { messageApi.error(`打开历史任务失败：${result.error}`); return; }
    const current = result;
    setActive(current); setEvents(normalizeEvents(current)); setView("task"); setText("");
    if (MISSION) localStorage.setItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`, current.id);
    // 页面刷新或重新打开历史任务时，审批请求可能已经在服务端挂起，
    // 不会再次经过 SSE；自动确认开启时要主动恢复这类请求。
    if (autoApproveRef.current) {
      const pending = normalizeEvents(current).find((event) => event.type === "approval_request");
      if (pending) void approve(pending.id, true, current);
    }
    await loadFiles(current);
  };

  const loadFiles = async (task = active) => {
    setFilesLoading(true);
    const project = task?.project || "";
    const query = `/api/files?project=${encodeURIComponent(project)}${MISSION ? missionQuery({ taskId: task?.id || "" }) : ""}`;
    const result = await api(query);
    if (!result.error) setFiles((result.files || []).filter((file) => !String(file.path).includes("-sheets/") && !String(file.path).endsWith("manifest.json")));
    setFilesLoading(false);
  };

  const createTask = async () => {
    const result = await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: MISSION ? "" : selectedProject || meta.projects?.[0]?.name || "", repositoryId: MISSION?.repositoryId || "", taskCode: MISSION?.taskCode || "", taskType: MISSION?.taskType || "" }) });
    if (result.error) { messageApi.error(result.error); return null; }
    setTasks((previous) => [result, ...previous.filter((task) => task.id !== result.id)]); setActive(result); setEvents([]); setView("task"); return result;
  };

  const appendEvent = (event) => setEvents((previous) => {
    if (event.type === "text" || event.type === "thinking") {
      const last = previous[previous.length - 1];
      if (last?.type === event.type) return [...previous.slice(0, -1), { ...last, text: `${last.text || ""}${event.text || ""}` }];
    }
    return [...previous, event];
  });

  const approve = async (id, approved, taskOverride = null) => {
    const task = taskOverride || active;
    if (!task || !id) return false;
    const key = `${task.id}:${id}`;
    if (approvalInFlightRef.current.has(key)) return false;
    approvalInFlightRef.current.add(key);
    try {
      const result = await api(`/api/tasks/${task.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, approved }) });
      if (result.error) {
        // 自动恢复历史审批时，服务端可能已处理同一个请求；这不是用户需要
        // 处理的异常。其他审批失败（鉴权、网络等）仍然保留明确提示。
        if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);
        return false;
      }
      appendEvent({ type: "approval_result", id, approved });
      return true;
    } finally {
      approvalInFlightRef.current.delete(key);
    }
  };

  const uploadFiles = async (task, selected) => {
    const names = [];
    for (const file of selected) {
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = reject; reader.readAsDataURL(file); });
      const result = await api("/api/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: task.project, name: file.name, data, ...(MISSION ? { repositoryId: MISSION.repositoryId, taskCode: MISSION.taskCode, taskId: task.id } : {}) }) });
      if (result.error) messageApi.error(`${file.name}: ${result.error}`); else names.push(file.name);
    }
    setPendingFiles([]); return names;
  };

  const sendToTask = async (task, content, displayMessage = content) => {
    setBusy(true); appendEvent({ type: "user", text: displayMessage });
    let response;
    try {
      response = await fetch(`/api/tasks/${task.id}/send`, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ message: content, displayMessage, missionContext: MISSION ? missionContext : null }) });
    } catch (error) { appendEvent({ type: "error", error: error.message }); setBusy(false); return; }
    if (!response.ok || !response.body) { appendEvent({ type: "error", error: `请求失败(${response.status})` }); setBusy(false); return; }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    const consume = (chunk) => {
      buffer += decoder.decode(chunk, { stream: true });
      const packets = buffer.split("\n\n"); buffer = packets.pop() || "";
      packets.forEach((packet) => {
        const line = packet.split("\n").find((item) => item.startsWith("data: "));
        if (!line) return;
        try {
          const event = JSON.parse(line.slice(6));
          appendEvent(event);
          if (event.type === "approval_request" && autoApproveRef.current) approve(event.id, true, task);
          if (event.type === "done") setBusy(false);
        } catch { /* ignore malformed SSE packet */ }
      });
    };
    try { while (true) { const { value, done } = await reader.read(); if (done) break; consume(value); } if (buffer) consume(new Uint8Array()); } catch (error) { appendEvent({ type: "error", error: error.message }); }
    setBusy(false); await loadTasks(); await loadFiles(task);
  };

  const send = async () => {
    if (busy) return;
    let task = active;
    const start = MISSION && !hasConversation && !text.trim();
    const userText = text.trim();
    if (!userText && !start) return;
    if (!task) task = await createTask();
    if (!task) return;
    const names = pendingFiles.length ? await uploadFiles(task, pendingFiles) : [];
    const messageText = start ? "请直接开始执行当前任务\n不需要等待我补充提示词。严格按照当前 execution-context 和系统规则完成全部工作。" : `${userText}${names.length ? `\n\n[用户上传了文件: ${names.join(", ")}]` : ""}`;
    const display = start ? "请直接开始执行当前任务" : userText;
    setText(""); await sendToTask(task, messageText, display);
  };

  const onAttach = () => fileInput.current?.click();
  const onFilesSelected = (event) => { setPendingFiles(Array.from(event.target.files || [])); event.target.value = ""; };
  const onParams = async (patch) => { const result = await api("/api/params", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, params: result })); };
  const onModel = async (value) => { const result = await api("/api/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: value }) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, model: result.model, provider: (previous.models || []).find((item) => item.id === result.model)?.provider || previous.provider })); };
  const onSaveKey = async () => { const result = await api("/api/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, key: keyValue }) }); if (result.error) messageApi.error(result.error); else messageApi.success("模型密钥已保存"); };

  const fileUrl = (path) => { const project = active?.project || ""; return `/p/${encodeURIComponent(project)}/${path.split("/").map(encodeURIComponent).join("/")}${MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}&taskId=${encodeURIComponent(active?.id || "")}` : ""}`; };
  const openFile = async (path) => { setFilesOpen(true); setFocusFile(path); try { const response = await fetch(fileUrl(path), { credentials: "same-origin" }); if (!response.ok) throw new Error(`HTTP ${response.status}`); const type = response.headers.get("content-type") || ""; if (type.startsWith("image/")) setPreview({ path, image: URL.createObjectURL(await response.blob()) }); else if (/\.(xlsx?|xlsm)$/i.test(path)) { const workbook = XLSX.read(await response.arrayBuffer(), { type: "array", cellDates: true }); const sheets = workbook.SheetNames.map((name) => ({ name, rows: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1, defval: "", raw: false }) })); setPreview({ path, xlsx: true, sheets }); } else { const text = await response.text(); setPreview({ path, text, csv: /\.csv$/i.test(path) || type.includes("text/csv") }); } } catch (error) { messageApi.error(`打开文件失败: ${error.message}`); } };
  const download = () => { if (!selectedFiles.length) return; const project = active?.project || ""; const query = new URLSearchParams({ project }); selectedFiles.forEach((path) => query.append("path", path)); if (MISSION) { query.set("repositoryId", MISSION.repositoryId); query.set("taskCode", MISSION.taskCode); query.set("taskId", active?.id || ""); } window.open(`/api/download?${query}`, "_blank"); };
  const uploadToMinio = async () => {
    if (!MISSION || !active || !selectedFiles.length) return;
    const prefix = String(missionContext?.outputPrefix || "").trim();
    if (!prefix) { messageApi.error("尚未获取当前任务的输出路径，无法上传到 MinIO"); return; }
    setMinioUploading(true);
    try {
      const result = await api("/api/minio/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: active.project, paths: selectedFiles, prefix, taskCode: MISSION.taskCode, repositoryId: MISSION.repositoryId, taskId: active.id, taskType: MISSION.taskType || active.taskType || "" }) });
      if (result.error) { messageApi.error(result.error); return; }
      const failed = (result.results || []).filter((item) => !item.ok);
      if (result.uploaded) messageApi.success(`已上传 ${result.uploaded}/${result.total || selectedFiles.length} 个文件到 MinIO`);
      if (failed.length) messageApi.warning(failed.map((item) => `${item.name}: ${item.error}`).join("；"));
      if (result.task) {
        setActive(result.task);
        setTasks((previous) => previous.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
      }
      if (result.callback?.ok) messageApi.success("结果文件已校验并自动回写完成");
      else if (result.callback?.skipped) messageApi.info(`尚未自动完成：${result.callback.error}`);
      else if (result.callback) messageApi.warning(`结果已上传，但完成回写失败：${result.callback.error || "未知错误"}`);
      await loadFiles(active);
    } finally {
      setMinioUploading(false);
    }
  };

  const sidebarTasks = tasks.filter((task) => !MISSION || (task.repositoryId === MISSION.repositoryId && task.taskCode === MISSION.taskCode));
  return <ConfigProvider theme={{ token: { colorPrimary: "#5f7f9d", borderRadius: 8, fontFamily: '"PingFang SC", -apple-system, sans-serif' } }}>
    {contextHolder}
    <div className="workbench">
      <aside className="sidebar">
        <div className="brand"><span className="brand-logo">硕</span><strong>硕磐智能</strong><Tag>Agent</Tag></div>
        <div className="sidebar-scroll">
          <Button className="new-task" onClick={async () => { setActive(null); setEvents([]); setText(""); setView("home"); if (MISSION) await createTask(); }}>✚ 新任务</Button>
          <button className="section-toggle" onClick={() => setHistoryOpen((value) => !value)}>历史任务</button>
          {historyOpen && <div className="task-list">{sidebarTasks.length ? sidebarTasks.map((task) => <button className={`task-row ${active?.id === task.id ? "active" : ""}`} key={task.id} onClick={() => openTask(task)}><span>{task.title || "新任务"}</span><small><i className={task.status === "working" ? "working" : task.status === "error" ? "error" : ""} />{task.workspace || task.project} · {relativeTime(task.updated)}</small></button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有任务" />}</div>}
          <Button className="settings-button" onClick={() => setSettingsOpen(true)}>⚙ 大语言模型设置</Button>
          {MISSION && <div className="current-mission">
            <Button type="text" onClick={() => setMissionInfoOpen(true)}>📋 当前任务信息</Button>
            <small>{MISSION.taskCode} · 本体库 {MISSION.repositoryId}</small>
            <div className="sidebar-mission-info">
              {missionLoading ? <Spin size="small" /> : missionContext ? <RecursiveInfo value={missionContext} /> : <span className="sidebar-mission-empty">暂未获取到完整任务信息</span>}
            </div>
          </div>}
        </div>
        <div className="sandbox-note">沙箱模式：智能体只能操作当前任务工作目录。<br /><span>{meta.sandbox || "sandbox/"}</span></div>
      </aside>
      <main className="main-content">
        {view === "home" ? <section className="home-view"><h1>{MISSION ? (MISSION.taskType === "integration" ? "智能消歧与整合" : "智能建模") : "本体智能体"}</h1><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={false} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></section> : <section className="task-view">
          <header className="task-header"><i className={active?.status === "working" || busy ? "status-dot working" : "status-dot"} /><strong title={active?.title || "当前任务"}>{truncateTitle(active?.title || "当前任务")}</strong><Tag>{active?.workspace || active?.project}</Tag><span className="header-spacer" />{MISSION && <Switch checked={autoApprove} onChange={(value) => { autoApproveRef.current = value; setAutoApprove(value); localStorage.setItem("oc_auto_approve", value ? "1" : "0"); if (value) { const pending = events.find((event) => event.type === "approval_request"); if (pending) approve(pending.id, true, active); } }} checkedChildren="自动确认：开" unCheckedChildren="自动确认：关" />}<Button onClick={() => { setFilesOpen(true); loadFiles(); }}>📂 文件</Button></header>
          <div className="feed"><EventFeed events={events} onApprove={approve} files={files} onFile={openFile} busy={busy} /></div>
          <div className="task-composer"><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={hasConversation} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></div>
        </section>}
      </main>
      <FilePanel open={filesOpen} files={files} loading={filesLoading} selected={selectedFiles} focusPath={focusFile} onSelect={(path) => setSelectedFiles((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])} onSelectGroup={(paths) => setSelectedFiles((current) => paths.every((path) => current.includes(path)) ? current.filter((path) => !paths.includes(path)) : [...new Set([...current, ...paths])])} onOpen={openFile} onDownload={download} onUploadToMinio={uploadToMinio} uploadingToMinio={minioUploading} onClose={() => setFilesOpen(false)} onRefresh={() => loadFiles()} mission={MISSION} />
      <input ref={fileInput} type="file" multiple hidden onChange={onFilesSelected} />
      {preview && <Modal open title={preview.path} footer={null} width="88vw" onCancel={() => setPreview(null)}>{preview.image ? <img className="preview-image" src={preview.image} alt={preview.path} /> : preview.xlsx ? <SpreadsheetPreview sheets={preview.sheets} /> : preview.csv ? <CsvPreview text={preview.text} /> : <pre className="preview-text">{preview.text}</pre>}</Modal>}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} meta={meta} model={model} onModel={onModel} params={params} onParams={onParams} provider={provider} keyValue={keyValue} setKeyValue={setKeyValue} onSaveKey={onSaveKey} />
      {MISSION && <MissionInfo open={missionInfoOpen} context={missionContext} loading={missionLoading} onClose={() => setMissionInfoOpen(false)} />}
    </div>
  </ConfigProvider>;
}

createRoot(document.getElementById("root")).render(<AntApp><App /></AntApp>);
