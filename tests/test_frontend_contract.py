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
        self.assertIn('import { ThoughtChain } from "@ant-design/x"', source)
        for route in ("/api/tasks", "/api/files", "/api/mission/task", "/api/tasks/${task.id}/send"):
            self.assertIn(route, source)

    def test_python_server_prefers_built_frontend_with_safe_assets(self):
        source = (ROOT / "open-claude" / "oc_codex_server.py").read_text(encoding="utf-8")
        self.assertIn("FRONTEND_DIST", source)
        self.assertIn("_serve_frontend_asset", source)
        self.assertIn('"..", "frontend", "dist"', source)


if __name__ == "__main__":
    unittest.main()
