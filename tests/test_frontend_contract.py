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
        self.assertIn('上传到 MinIO', source)
        self.assertIn('const uploadToMinio = async () =>', source)
        self.assertIn('missionContext?.outputPrefix', source)
        self.assertIn('onUploadToMinio={uploadToMinio}', source)
        self.assertIn('const changePlatformStatus = async () =>', source)
        self.assertIn('/api/tasks/${active.id}/platform-status', source)
        self.assertIn('active?.platformStatus === "COMPLETED" ? "修改" : "完成"', source)
        self.assertIn('请先点击“修改”恢复任务后再上传', source)
        self.assertIn('function isExpiredApprovalError(error)', source)
        self.assertIn('if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);', source)
        self.assertNotIn('else messageApi.warning(result.error);', source)
        for route in ("/api/tasks", "/api/files", "/api/mission/task", "/api/tasks/${task.id}/send", "/api/minio/upload", "/api/tasks/${active.id}/platform-status"):
            self.assertIn(route, source)

    def test_python_server_prefers_built_frontend_with_safe_assets(self):
        source = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
        self.assertIn("FRONTEND_DIST", source)
        self.assertIn("_serve_frontend_asset", source)
        self.assertIn('"..", "frontend", "dist"', source)


if __name__ == "__main__":
    unittest.main()
