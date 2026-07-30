import React, { useEffect, useMemo, useRef, useState } from "react";
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
  Select,
  Slider,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message,
} from "antd";
import { ThoughtChain } from "@ant-design/x";
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

function normalizeFiles(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => (typeof item === "string" ? item : item?.path || item?.filename)).filter(Boolean);
}

function eventTitle(event) {
  const names = { Read: "读取文件", Write: "写入文件", Edit: "修改文件", Bash: "执行命令", Glob: "查找文件", Grep: "搜索内容", Agent: "调用子智能体" };
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

function ThoughtEvent({ event, onApprove }) {
  const item = {
    key: event.id || `${event.type}-${event.name || "event"}-${event.text || ""}`,
    title: eventTitle(event),
    description: eventDescription(event),
    status: eventStatus(event),
  };
  return (
    <div className="chain-event">
      <ThoughtChain items={[item]} />
      {event.type === "approval_request" && (
        <div className="approval-actions">
          <Button type="primary" size="small" onClick={() => onApprove(event.id, true)}>允许执行</Button>
          <Button size="small" onClick={() => onApprove(event.id, false)}>拒绝</Button>
        </div>
      )}
    </div>
  );
}

function AssistantText({ text }) {
  const lines = String(text || "").split("\n");
  return (
    <div className="assistant-text">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return <div className="text-gap" key={index} />;
        if (/^```/.test(trimmed)) return <div className="code-line" key={index}>{trimmed}</div>;
        if (/^#{1,3}\s/.test(trimmed)) return <h3 key={index}>{trimmed.replace(/^#{1,3}\s*/, "")}</h3>;
        if (/^[-*]\s/.test(trimmed)) return <div className="list-line" key={index}>• {trimmed.slice(2)}</div>;
        return <p key={index}>{line}</p>;
      })}
    </div>
  );
}

function EventFeed({ events, onApprove }) {
  return (
    <div className="feed-list">
      {events.map((event, index) => {
        if (event.type === "user") return <div className="user-message" key={`${index}-user`}>{event.text}</div>;
        if (["text", "assistant"].includes(event.type)) return <div className="assistant-message" key={`${index}-assistant`}><AssistantText text={event.text} /></div>;
        if (event.type === "done") return <div className="done-note" key={`${index}-done`}>本轮执行结束 · {event.status || "完成"}</div>;
        return <ThoughtEvent event={event} onApprove={onApprove} key={`${index}-${event.id || event.type}`} />;
      })}
    </div>
  );
}

function RecursiveInfo({ value, level = 0 }) {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return <div className="info-tags">{value.map((item, index) => <Tag key={index}>{typeof item === "object" ? $json(item) : String(item)}</Tag>)}</div>;
  if (typeof value === "object") return <div className="info-nested">{Object.entries(value).map(([key, item]) => <div className="info-row" key={`${level}-${key}`}><span className="info-key">{key}</span><div className="info-value"><RecursiveInfo value={item} level={level + 1} /></div></div>)}</div>;
  return <span>{String(value)}</span>;
}

function MissionInfo({ context, loading, onClose }) {
  return (
    <Modal open title="当前任务信息" footer={null} onCancel={onClose} width={680}>
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

function Composer({ value, onChange, onSend, onAttach, pendingFiles, mission, busy, hasConversation, model, placeholder, projects, project, onProject }) {
  const start = mission && !hasConversation && !value.trim();
  return (
    <div className="composer">
      <Input.TextArea value={value} onChange={(event) => onChange(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); onSend(); } }} autoSize={{ minRows: 1, maxRows: 8 }} placeholder={placeholder} disabled={busy} />
      {!!pendingFiles.length && <div className="pending-files">{pendingFiles.map((file) => <Tag key={file.name}>📎 {file.name}</Tag>)}</div>}
      <div className="composer-row">
        <Button type="text" onClick={onAttach} title="上传文件到项目">📎 <span>上传文件</span></Button>
        {!mission && projects?.length > 0 && <Select size="small" value={project} options={projects.map((item) => ({ value: item.name, label: item.name }))} onChange={onProject} className="project-select" placeholder="选择项目" />}
        <Tooltip title={`当前模型：${model || "未选择"}`}><span className="model-hint">⚙ {String(model || "模型").slice(0, 9)}…⌄</span></Tooltip>
        <Button type={start ? "primary" : "default"} className={start ? "start-button" : "send-button"} onClick={onSend} disabled={busy}>{start ? (mission?.taskType === "integration" ? "开始智能消歧与整合" : "开始智能建模") : "↑"}</Button>
      </div>
    </div>
  );
}

function FilePanel({ open, files, loading, selected, onSelect, onOpen, onDownload, onClose, onRefresh, mission }) {
  const groups = useMemo(() => {
    const map = new Map();
    files.forEach((file) => { const dir = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : ""; if (!map.has(dir)) map.set(dir, []); map.get(dir).push(file); });
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [files]);
  if (!open) return null;
  return <aside className="file-panel">
    <div className="panel-head"><strong>项目文件</strong><Button size="small" onClick={onRefresh}>⟳</Button><Button size="small" onClick={onClose}>✕</Button></div>
    <div className="file-actions"><Button size="small" disabled={!selected.length} onClick={onDownload}>⬇ 下载所选</Button>{mission && <span className="panel-note">当前任务范围</span>}</div>
    {loading ? <Spin /> : !files.length ? <Empty description="暂无文件" /> : <div className="file-list">{groups.map(([dir, items]) => <div className="file-group" key={dir || "root"}><div className="file-group-title">{dir === "mission-input" ? "📥 mission-input/" : dir === "mission-output" ? "📤 mission-output/" : dir === "project-shared" ? "📚 项目公共文件/" : `📁 ${dir || "项目根目录"}`} <span>({items.length})</span></div>{items.map((file) => <div className="file-row" key={file.path}><input type="checkbox" checked={selected.includes(file.path)} onChange={() => onSelect(file.path)} /><button onClick={() => onOpen(file.path)}>{file.path.split("/").pop()}</button><small>{file.sizeLabel || file.size}</small></div>)}</div>)}</div>}
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
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [missionInfoOpen, setMissionInfoOpen] = useState(false);
  const [missionContext, setMissionContext] = useState(null);
  const [missionLoading, setMissionLoading] = useState(Boolean(MISSION));
  const [keyValue, setKeyValue] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("oc_auto_approve") === "1");
  const [messageApi, contextHolder] = message.useMessage();
  const fileInput = useRef(null);

  const model = meta.model || "";
  const params = meta.params || { temperature: null, max_tokens: null, thinking: false, thinking_budget: 8000 };
  const provider = meta.provider || "";
  const hasConversation = Boolean(active?.hasConversation || events.some((event) => ["user", "assistant"].includes(event.type) && String(event.text || "").trim()));
  const placeholder = view === "task" ? "继续对这个任务下指令…" : mission ? "你可以直接点击开始任务，或者描述一个任务" : "描述一个任务，例如：帮我分析这个项目…";

  const loadMeta = async () => { const result = await api("/api/meta"); if (!result.error) setMeta(result); else messageApi.error(result.error); };
  const loadTasks = async () => { const result = await api(`/api/tasks${MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}` : ""}`); if (!result.error) setTasks(result.tasks || []); };
  const loadMission = async () => {
    if (!MISSION) return;
    setMissionLoading(true);
    const query = new URLSearchParams({ repositoryId: MISSION.repositoryId, taskCode: MISSION.taskCode, ...(MISSION.taskType ? { taskType: MISSION.taskType } : {}) });
    const result = await api(`/api/mission/task?${query}`);
    if (!result.error) setMissionContext(result.task); else messageApi.warning(result.error);
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
    const result = await api(`/api/tasks/${task.id}`);
    const current = result.error ? task : result;
    setActive(current); setEvents(current.log || []); setView("task"); setText("");
    if (MISSION) localStorage.setItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`, current.id);
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
    if (event.type === "text") {
      const last = previous[previous.length - 1];
      if (last?.type === "text") return [...previous.slice(0, -1), { ...last, text: `${last.text || ""}${event.text || ""}` }];
    }
    return [...previous, event];
  });

  const approve = async (id, approved) => { if (!active) return; await api(`/api/tasks/${active.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, approved }) }); appendEvent({ type: "approval_result", approved }); };

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
      packets.forEach((packet) => { const line = packet.split("\n").find((item) => item.startsWith("data: ")); if (!line) return; try { const event = JSON.parse(line.slice(6)); appendEvent(event); if (event.type === "done") setBusy(false); } catch { /* ignore malformed SSE packet */ } });
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
  const openFile = async (path) => { try { const response = await fetch(fileUrl(path), { credentials: "same-origin" }); if (!response.ok) throw new Error(`HTTP ${response.status}`); const type = response.headers.get("content-type") || ""; if (type.startsWith("image/")) setPreview({ path, image: URL.createObjectURL(await response.blob()) }); else setPreview({ path, text: await response.text() }); } catch (error) { messageApi.error(`打开文件失败: ${error.message}`); } };
  const download = () => { if (!selectedFiles.length) return; const project = active?.project || ""; const query = new URLSearchParams({ project }); selectedFiles.forEach((path) => query.append("path", path)); if (MISSION) { query.set("repositoryId", MISSION.repositoryId); query.set("taskCode", MISSION.taskCode); query.set("taskId", active?.id || ""); } window.open(`/api/download?${query}`, "_blank"); };

  const sidebarTasks = tasks.filter((task) => !MISSION || (task.repositoryId === MISSION.repositoryId && task.taskCode === MISSION.taskCode));
  return <ConfigProvider theme={{ token: { colorPrimary: "#5f7f9d", borderRadius: 8, fontFamily: '"PingFang SC", -apple-system, sans-serif' } }}>
    {contextHolder}
    <div className="workbench">
      <aside className="sidebar">
        <div className="brand"><span className="brand-logo">硕</span><strong>硕磐智能</strong><Tag>Agent</Tag></div>
        <Button className="new-task" onClick={async () => { setActive(null); setEvents([]); setText(""); setView("home"); if (MISSION) await createTask(); }}>✚ 新任务</Button>
        <button className="section-toggle" onClick={() => setHistoryOpen((value) => !value)}>历史任务 <span>{historyOpen ? "⌃" : "⌄"}</span></button>
        {historyOpen && <div className="task-list">{sidebarTasks.length ? sidebarTasks.map((task) => <button className={`task-row ${active?.id === task.id ? "active" : ""}`} key={task.id} onClick={() => openTask(task)}><span>{task.title || "新任务"}</span><small><i className={task.status === "working" ? "working" : task.status === "error" ? "error" : ""} />{task.workspace || task.project} · {relativeTime(task.updated)}</small></button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有任务" />}</div>}
        {MISSION && <div className="current-mission"><Button type="text" onClick={() => setMissionInfoOpen(true)}>📋 当前任务信息</Button><small>{MISSION.taskCode} · 本体库 {MISSION.repositoryId}</small></div>}
        <div className="sidebar-grow" />
        <Button className="settings-button" onClick={() => setSettingsOpen(true)}>⚙ 大语言模型设置</Button>
        <div className="sandbox-note">沙箱模式：智能体只能操作当前任务工作目录。<br /><span>{meta.sandbox || "sandbox/"}</span></div>
      </aside>
      <main className="main-content">
        {view === "home" ? <section className="home-view"><h1>{MISSION ? (MISSION.taskType === "integration" ? "智能消歧与整合" : "智能建模") : "本体智能体"}</h1><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={false} model={model} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></section> : <section className="task-view">
          <header className="task-header"><i className={active?.status === "working" || busy ? "status-dot working" : "status-dot"} /><strong>{active?.title || "当前任务"}</strong><Tag>{active?.workspace || active?.project}</Tag><span className="header-spacer" />{MISSION && <Switch checked={autoApprove} onChange={(value) => { setAutoApprove(value); localStorage.setItem("oc_auto_approve", value ? "1" : "0"); }} checkedChildren="自动确认" unCheckedChildren="自动确认：关" />}<Button onClick={() => { setFilesOpen(true); loadFiles(); }}>📂 文件</Button></header>
          <div className="feed"><EventFeed events={events} onApprove={approve} /></div>
          <div className="task-composer"><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={hasConversation} model={model} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></div>
        </section>}
      </main>
      <FilePanel open={filesOpen} files={files} loading={filesLoading} selected={selectedFiles} onSelect={(path) => setSelectedFiles((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])} onOpen={openFile} onDownload={download} onClose={() => setFilesOpen(false)} onRefresh={() => loadFiles()} mission={MISSION} />
      <input ref={fileInput} type="file" multiple hidden onChange={onFilesSelected} />
      {preview && <Modal open title={preview.path} footer={null} width="80vw" onCancel={() => setPreview(null)}>{preview.image ? <img className="preview-image" src={preview.image} alt={preview.path} /> : <pre className="preview-text">{preview.text}</pre>}</Modal>}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} meta={meta} model={model} onModel={onModel} params={params} onParams={onParams} provider={provider} keyValue={keyValue} setKeyValue={setKeyValue} onSaveKey={onSaveKey} />
      {MISSION && <MissionInfo context={missionContext} loading={missionLoading} onClose={() => setMissionInfoOpen(false)} />}
    </div>
  </ConfigProvider>;
}

createRoot(document.getElementById("root")).render(<AntApp><App /></AntApp>);
