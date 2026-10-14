import os
import unittest
from types import SimpleNamespace

from langgraph_integration.runtime import ActiveRuntime, active_provider, messages_to_prompt


class MessagePromptTests(unittest.TestCase):
    def test_splits_system_and_user_messages(self):
        system, prompt = messages_to_prompt([
            {"role": "system", "content": "只返回标题"},
            SimpleNamespace(type="human", content="生成登录用例"),
        ])
        self.assertEqual(system, "只返回标题")
        self.assertEqual(prompt, "生成登录用例")


class ActiveProviderTests(unittest.TestCase):
    def test_falls_back_to_agent_runtime_env(self):
        previous = os.environ.get("AGENT_RUNTIME")
        os.environ["AGENT_RUNTIME"] = "deepseek"
        try:
            self.assertEqual(active_provider(), "deepseek")
        finally:
            if previous is None:
                os.environ.pop("AGENT_RUNTIME", None)
            else:
                os.environ["AGENT_RUNTIME"] = previous

    def test_codex_runtime_invoke_uses_complete(self):
        runtime = ActiveRuntime(SimpleNamespace(provider="codex"))
        calls = {}

        def fake_complete(prompt, system="", project_id=0):
            calls["prompt"] = prompt
            calls["system"] = system
            return "ok"

        import langgraph_integration.runtime as runtime_module
        original = runtime_module.codex_complete
        runtime_module.codex_complete = fake_complete
        try:
            result = runtime.invoke([{"role": "user", "content": "hi"}])
        finally:
            runtime_module.codex_complete = original
        self.assertEqual(result.content, "ok")
        self.assertEqual(calls["prompt"], "hi")

    def test_codex_complete_uses_short_call(self):
        import langgraph_integration.runtime as runtime_module

        calls = {}

        def fake_completion(prompt, system="", timeout_s=20):
            calls["prompt"] = prompt
            calls["system"] = system
            calls["timeout_s"] = timeout_s
            return "只返回这一句"

        import orchestrator_integration.codex_runtime as codex_module
        original = codex_module.run_codex_completion
        codex_module.run_codex_completion = fake_completion
        try:
            text = runtime_module.codex_complete("改写查询", system="只返回查询")
        finally:
            codex_module.run_codex_completion = original
        self.assertEqual(text, "只返回这一句")
        self.assertEqual(calls["timeout_s"], 20)
        self.assertNotIn("创建或修改用例", calls["system"])


if __name__ == "__main__":
    unittest.main()
