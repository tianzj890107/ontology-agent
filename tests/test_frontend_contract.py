import json
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_react_workbench_declares_ant_design_stack(self):
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        dependencies = {**package["dependencies"], **package["devDependencies"]}
        for name in ("react", "react-dom", "antd", "@ant-design/x", "vite"):
            self.assertIn(name, dependencies)

    def test_frontend_build_splits_stable_dependency_chunks(self):
        config = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
        self.assertIn("manualChunks", config)
        self.assertIn('return "ui"', config)
        self.assertIn('return undefined', config)

    def test_workbench_uses_thought_chain_and_existing_api_routes(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        # StandaloneApp renders an Ant Design Alert for request failures. Keep
        # the component imported so the 47314 entry cannot fail at runtime with
        # `ReferenceError: Alert is not defined` and leave a blank page.
        self.assertIn("  Alert,\n  App as AntApp,", source)
        # The workbench keeps @ant-design/x as a supported dependency, but the
        # visible chain is rendered directly so its icon/toggle hit areas stay
        # stable across Ant Design X releases.
        self.assertIn("function ThoughtEvent", source)
        self.assertIn('className={`thought-icon thought-icon-${kind}`}', source)
        self.assertIn('MISSION ? "点击开始任务，或者描述一个任务"', source)
        self.assertNotIn('MISSION ? "你可以直接点击开始任务', source)
        self.assertIn('<RecursiveInfo value={missionContext} />', source)
        self.assertIn('MissionInfo open={missionInfoOpen}', source)
        self.assertIn('normalizeEvents(current)', source)
        self.assertIn('autoApproveRef.current', source)
        self.assertIn('approve(event.id, true, task)', source)
        self.assertIn('approvalInFlightRef', source)
        self.assertIn('approve(pending.id, true, current)', source)
        self.assertIn('event.type === "thinking" ? <ThinkingIcon />', source)
        self.assertIn('return source.reduce((events, event) =>', source)
        self.assertIn('events[events.length - 1] = { ...last, text:', source)
        # 47314 receives each streamed thinking token as a persisted event.
        # It must use the shared adjacent-delta merger so one reasoning block
        # cannot become dozens of separate "思考中" nodes.
        self.assertIn('const journal = mergeEvents([], run.events || [], scope);', source)
        self.assertIn('const normalized = normalizeEvents({ events: journal });', source)
        self.assertIn('className={`standalone-layout ${run ? "standalone-layout-running" : ""}`}', source)
        self.assertIn('const startNewTask = () => {', source)
        self.assertIn('setRun(null);', source)
        self.assertIn('className="standalone-new-task" onClick={startNewTask}>＋ 新任务</', source)
        self.assertIn('function standaloneRunTitle(run)', source)
        self.assertIn('const [standaloneTitle, setStandaloneTitle] = useState("");', source)
        self.assertIn('setStandaloneTitle("");', source)
        self.assertIn('title: standaloneTitle.trim(),', source)
        self.assertIn('placeholder="任务名称（可选），不填时用建模要求作为会话名"', source)
        self.assertIn('title={standaloneTitle} setTitle={setStandaloneTitle}', source)
        self.assertIn('[run?.title, run?.name]', source)
        self.assertIn('return "本体建模";', source)
        self.assertIn('function formatRunCreatedAt(value)', source)
        self.assertIn('formatRunCreatedAt(item.createdAt)', source)
        self.assertIn('const updateRunSummary = (summary) =>', source)
        self.assertIn('? { ...item, ...summary, events: undefined }', source)
        self.assertIn('?includeEvents=false', source)
        self.assertIn('/events?since=', source)
        self.assertIn('const beginRunRequest = () =>', source)
        self.assertIn('const isCurrentRunRequest = (runId, generation)', source)
        self.assertIn('runRequestRef.current.controller?.abort()', source)
        self.assertIn('const selectRun = (runId) =>', source)
        self.assertIn('const cached = runs.find((item) => item.runId === runId);', source)
        self.assertIn('setRun({ ...cached, events:', source)
        self.assertIn('const standaloneEventCacheRef = useRef(new Map());', source)
        self.assertIn('const cachedEvents = Array.isArray(visibleRun?.events)', source)
        self.assertIn('files: Array.isArray(summary.files) ? summary.files : (visibleRun?.files || []),', source)
        self.assertIn('if (events.error && !cachedEvents.length)', source)
        self.assertIn('includeEvents=true', source)
        self.assertIn('standaloneEventCacheRef.current.set(runId, mergedEvents);', source)
        self.assertIn('async function standaloneApi(path, apiKey, options = {}, retrySession = true)', source)
        self.assertIn('fetch("/", { credentials: "same-origin", cache: "no-store" })', source)
        self.assertIn('return standaloneApi(path, apiKey, options, false);', source)
        self.assertIn('function standaloneRequestFailed(result)', source)
        self.assertIn('if (standaloneRequestFailed(summary))', source)
        self.assertIn('MODEL_GATE_RETRY_LIMIT', source)
        self.assertIn('void loadRun(runId, false);', source)
        self.assertIn('historical window instead of committing an incomplete chain', source)
        self.assertIn('selectRun(item.runId)', source)
        self.assertIn('role="button" tabIndex={0}', source)
        self.assertIn('selecting a run is view-only', source)
        # Multiple standalone runs may be queued or analyzed concurrently;
        # starting one must not reject the others on the client.
        self.assertNotIn('const active = runs.find((item) => ["ANALYZING", "VALIDATING"].includes(item.status));', source)
        # A rejected start must not automatically switch the user away from
        # the session they are currently viewing.
        self.assertNotIn('if (started.activeRunId) await loadRun(started.activeRunId);', source)
        self.assertIn('const continueRun = async (nextPrompt = "", selectedModel = standaloneModel) => {', source)
        self.assertIn('["CREATED", "INPUT_READY", "FAILED", "BLOCKED", "CANCELLED"].includes(run.status)', source)
        self.assertIn('eventCursorRef.current.delete(started.runId);', source)
        self.assertIn('void loadRun(started.runId);', source)
        self.assertIn('onContinue={continueRun}', source)
        self.assertIn('["FAILED", "BLOCKED", "CANCELLED"].includes(run.status) && <Button type="primary"', source)
        self.assertIn('>继续运行</Button>', source)
        self.assertIn('const [standaloneComposerText, setStandaloneComposerText] = useState("");', source)
        self.assertIn('const sendStandaloneMessage = async () =>', source)
        self.assertIn('onComposerSend={sendStandaloneMessage}', source)
        self.assertIn('className="standalone-agent-conversation"', source)
        self.assertIn('<div className="task-composer standalone-agent-task-composer"><Composer', source)
        self.assertIn('busy={busy} hasConversation={true}', source)
        self.assertIn('const [standaloneModels, setStandaloneModels] = useState([]);', source)
        self.assertIn('const loadStandaloneModels = async () =>', source)
        self.assertIn('/api/modeling-models', source)
        self.assertIn('models={standaloneModels}', source)
        self.assertIn('placeholder="继续对这个任务下指令…"', source)
        self.assertIn('/inputs', source)
        self.assertNotIn('{item.runId} · {item.status}', source)
        self.assertIn('csv: /\\.csv$/i.test(path)', source)
        self.assertIn('preview.csv ? <CsvPreview text={preview.text} />', source)
        self.assertIn('function CsvPreview({ text })', source)
        self.assertIn('/\\.(xlsx?|xlsm)$/i.test(path)', source)
        self.assertIn('response.arrayBuffer()', source)
        self.assertIn('const workbook = XLSX.read(buffer, { type: "array", cellDates: true });', source)
        self.assertIn('preview.xlsx ? <SpreadsheetPreview sheets={preview.sheets} />', source)
        self.assertIn('const waitingForNextEvent = busy && !["done", "error", "approval_request"].includes(lastEvent?.type);', source)
        self.assertIn('event={{ type: "thinking", text: "" }}', source)
        self.assertIn('const approved = event.type === "approval_request" && approvalResult?.approved === true;', source)
        self.assertIn('✓ 已允许执行', source)
        self.assertIn('const approvalResults = events.reduce((result, event) =>', source)
        self.assertIn('event.type === "approval_result" ? "approval-result"', source)
        self.assertIn('event.type === "approval_result" && event.approved ? "✓"', source)
        self.assertIn('event.type === "approval_request" ? "?"', source)
        self.assertIn('function ModelSettingsIcon()', source)
        self.assertIn('<ModelSettingsIcon /> 大语言模型设置', source)
        self.assertIn('function HistoryIcon()', source)
        self.assertIn('<HistoryIcon />历史会话', source)
        self.assertIn('>+ 新会话</Button>', source)
        self.assertIn('M15.167 8c0 .99', source)
        self.assertIn('modelText.length > 15 ? `${modelText.slice(0, 15)}...` : modelText', source)
        self.assertNotIn('DownOutlined', source)
        self.assertIn('function SendArrowIcon()', source)
        self.assertIn('fill="#fff"', source)
        self.assertIn(': <SendArrowIcon />', source)
        self.assertIn('function CurrentMissionIcon()', source)
        self.assertIn('function UploadFileIcon()', source)
        self.assertIn('<CurrentMissionIcon /> 当前任务信息', source)
        self.assertIn('<UploadFileIcon /> <span>上传文件</span>', source)
        upload_icon_start = source.index('function UploadFileIcon()')
        upload_icon_end = source.index('function DownloadSelectedIcon()')
        self.assertIn('fill="currentColor"', source[upload_icon_start:upload_icon_end])
        self.assertIn('function DownloadSelectedIcon()', source)
        self.assertIn('fillRule="evenodd"', source)
        self.assertIn('icon={<DownloadSelectedIcon />}', source)
        self.assertIn('function ReadFileIcon()', source)
        self.assertIn('function WriteFileIcon()', source)
        self.assertIn('function UploadMinioIcon()', source)
        upload_minio_start = source.index('function UploadMinioIcon()')
        upload_minio_end = source.index('function AuditIcon()')
        self.assertIn('fill="currentColor"', source[upload_minio_start:upload_minio_end])
        self.assertIn('function TaskEditIcon()', source)
        self.assertIn('function TaskCompleteIcon()', source)
        complete_icon_start = source.index('function TaskCompleteIcon()')
        complete_icon_end = source.index('function TaskFilesIcon()')
        self.assertIn('fill="#fff"', source[complete_icon_start:complete_icon_end])
        self.assertIn('function TaskFilesIcon()', source)
        self.assertIn('function FolderPanelIcon()', source)
        self.assertIn('function FileGroupChevronIcon({ collapsed })', source)
        self.assertIn('<FileGroupChevronIcon collapsed={collapsed} />', source)
        self.assertIn('icon={active?.platformStatus === "COMPLETED" ? <TaskEditIcon /> : <TaskCompleteIcon />}', source)
        self.assertIn('icon={<TaskFilesIcon />}', source)
        self.assertIn('<FolderPanelIcon />', source)
        self.assertIn('function AuditIcon()', source)
        self.assertIn('M9.75 10V7.437', source)
        self.assertIn('function TaskUpdateIcon()', source)
        self.assertIn('function CommandIcon()', source)
        self.assertIn('function ThinkingIcon()', source)
        thinking_icon_start = source.index('function ThinkingIcon()')
        thinking_icon_end = source.index('function CommandIcon()')
        self.assertIn('viewBox="0 0 16 16"', source[thinking_icon_start:thinking_icon_end])
        self.assertIn('fill="currentColor"', source[thinking_icon_start:thinking_icon_end])
        command_icon_start = source.index('function CommandIcon()')
        command_icon_end = source.index('function isExpiredApprovalError(error)')
        self.assertIn('viewBox="0 0 48 48"', source[command_icon_start:command_icon_end])
        self.assertIn('stroke="currentColor"', source[command_icon_start:command_icon_end])
        self.assertIn('event.type === "thinking" ? <ThinkingIcon />', source)
        self.assertNotIn('event.type === "thinking" ? "·"', source)
        model_icon_start = source.index('function ModelSettingsIcon()')
        model_icon_end = source.index('function TaskUpdateIcon()')
        self.assertIn('fill="currentColor"', source[model_icon_start:model_icon_end])
        self.assertIn('fill="#fff"', source)
        self.assertIn('isReadTool ? <ReadFileIcon />', source)
        self.assertIn('isWriteTool || isEditTool ? <WriteFileIcon />', source)
        self.assertIn('isAudit ? <AuditIcon />', source)
        self.assertIn('isTaskUpdate ? <TaskUpdateIcon />', source)
        self.assertIn('isCommand ? <CommandIcon />', source)
        self.assertIn('icon={<UploadMinioIcon />}', source)
        self.assertIn('event.type === "error" || event.is_error ? "ℹ"', source)
        self.assertIn('if (event.type === "error" || event.is_error) return "提示";', source)
        self.assertIn('`提示：${event.error || "本轮执行未完成，可继续执行"}`', source)
        self.assertIn('event.status === "error" ? "本轮执行结束 · 未完成（可继续执行）"', source)
        self.assertIn('const executionFinished = event.type === "approval_request" && events.slice(index + 1).some((candidate) => candidate.type === "done");', source)
        self.assertIn('event.type === "approval_request" && !completed', source)
        self.assertIn('className: "thought-collapsed-row thought-collapsed-row-clickable"', source)
        self.assertIn('const collapsedRowProps = {', source)
        self.assertIn('role: "button"', source)
        self.assertIn('clickEvent.stopPropagation(); onFile(part);', source)
        self.assertIn('const feedRef = useRef(null);', source)
        self.assertIn('const feedPinnedRef = useRef(true);', source)
        self.assertIn('const feedPrependAnchorRef = useRef(null);', source)
        self.assertIn('feed.scrollTop = Math.max(0, anchor.top + feed.scrollHeight - anchor.height);', source)
        self.assertIn('const standaloneFeedPrependAnchorRef = useRef(null);', source)
        self.assertIn('document.querySelector(".standalone-agent-feed")', source)
        self.assertIn('loadOlderStandaloneEvents(runId, 10)', source)
        self.assertIn('const historyHasMore = await loadOlderTaskEvents(current, 0, 10);', source)
        self.assertIn('if (historyHasMore) await loadOlderTaskEvents(current);', source)
        self.assertIn('if (historyHasMore) await loadOlderStandaloneEvents(runId);', source)
        self.assertIn('await waitForNextPaint();', source)
        self.assertIn('MISSION ? loadMission() : Promise.resolve()', source)
        self.assertIn('loadTasks(),', source)
        self.assertIn('/api/tasks/${task.id}?before=${window.start}&limit=160', source)
        self.assertIn('/api/modeling-runs/${encodedId}/events?tail=1&limit=80', source)
        self.assertIn('scheduleIdle(async () => {', source)
        self.assertIn('if (feed && feedPinnedRef.current) feed.scrollTop = feed.scrollHeight;', source)
        self.assertIn('feedPinnedRef.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 56;', source)
        self.assertIn('onScroll={handleFeedScroll}', source)
        self.assertIn('feed.scrollTop = feed.scrollHeight;', source)
        self.assertIn('}, [events, busy, view]);', source)
        self.assertIn('}, [events, view, filesOpen]);', source)
        self.assertIn('<div ref={feedRef} className="feed" onScroll={handleFeedScroll}>', source)
        self.assertIn('body: JSON.stringify({ message: content, displayMessage, startTask, intent, clientMessageId })', source)
        self.assertNotIn('startTask, missionContext:', source)
        self.assertIn('function missionIdentity(task = null)', source)
        self.assertIn('const taskMission = missionIdentity(task)', source)
        self.assertIn('sendToTask(task, messageText, display, start, intent)', source)
        self.assertIn('function formatDuration(durationMs)', source)
        self.assertIn('`已思考 ${formatDuration(durationMs)}`', source)
        self.assertIn('durationMs={eventDuration(events, index)}', source)
        self.assertIn('["done", "tool_result", "approval_result", "audit", "error"]', source)
        self.assertIn('const stamped = stampEvent(event);', source)
        styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('.thought-icon-approval-result{color:#7c3aed;background:#ede9fe}', styles)
        self.assertIn('.chain-event-approval-result .thought-toggle{color:#7c3aed}', styles)
        self.assertIn('.thought-summary{flex:1;min-width:0;max-width:100%', styles)
        self.assertIn('.thought-duration{flex:none;', styles)
        self.assertIn('.thought-collapsed-row-clickable{display:flex;width:75%;max-width:75%', styles)
        self.assertIn('.thought-collapsed-row-clickable:hover{background:#f1f5f9;box-shadow:0 2px 8px rgba(15,23,42,.14)}', styles)
        self.assertIn('.chain-event{position:relative;padding:3px 0;', styles)
        self.assertIn('.feed-list{gap:2.4px}', styles)
        self.assertIn('.chain-event::before{display:none!important;content:none!important}.chain-event:not(:last-child)::after{left:17px;top:27px;bottom:-7px;width:1px;background:#cbd5e1}', styles)
        self.assertIn('.thought-icon-error{color:#64748b;background:#e2e8f0}', styles)
        self.assertIn('.task-row i.error{background:#94a3b8}', styles)
        self.assertIn('.approval-actions .ant-btn-primary,.file-actions .ant-btn-primary{background:#2563eb!important', styles)
        self.assertIn('.new-task,.start-button,.send-button{background:linear-gradient(135deg,#2563eb,#1e40af)!important', styles)
        self.assertIn('.new-task{height:32px!important;margin:10px 0 0', styles)
        self.assertIn('.approval-actions .ant-btn-primary:disabled,.auto-approve-toggle,.file-actions .ant-btn-primary{font-weight:400!important}', styles)
        self.assertIn('.approval-actions .ant-btn-primary:disabled,.file-actions .ant-btn-primary,.auto-approve-toggle.ant-btn-primary{background:#fff!important', styles)
        self.assertIn('.auto-approve-toggle.ant-btn-default{background:#fff!important;border-color:#d9d9d9!important', styles)
        self.assertIn('.task-header .ant-btn-primary{background:linear-gradient(135deg,#2563eb,#1e40af)!important', styles)
        self.assertIn('.auto-approve-toggle.ant-btn-default{background:#fff!important;border-color:#d9d9d9!important', styles)
        self.assertIn('.file-row>input[type=checkbox]{margin-left:19px', styles)
        self.assertIn('.thought-icon-read-file{color:#0f766e;background:#ccfbf1}', styles)
        self.assertIn('.thought-icon-write-file,.thought-icon-edit-file{color:#c2410c;background:#ffedd5}', styles)
        self.assertIn('.thought-icon-read-file svg,.thought-icon-write-file svg,.thought-icon-edit-file svg,.thought-icon-audit svg,.thought-icon-task-update svg,.thought-icon-command svg{width:12px;height:12px}', styles)
        self.assertIn('.thought-icon-audit{color:#8f9299;background:#f1f5f9}', styles)
        self.assertIn('.model-settings-icon{display:block;flex:none;width:16px;height:16px}', styles)
        self.assertIn('.thought-icon-task-update{color:#7c3aed;background:#ede9fe}', styles)
        self.assertIn('.thought-icon-command{color:#2563eb;background:#dbeafe}', styles)
        self.assertIn('.thought-icon-thinking svg{width:12px;height:12px}', styles)
        self.assertIn('.standalone-layout-running{padding-bottom:24px}', styles)
        self.assertIn('.standalone-new-task{margin-bottom:14px}', styles)
        self.assertIn('.standalone-agent-task-view{display:flex;flex-direction:column;height:calc(100dvh - 112px);min-height:0', styles)
        self.assertIn('.standalone-agent-task-body{display:flex;flex:1;height:auto;min-height:0}', styles)
        self.assertIn('.standalone-agent-conversation{display:flex;flex:1;min-width:0;min-height:0;flex-direction:column}', styles)
        self.assertIn('.standalone-agent-conversation .standalone-agent-task-composer{flex:none;width:100%', styles)
        self.assertIn('上传到 MinIO', source)
        self.assertIn('const uploadToMinio = async () =>', source)
        self.assertNotIn('prefix: missionContext?.outputPrefix', source)
        self.assertIn('const intent = start ? "execute" : task.platformStatus === "COMPLETED" ? "chat" : "auto";', source)
        self.assertIn('onUploadToMinio={uploadToMinio}', source)
        self.assertIn('["root", "input", "work", "output"].forEach', source)
        self.assertIn('const defaultCollapsedDirs = () => new Set(["root", "input"]);', source)
        self.assertIn('file?.displayPath || file?.path', source)
        self.assertIn('const renderSubgroup = (dir, subdir, items)', source)
        self.assertIn('setCollapsedDirs(defaultCollapsedDirs());', source)
        self.assertIn('workspaceFolders = false', source)
        self.assertIn('workspaceFolders resetKey={run.runId}', source)
        self.assertIn('function hasMissionOutputFiles(files = [])', source)
        self.assertIn('const shouldOpenFiles = hasMissionOutputFiles(loadedFiles);', source)
        self.assertIn('if (shouldOpenFiles) setFilesOpen(true);', source)
        self.assertIn('startsWith("mission-output/")', source)
        self.assertIn('!files.length && !mission && !workspaceFolders ? <Empty description="暂无文件" />', source)
        self.assertIn('className="file-group-empty">暂无文件', source)
        self.assertIn('modelingPlan: "分层建模计划"', source)
        self.assertIn('artifactType: "Artifact 类型"', source)
        self.assertIn('if (result.completionHint) messageApi.info(result.completionHint);', source)
        self.assertIn('const changePlatformStatus = async () =>', source)
        self.assertIn('/api/tasks/${active.id}/platform-status', source)
        self.assertIn('isMissionTask && active?.platformStatus !== "FAILED" && <Button type={active?.platformStatus === "COMPLETED" ? "default" : "primary"}', source)
        self.assertIn('mission={isMissionTask}', source)
        self.assertIn('const toggleAutoApprove = () =>', source)
        self.assertIn('已开启自动确认', source)
        self.assertIn('已关闭自动确认', source)
        self.assertIn('showAutoApprove={isMissionTask}', source)
        self.assertIn('上传文件</span></Button>', source)
        self.assertIn('上传新结果将恢复任务为执行中', source)
        self.assertNotIn('"当前任务范围"', source)
        self.assertIn('<Button className="new-task" onClick={handleNewSession}>+ 新会话</Button>', source)
        self.assertIn('const reuseMissionTask = async () =>', source)
        self.assertIn('const handleNewSession = async () =>', source)
        self.assertIn('if (MISSION) {\n      await reuseMissionTask();\n      return;', source)
        self.assertIn('messageApi.success("已复用当前任务，不会新建会话")', source)
        self.assertNotIn('import * as XLSX from "xlsx";', source)
        self.assertIn('import("xlsx")', source)
        self.assertIn('URL.revokeObjectURL(previewImageUrlRef.current)', source)
        self.assertIn('requestId !== previewRequestRef.current', source)
        self.assertIn('uploadBlocked={busy || active?.status === "working" || active?.status === "queued" || platformActionLoading}', source)
        self.assertIn('任务已完成，请先点击“修改”再上传新的输入文件', source)
        self.assertIn('const refreshedTasks = await loadTasks();', source)
        self.assertIn('function isExpiredApprovalError(error)', source)
        self.assertIn('if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);', source)
        self.assertNotIn('else messageApi.warning(result.error);', source)
        for route in ("/api/tasks", "/api/files", "/api/mission/task", "/api/tasks/${taskId}/send", "/api/minio/upload"):
            self.assertIn(route, source)

    def test_python_server_prefers_built_frontend_with_safe_assets(self):
        source = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
        self.assertIn("FRONTEND_DIST", source)
        self.assertIn("_serve_frontend_asset", source)
        self.assertIn('"..", "frontend", "dist"', source)
        self.assertIn('html_path = os.path.join(FRONTEND_DIST, "index.html")', source)
        self.assertIn("built React frontend not found; run npm run build", source)
        self.assertNotIn("HTML_PATH", source)
        self.assertNotIn("codex_web.html", source)
        self.assertIn('cache_control="public, max-age=31536000, immutable"', source)
        self.assertIn("def _stamp_event(event)", source)
        self.assertIn('"timestamp": time.time()', source)
        self.assertIn('thinking_event = self._record_event({"type": "thinking", "text": ev["text"]})', source)
        self.assertIn('emit(thinking_event)', source)

    def test_numeric_display_contract_is_global_and_semantic(self):
        formatter = (ROOT / "frontend" / "src" / "numberFormat.js").read_text(encoding="utf-8")
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        spec = (ROOT / "agent_knowledge" / "数字展示规范v0.0.1.md").read_text(encoding="utf-8")
        self.assertIn('absolute >= 10000', formatter)
        self.assertIn('minimumFractionDigits: currency ? 2 : 0', formatter)
        self.assertIn('if (currency && compact && absolute >= 10000)', formatter)
        self.assertIn('formatDisplayValue', source)
        self.assertIn('isNumericDisplayValue', source)
        self.assertIn('.numeric-cell,.numeric-header,.numeric-value', styles)
        self.assertIn('¥12,345.00', spec)
        self.assertIn('¥12.34万', spec)
        self.assertIn('禁止显示', spec)

    def test_standalone_download_selected_uses_explicit_paths(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        # React passes the click event to onClick handlers. The standalone
        # download handler must receive the selected file paths explicitly,
        # otherwise `for (const path of paths)` throws "event is not iterable"
        # and the download silently never starts.
        self.assertIn("onClick={() => onDownload(selected)}>下载所选", source)
        self.assertIn("const selected = Array.isArray(paths) && paths.length ? paths : selectedRunFiles;", source)
        # Downloads must tolerate an expired browser session cookie the same
        # way the JSON API path does (refresh once via the root page).
        self.assertIn("async function standaloneFileResponse(path)", source)
        self.assertIn('credentials: "same-origin"', source)
        self.assertIn('const refreshed = await fetch("/", { credentials: "same-origin", cache: "no-store" });', source)
        self.assertIn("standaloneFileResponse(`/api/modeling-runs/${encodeURIComponent(run.runId)}/files/content?path=${encodeURIComponent(path)}`)", source)
        # The blob download must survive the click: append the anchor to the
        # DOM and revoke the object URL asynchronously instead of revoking it
        # synchronously right after link.click().
        self.assertIn("document.body.appendChild(link);", source)
        self.assertIn("link.click();", source)
        self.assertIn("document.body.removeChild(link);", source)
        self.assertIn("setTimeout(() => URL.revokeObjectURL(url), 1000);", source)
        self.assertNotIn("link.click();\n      URL.revokeObjectURL(link.href);", source)
        # Failures must be reported instead of silently skipped.
        self.assertIn("messageApi.success(`已开始下载 ${okCount} 个文件`)", source)
        self.assertIn("messageApi.error(`下载失败 ${failed.length} 个文件", source)
        # The run-detail payload already carries the file tree; keep it so the
        # panel is populated immediately instead of after the (slow) journal
        # replay, which previously left the download button unusable.
        self.assertIn("files: Array.isArray(summary.files) ? summary.files : (visibleRun?.files || []),", source)
        idle_start = source.index("scheduleIdle(async () => {")
        files_first = source.index("await loadRunFiles(runId);", idle_start)
        history_load = source.index("await loadOlderStandaloneEvents(runId, 10);", idle_start)
        self.assertLess(files_first, history_load)

    def test_mission_file_panel_draws_available_ontology_layers(self):
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("echarts", package["dependencies"])
        self.assertIn('function buildOntologyGraph(records)', source)
        self.assertIn('businessObject: ["business_objects.csv"]', source)
        self.assertIn('logicalEntity: ["logical_entities.csv"]', source)
        self.assertIn('businessAttribute: ["business_attributes.csv"]', source)
        self.assertIn('metric: ["metrics.csv", "indicators.csv", "indicator.csv"', source)
        self.assertIn('businessRule: ["business_rules.csv", "rules.csv"]', source)
        self.assertIn('return selected.has("logicalEntity") ? selected : null;', source)
        self.assertIn('type: "graph"', source)
        self.assertIn('layout: "none"', source)
        self.assertNotIn('type: "tree"', source)
        layout_module = (ROOT / "frontend" / "src" / "ontologyRadialLayout.js").read_text(encoding="utf-8")
        self.assertIn('export const ONTOLOGY_LAYER_DEFINITIONS = [', layout_module)
        self.assertIn('export function computeTrackCapacity(', layout_module)
        self.assertIn('export function computeTrackCount(', layout_module)
        self.assertIn('export function computeRingRadius(', layout_module)
        self.assertIn('export function layoutOntologyRadial(', layout_module)
        self.assertIn('export function computeSectorAngles(', layout_module)
        self.assertIn('fitSectorTrackWithoutOverlap(batches, radius, placed, minGap, trackIndex)', layout_module)
        self.assertIn('weight: Math.sqrt(sectorCounts.get(id) || 1)', layout_module)
        self.assertIn('boundaryAnchors', layout_module)
        self.assertIn('export function computeFitScale(', layout_module)
        self.assertIn('export function scaledTypography(', layout_module)
        self.assertIn('const [appliedLayers, setAppliedLayers]', source)
        self.assertIn('const [draftLayers, setDraftLayers]', source)
        self.assertIn('setAppliedLayers(ONTOLOGY_LAYER_DEFINITIONS.map', source)
        self.assertIn('>确认</Button>', source)
        self.assertIn('disabled={!availability[layer.key]}', source)
        self.assertIn('className="ontology-layer-filter-button"', source)
        self.assertIn('fillRule="evenodd"', source)
        self.assertIn('nodeScaleRatio: 1', source)
        self.assertIn('const displayScale = Math.max(fitScale, 0.65);', source)
        self.assertIn('scaledTypography(13, displayScale, roamZoom)', source)
        self.assertIn('if (event.ctrlKey) return;', source)
        self.assertIn('type: "graphRoam", seriesIndex: 0, dx: -event.deltaX, dy: -event.deltaY', source)
        self.assertIn('addEventListener("wheel", wheelHandler, { passive: false, capture: true })', source)
        self.assertIn('roam: true', source)
        self.assertIn('observer = new ResizeObserver(() => renderGraph());', source)
        self.assertIn('emphasis: { focus: "none", scale: 1.12 }', source)
        self.assertIn('selectedMode: false', source)
        self.assertNotIn('chart.on("click", ({ data: clicked }) =>', source)
        self.assertIn('const [filesTaskId, setFilesTaskId] = useState("");', source)
        self.assertIn('if (activeTaskIdRef.current !== taskId || filesRequestRef.current !== requestId) return [];', source)
        self.assertIn('onClick={onDrawOntology}>本体可视化</Button>', source)
        self.assertNotIn('>{ontologyReady ? "展示" : "画图"}</Button>', source)
        self.assertIn('缺少逻辑实体 CSV，不能进行本体可视化', source)
        self.assertIn('const drawStandaloneOntology = async () =>', source)
        self.assertIn('standaloneFileResponse(`/api/modeling-runs/${encodeURIComponent(runId)}/files/content?', source)
        self.assertIn('onDrawOntology={drawStandaloneOntology}', source)
        self.assertIn('function PreviewModalTitle({ title, fullscreen, onToggle })', source)
        self.assertIn('className={previewFullscreen ? "preview-modal preview-modal-fullscreen" : "preview-modal"}', source)
        self.assertIn('centered={!previewFullscreen}', source)
        self.assertIn('wrapClassName={previewFullscreen ? "preview-modal-wrap-fullscreen" : ""}', source)
        self.assertIn('symbolSize: [Math.max(92, Math.min(220, length * 14 + 32)), 38]', source)
        self.assertIn('position: "inside"', source)
        self.assertIn('preview.ontologyGraph ? <OntologyTreePreview data={preview.ontologyGraph} />', source)
        self.assertIn('.ontology-tree-preview{', styles)
        self.assertIn('.ontology-tree-scroll{', styles)
        self.assertIn('.ontology-layer-filter-button{', styles)
        self.assertIn('.preview-modal-title>button{position:absolute;top:12px;right:48px;', styles)


    def test_continue_run_preserves_event_cursor_and_guards_double_submit(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        # Double clicks on Continue must not issue two /execute POSTs.
        self.assertIn("const continueInFlightRef = useRef(false);", source)
        self.assertIn("if (continueInFlightRef.current) return;", source)
        self.assertIn("continueInFlightRef.current = true;", source)
        self.assertIn("continueInFlightRef.current = false;", source)
        self.assertLess(
            source.index("continueInFlightRef.current = true;"),
            source.index("standaloneApi(`/api/modeling-runs/${encodeURIComponent(run.runId)}/execute`"),
        )
        # A continue appends to the same run: when this browser already loaded
        # the event window, only pull the delta via /events?since=cursor.
        self.assertIn("if (eventWindowRef.current.has(started.runId)) {", source)
        self.assertIn("void refreshRun(started.runId);", source)
        self.assertIn("eventCursorRef.current.delete(started.runId);", source)
        self.assertIn("void loadRun(started.runId);", source)
        continue_start = source.index("const continueRun = async (nextPrompt")
        has_branch = source.index("if (eventWindowRef.current.has(started.runId)) {", continue_start)
        self.assertLess(has_branch, source.index("void loadRun(started.runId);", continue_start))
        # refreshRun must keep the persisted cursor and never reload the whole
        # journal when the window is already loaded.
        self.assertIn("const cursor = eventCursorRef.current.get(runId) || 0;", source)
        self.assertIn("`/api/modeling-runs/${encodedId}/events?since=${cursor}`", source)
        self.assertIn("eventCursorRef.current.set(runId, nextCursor(events, delta));", source)
        self.assertIn("if (!eventWindowRef.current.has(runId)) return null;", source)
        # The already-rendered file tree must survive until refresh replaces it.
        self.assertIn("return { ...started, files: Array.isArray(run.files) ? run.files : [] };", source)
        self.assertIn("events: current.events,", source)
        self.assertIn("if (!run?.runId || ![\"CREATED\", \"INPUT_READY\", \"FAILED\", \"BLOCKED\", \"CANCELLED\"].includes(run.status)) return;", source)


    def test_event_sync_merge_is_idempotent_and_seq_safe(self):
        """Behavioral check of the shared merge through the Node runtime."""
        script = (
            "import { mergeEvents, appendStreamEvent, nextCursor } from './src/eventSync.js';"
            "const snapshot = [{seq:0,type:'user',text:'继续'},{seq:1,type:'run_queued'}];"
            "const delta = [{seq:0,type:'user',text:'继续'},{seq:2,type:'run_started'}];"
            "const merged = mergeEvents(snapshot, delta, 'run:1');"
            "if (JSON.stringify(merged.map(e=>e.seq)) !== '[0,1,2]') throw new Error('merge not idempotent');"
            "const older = [{seq:0,type:'user',text:'继续'}];"
            "const newer = [{seq:0,type:'user',text:'继续'},{seq:1,type:'run_queued'}];"
            "if (mergeEvents(older, newer, 'run:1').length !== 2) throw new Error('prepend overlap');"
            "const sameText = [{seq:3,type:'user',text:'继续'},{seq:4,type:'user',text:'继续'}];"
            "if (mergeEvents([], sameText, 'run:1').length !== 2) throw new Error('same text diff seq must keep both');"
            "const stream = appendStreamEvent([{type:'user',text:'x',clientMessageId:'cm1'}], {type:'user',text:'x',clientMessageId:'cm1',seq:0}, 'task:1');"
            "if (stream.length !== 1) throw new Error('stream dedupe failed');"
            "if (nextCursor({eventStart:10,eventEnd:12,nextCursor:12},[1,2]) !== 12) throw new Error('absolute cursor');"
            "console.log('eventSync ok');"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(ROOT / "frontend"), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("eventSync ok", result.stdout)

    def test_event_sync_contract_unifies_identity_cursor_and_error_handling(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        sync = (ROOT / "frontend" / "src" / "eventSync.js").read_text(encoding="utf-8")
        standalone = (ROOT / "open-claude" / "standalone_modeling_server.py").read_text(encoding="utf-8")
        window_module = (ROOT / "open-claude" / "open_claude" / "event_window.py").read_text(encoding="utf-8")
        # One shared idempotent merge feeds both the workbench and the
        # standalone workspace; execute snapshots never double-apply as deltas.
        self.assertIn('import { appendStreamEvent, eventKey, mergeEvents, nextCursor } from "./eventSync.js";', source)
        for exported in ("export function mergeEvents", "export function eventIdentity",
                         "export function nextCursor", "export function appendStreamEvent"):
            self.assertIn(exported, sync)
        self.assertIn("self._send(202, run.as_dict(include_events=False))", standalone)
        # The unified window contract (eventStart/eventEnd/eventTotal/
        # eventHasMore/nextCursor) is generated by the shared module consumed
        # by both services, so boundary semantics cannot drift.
        self.assertIn('"nextCursor": end', window_module)
        self.assertIn('"eventHasMore": start > 0', window_module)
        # Domain error fields on 2xx responses are not API/transport failures.
        self.assertIn("if (standaloneRequestFailed(started))", source)
        self.assertIn("if (standaloneRequestFailed(created))", source)
        # Cursor is the server-absolute next-read position, never only
        # `cursor + delta.length`.
        self.assertIn("eventCursorRef.current.set(runId, nextCursor(events, delta));", source)
        self.assertIn("nextCursor(eventPayload, latestEvents)", source)
        self.assertNotIn("eventCursorRef.current.set(runId, cursor + delta.length);", source)
        # Poll lock is per-run so session A can never block/release session B.
        self.assertIn("pollInFlightRef.current.has(runId)", source)
        self.assertIn("pollInFlightRef.current.set(runId, true);", source)
        self.assertIn("pollInFlightRef.current.delete(runId);", source)
        # Initial prompt bubble is synthesized only without a formal user
        # event; the BLOCKED advice and prompt bubble carry stable keys.
        self.assertIn('const hasUserEvent = normalized.some((event) => event.type === "user");', source)
        self.assertIn("_key: `prompt:${run.runId}`", source)
        self.assertIn("_key: `blocked-advice:${run.runId}`", source)
        self.assertIn('function eventKey(event, scope = "default", index = 0)', sync)
        # 47313 optimistic user messages reconcile through clientMessageId and
        # the shared stream merge; busy is request-scoped.
        self.assertIn('const clientMessageId = `cm-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;', source)
        self.assertIn("body: JSON.stringify({ message: content, displayMessage, startTask, intent, clientMessageId })", source)
        self.assertIn("appendStreamEvent(previous, stamped, `task:${taskId}`)", source)
        self.assertIn("mergeEvents(older, current, `task:${task.id}`)", source)
        self.assertIn("const busyRequestRef = useRef(0);", source)
        self.assertIn("if (busyRequestRef.current === requestId) setBusy(false)", source)
        self.assertIn('if (activeTaskIdRef.current !== taskId) return;', source)

    def test_task_events_endpoint_and_active_run_exists_contract(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        server = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
        window_module = (ROOT / "open-claude" / "open_claude" / "event_window.py").read_text(encoding="utf-8")
        # 47313 exposes the same absolute-position journal route as 47314 and
        # answers with the shared window contract under taskId.
        self.assertIn(r"^/api/tasks/([0-9a-f]+)/events$", server)
        self.assertIn('scope_id=task.id,\n                    scope_key="taskId"', server)
        self.assertIn("_parse_event_window(event_query, total)", server)
        # Opening a task fetches the summary plus a tail window, older pages
        # use before=window.start, and live compensation uses since=cursor.
        self.assertIn("`?tail=1&limit=80${identityQuery}`", source)
        self.assertIn("`/api/tasks/${task.id}?before=${window.start}&limit=160${identity}`", source)
        self.assertIn("`/api/tasks/${taskId}/events?since=${cursor}${identity}`", source)
        self.assertIn("cursor: logTotal", source)
        # ACTIVE_RUN_EXISTS: drop the duplicate optimistic bubble and resume
        # the existing execution instead of a generic red error.
        self.assertIn('payload?.code === "ACTIVE_RUN_EXISTS"', source)
        self.assertIn("current.filter((event) => event.clientMessageId !== clientMessageId)", source)
        self.assertIn('messageApi.info("任务正在执行，已恢复当前进度")', source)
        # Every window path (snapshot/tail/since/before/SSE) converges on the
        # shared merge; old requests from a previous session cannot write into
        # the currently selected task.
        self.assertIn("mergeEvents(current, delta, `task:${taskId}`)", source)
        self.assertIn("mergeEvents(older, current, `task:${task.id}`)", source)
        self.assertIn("activeTaskIdRef.current !== taskId", source)
        self.assertIn("taskPollInFlightRef.current.has(taskId)", source)
        # The task detail endpoint must not default to the full journal.
        self.assertIn('include_events = ("tail" in detail_query or "before" in detail_query', server)
        # 409 payload shape is unified.
        self.assertIn('"code": "ACTIVE_RUN_EXISTS"', server)
        self.assertIn('"code": "ACTIVE_RUN_EXISTS"', server)
        self.assertIn("task.claim_execution()", server)
        self.assertIn("task.release_execution(execution_id)", server)

    def test_legacy_static_frontends_are_removed(self):
        self.assertEqual([], sorted(ROOT.glob("*.html")))
        for name in ("codex_web.html", "generic_claude_gpt_style_chat.html"):
            self.assertFalse((ROOT / "open-claude" / name).exists())


if __name__ == "__main__":
    unittest.main()
