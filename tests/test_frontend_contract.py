import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_react_workbench_declares_ant_design_stack(self):
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        dependencies = {**package["dependencies"], **package["devDependencies"]}
        for name in ("react", "react-dom", "antd", "@ant-design/x", "vite"):
            self.assertIn(name, dependencies)

    def test_workbench_uses_thought_chain_and_existing_api_routes(self):
        source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
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
        self.assertIn('event.type === "thinking" && loading ? <Spin size="small" />', source)
        self.assertIn('const waitingForNextEvent = busy && !["done", "error", "approval_request"].includes(lastEvent?.type);', source)
        self.assertIn('event={{ type: "thinking", text: "" }}', source)
        self.assertIn('const approved = event.type === "approval_request" && approvalResult?.approved === true;', source)
        self.assertIn('✓ 已允许执行', source)
        self.assertIn('const approvalResults = events.reduce((result, event) =>', source)
        self.assertIn('event.type === "approval_result" ? "approval-result"', source)
        self.assertIn('event.type === "approval_result" && event.approved ? "✓"', source)
        self.assertIn('const executionFinished = event.type === "approval_request" && events.slice(index + 1).some((candidate) => candidate.type === "done");', source)
        self.assertIn('event.type === "approval_request" && !completed', source)
        styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('.thought-icon-approval-result{color:#7c3aed;background:#ede9fe}', styles)
        self.assertIn('.chain-event-approval-result .thought-toggle{color:#7c3aed}', styles)
        self.assertIn('上传到 MinIO', source)
        self.assertIn('const uploadToMinio = async () =>', source)
        self.assertIn('missionContext?.outputPrefix', source)
        self.assertIn('onUploadToMinio={uploadToMinio}', source)
        self.assertIn('modelingPlan: "分层建模计划"', source)
        self.assertIn('artifactType: "Artifact 类型"', source)
        self.assertIn('结果文件已校验并自动回写完成', source)
        self.assertIn('尚未自动完成：${result.callback.error}', source)
        self.assertNotIn('const changePlatformStatus = async () =>', source)
        self.assertNotIn('/api/tasks/${active.id}/platform-status', source)
        self.assertNotIn('platformStatus === "COMPLETED" ? "修改" : "完成"', source)
        self.assertNotIn('请先点击“修改”恢复任务后再上传', source)
        self.assertIn('function isExpiredApprovalError(error)', source)
        self.assertIn('if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);', source)
        self.assertNotIn('else messageApi.warning(result.error);', source)
        for route in ("/api/tasks", "/api/files", "/api/mission/task", "/api/tasks/${task.id}/send", "/api/minio/upload"):
            self.assertIn(route, source)

    def test_python_server_prefers_built_frontend_with_safe_assets(self):
        source = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
        self.assertIn("FRONTEND_DIST", source)
        self.assertIn("_serve_frontend_asset", source)
        self.assertIn('"..", "frontend", "dist"', source)


if __name__ == "__main__":
    unittest.main()
