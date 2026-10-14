import os
import stat
import tempfile
import unittest
from types import SimpleNamespace

from orchestrator_integration.codex_runtime import (
    EXPECTED_SDK_VERSION,
    LocalCodexAuth,
    agent_runtime,
    answer_only_instructions,
    ensure_api_key_login,
    load_local_codex_auth,
    notification_events,
    resolve_codex_bin,
    thread_model_kwargs,
    use_codex_runtime,
)


class NotificationMappingTests(unittest.TestCase):
    def test_maps_agent_delta_to_stream(self):
        notification = SimpleNamespace(
            method="item/agentMessage/delta",
            payload=SimpleNamespace(delta="你好"),
        )
        self.assertEqual(
            notification_events(notification),
            [{"type": "stream", "data": "你好"}],
        )

    def test_maps_command_start(self):
        item = SimpleNamespace(type="commandExecution", command="pytest", aggregated_output="")
        notification = SimpleNamespace(
            method="item/started",
            payload=SimpleNamespace(item=item, token_usage=None),
        )
        events = notification_events(notification)
        self.assertEqual(events[0]["type"], "step_start")
        self.assertEqual(events[0]["tool"], "command")
        self.assertIn("pytest", events[0]["input"])

    def test_completed_agent_message_is_fallback_text(self):
        item = SimpleNamespace(type="agentMessage", text="已生成用例")
        notification = SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(item=item, token_usage=None),
        )
        self.assertEqual(
            notification_events(notification),
            [{"type": "agent_message", "data": "已生成用例"}],
        )


class RuntimeSelectionTests(unittest.TestCase):
    def test_default_runtime_is_codex(self):
        previous = os.environ.pop("AGENT_RUNTIME", None)
        try:
            self.assertEqual(agent_runtime(), "codex")
            self.assertTrue(use_codex_runtime())
        finally:
            if previous is not None:
                os.environ["AGENT_RUNTIME"] = previous

    def test_resolve_codex_bin_uses_explicit_path(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
        previous = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = path
        try:
            self.assertEqual(resolve_codex_bin(), path)
        finally:
            if previous is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = previous
            os.remove(path)

    def test_sdk_version_pin(self):
        self.assertEqual(EXPECTED_SDK_VERSION, "0.162.0")

    def test_short_call_instructions_do_not_authorize_platform_writes(self):
        text = answer_only_instructions("只返回改写后的查询")
        self.assertIn("只返回改写后的查询", text)
        self.assertNotIn("MCP", text)
        self.assertNotIn("创建或修改用例", text)


class LocalApiKeyAuthTests(unittest.TestCase):
    def test_reads_provider_api_key_from_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = os.path.join(directory, ".codex")
            os.makedirs(home)
            with open(os.path.join(home, "config.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            'model_provider = "custom"',
                            'model = "gpt-6.1-sol"',
                            "",
                            "[model_providers.custom]",
                            'experimental_bearer_token = "sk-test-token"',
                            "requires_openai_auth = false",
                        ]
                    )
                )
            previous = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = home
            try:
                auth = load_local_codex_auth()
            finally:
                if previous is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous
        self.assertEqual(auth.provider, "custom")
        self.assertEqual(auth.model, "gpt-6.1-sol")
        self.assertEqual(auth.api_key, "sk-test-token")
        self.assertFalse(auth.requires_openai_auth)
        self.assertEqual(
            thread_model_kwargs(auth),
            {"model_provider": "custom", "model": "gpt-6.1-sol"},
        )
        self.assertNotIn("sk-test-token", repr(auth))

    def test_api_key_login_only_when_provider_requires_openai_auth(self):
        calls = []

        class FakeCodex:
            def login_api_key(self, api_key):
                calls.append(api_key)

        bearer = LocalCodexAuth(
            codex_home=os.path.abspath("."),
            model="gpt-6.1-sol",
            provider="custom",
            api_key="sk-test-token",
            requires_openai_auth=False,
        )
        self.assertIsNone(ensure_api_key_login(FakeCodex(), bearer))
        self.assertEqual(calls, [])

        account = LocalCodexAuth(
            codex_home=bearer.codex_home,
            model=bearer.model,
            provider=bearer.provider,
            api_key=bearer.api_key,
            requires_openai_auth=True,
        )
        ensure_api_key_login(FakeCodex(), account)
        self.assertEqual(calls, ["sk-test-token"])


if __name__ == "__main__":
    unittest.main()
