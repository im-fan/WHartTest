"""使用与本机 CLI 同版本的 openai-codex SDK 调度测试任务。"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

EXPECTED_SDK_VERSION = "0.162.0"
EXPECTED_CLI_VERSION = "0.162.0"


class CodexRuntimeError(RuntimeError):
    """Codex 运行时无法启动或版本不匹配。"""


@dataclass
class LocalCodexAuth:
    """本机 Codex 配置中的模型与 API key，不包含 ChatGPT 登录。"""

    codex_home: Path
    model: str
    provider: str
    api_key: str
    requires_openai_auth: bool

    def __repr__(self) -> str:
        return (
            f"LocalCodexAuth(provider={self.provider!r}, model={self.model!r}, "
            f"has_api_key={bool(self.api_key)})"
        )


def agent_runtime() -> str:
    return os.environ.get("AGENT_RUNTIME", "codex").strip().lower() or "codex"


def use_codex_runtime() -> bool:
    return agent_runtime() == "codex"


def data_root() -> Path:
    configured = os.environ.get("DATA_DIR", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            from django.conf import settings

            path = Path(settings.BASE_DIR) / path
        return path.resolve()
    from django.conf import settings

    return (Path(settings.BASE_DIR).parent / "data").resolve()


def resolve_codex_bin() -> str:
    candidates = []
    configured = os.environ.get("CODEX_BIN", "").strip()
    if configured:
        candidates.append(configured)
    found = shutil.which("codex")
    if found:
        candidates.append(found)
    home = Path.home()
    candidates.extend([
        str(home / ".npm-global" / "bin" / "codex"),
        str(home / ".local" / "bin" / "codex"),
        "/usr/local/bin/codex",
    ])
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise CodexRuntimeError(
        "未找到可执行的本机 Codex CLI。请安装 codex 0.162.0，或设置 CODEX_BIN。"
    )


def assert_sdk_version() -> str:
    try:
        import openai_codex
    except ImportError as exc:
        raise CodexRuntimeError(
            "未安装 openai-codex。请安装与本机 CLI 相同的版本：pip install openai-codex==0.162.0"
        ) from exc
    version = getattr(openai_codex, "__version__", "")
    if version != EXPECTED_SDK_VERSION:
        raise CodexRuntimeError(
            f"openai-codex 版本是 {version or '未知'}，需要与本机 CLI 对齐的 {EXPECTED_SDK_VERSION}。"
        )
    return version


def workspace_for(kind: str, key: str) -> Path:
    safe_key = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(key))
    path = data_root() / "codex-workspaces" / kind / safe_key
    (path / "output").mkdir(parents=True, exist_ok=True)
    (path / "context").mkdir(parents=True, exist_ok=True)
    agents = path / "AGENTS.md"
    if not agents.exists():
        agents.write_text(
            "\n".join(
                [
                    "# WHartTest Codex 工作区",
                    "",
                    "只在当前工作区完成任务。交付物写入 output/。",
                    "平台数据通过 MCP 工具 wharttest 读写，不要直接连接数据库。",
                    "不要修改工作区以外的文件。",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return path


def thread_state_path(session_id: str) -> Path:
    return workspace_for("sessions", session_id) / "thread.json"


def load_thread_id(session_id: str) -> str:
    path = thread_state_path(session_id)
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("thread_id") or "")


def save_thread_id(session_id: str, thread_id: str) -> None:
    path = thread_state_path(session_id)
    path.write_text(
        json.dumps({"thread_id": thread_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def developer_instructions(project_id: int, goal: str = "") -> str:
    backend = os.environ.get("DJANGO_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    lines = [
        "你是 WHartTest 的测试实现代理。",
        f"当前项目 ID 是 {project_id}。",
        f"平台 API 基址是 {backend}。",
        "需要创建或修改用例、接口步骤、UI 步骤时，调用 wharttest MCP。",
        "把生成的说明、脚本和无法直接写入平台的产物放到 output/。",
        "完成后用中文给出已实现的内容和仍需人工确认的点。",
    ]
    if goal:
        lines.append(f"本次目标：{goal}")
    return "\n".join(lines)


def mcp_config_overrides() -> tuple[str, ...]:
    from django.conf import settings

    tools = Path(settings.BASE_DIR).parent / "WHartTest_MCP" / "WHartTest_tools.py"
    if not tools.is_file():
        return ()
    python = os.environ.get("CODEX_MCP_PYTHON", "").strip() or shutil.which("python3") or "python3"
    return (
        f"mcp_servers.wharttest.command={json.dumps(python)}",
        f"mcp_servers.wharttest.args={json.dumps([str(tools)])}",
    )


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def load_local_codex_auth() -> LocalCodexAuth:
    """读取本机 ~/.codex/config.toml 里当前供应商的 API key。"""
    home = codex_home()
    config_path = home / "config.toml"
    if not config_path.is_file():
        raise CodexRuntimeError(
            f"未找到本机 Codex 配置 {config_path}，无法读取 API key。"
        )
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    provider = str(data.get("model_provider") or "").strip()
    model = str(data.get("model") or "").strip()
    providers = data.get("model_providers") or {}
    provider_cfg = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}
    api_key = str(
        provider_cfg.get("experimental_bearer_token")
        or provider_cfg.get("api_key")
        or ""
    ).strip()
    if not provider or not api_key:
        raise CodexRuntimeError(
            "本机 Codex 配置缺少 model_provider 或 experimental_bearer_token。"
        )
    return LocalCodexAuth(
        codex_home=home,
        model=model,
        provider=provider,
        api_key=api_key,
        requires_openai_auth=bool(provider_cfg.get("requires_openai_auth", False)),
    )


def thread_model_kwargs(auth: LocalCodexAuth) -> dict[str, str]:
    kwargs = {}
    if auth.provider:
        kwargs["model_provider"] = auth.provider
    if auth.model:
        kwargs["model"] = auth.model
    return kwargs


def ensure_api_key_login(codex: Any, auth: LocalCodexAuth) -> Any:
    """供应商要求 OpenAI 账号时，用配置里的 API key 登录。否则沿用配置中的 bearer token。"""
    if not auth.requires_openai_auth:
        return None
    return codex.login_api_key(auth.api_key)


def codex_child_env(api_key: str = "", auth: LocalCodexAuth | None = None) -> dict[str, str]:
    env = {
        "WHARTTEST_BACKEND_URL": os.environ.get("DJANGO_BASE_URL", "http://127.0.0.1:8000"),
        "WHARTTEST_API_KEY": api_key or os.environ.get("WHARTTEST_API_KEY", ""),
    }
    if auth is not None:
        env["CODEX_HOME"] = str(auth.codex_home)
    return {key: value for key, value in env.items() if value}


def build_codex_config(cwd: Path):
    assert_sdk_version()
    from openai_codex import CodexConfig

    return CodexConfig(
        codex_bin=resolve_codex_bin(),
        cwd=str(cwd),
        client_name="wharttest",
        client_title="WHartTest",
        client_version=EXPECTED_SDK_VERSION,
        env=codex_child_env(),
        config_overrides=mcp_config_overrides(),
    )


def item_root(item: Any) -> Any:
    return getattr(item, "root", item)


def summarize_item(item: Any) -> tuple[str, str]:
    node = item_root(item)
    kind = getattr(node, "type", "") or node.__class__.__name__
    if kind == "commandExecution":
        command = getattr(node, "command", "") or ""
        output = getattr(node, "aggregated_output", "") or ""
        return "command", f"$ {command}\n{output}".strip()
    if kind == "mcpToolCall":
        server = getattr(node, "server", "")
        tool = getattr(node, "tool", "")
        error = getattr(node, "error", None)
        result = getattr(node, "result", None)
        body = f"{server}/{tool}"
        if error:
            body = f"{body} 失败: {error}"
        elif result is not None:
            body = f"{body}\n{result}"
        return f"{server}/{tool}" if server else str(tool or "mcp"), body
    if kind == "fileChange":
        changes = getattr(node, "changes", None) or []
        names = []
        for change in changes:
            path = getattr(change, "path", None) or getattr(change, "file", None) or str(change)
            names.append(str(path))
        return "file_change", "\n".join(names) or "文件已修改"
    if kind == "agentMessage":
        return "agent", getattr(node, "text", "") or ""
    return str(kind or "tool"), str(getattr(node, "text", "") or kind)


def notification_events(notification: Any) -> list[dict[str, Any]]:
    payload = getattr(notification, "payload", None)
    method = getattr(notification, "method", "") or ""
    delta = getattr(payload, "delta", None)
    if method == "item/agentMessage/delta" and isinstance(delta, str) and delta:
        return [{"type": "stream", "data": delta}]
    if method == "commandExecution/outputDelta" and isinstance(delta, str) and delta:
        return [{"type": "tool_result", "tool": "command", "output": delta}]
    item = getattr(payload, "item", None)
    if method == "item/started" and item is not None:
        name, summary = summarize_item(item)
        if name == "agent":
            return []
        return [{"type": "step_start", "tool": name, "input": summary[:2000]}]
    usage = getattr(payload, "token_usage", None)
    if usage is not None:
        last = getattr(usage, "last", None)
        if last is not None:
            return [{
                "type": "context_update",
                "input_tokens": int(getattr(last, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(last, "output_tokens", 0) or 0),
                "total_tokens": int(getattr(last, "total_tokens", 0) or 0),
            }]
    if method == "turn/completed":
        turn = getattr(payload, "turn", None)
        error = getattr(turn, "error", None)
        if error:
            return [{"type": "error", "message": str(error)}]
        return []
    if method == "item/completed" and item is not None:
        name, summary = summarize_item(item)
        if name == "agent" and summary:
            return [{"type": "agent_message", "data": summary}]
        return [{"type": "step_complete", "tool": name, "output": summary[:4000]}]
    return []


_active_turns: dict[str, Any] = {}


def register_turn(session_id: str, turn: Any) -> None:
    _active_turns[session_id] = turn


def pop_turn(session_id: str) -> Any:
    return _active_turns.pop(session_id, None)


async def interrupt_session(session_id: str) -> bool:
    turn = _active_turns.get(session_id)
    if turn is None:
        return False
    interrupt = getattr(turn, "interrupt", None)
    if interrupt is None:
        return False
    result = interrupt()
    if hasattr(result, "__await__"):
        await result
    return True


def lookup_api_key(user) -> str:
    configured = os.environ.get("WHARTTEST_API_KEY", "").strip()
    if configured:
        return configured
    if user is None:
        return ""
    from django.utils import timezone
    from django.db.models import Q
    from api_keys.models import APIKey

    key = (
        APIKey.objects.filter(user=user, is_active=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("-created_at")
        .values_list("key", flat=True)
        .first()
    )
    return key or ""


def run_codex_prompt(project_id: int, goal: str, workspace_key: str, api_key: str = "") -> dict[str, str]:
    """同步执行一条 Codex 回合，供 Celery 任务实现测试。"""
    from openai_codex import ApprovalMode, Codex, Sandbox

    workspace = workspace_for("tasks", workspace_key)
    (workspace / "context" / "goal.md").write_text(goal, encoding="utf-8")
    auth = load_local_codex_auth()
    config = build_codex_config(workspace)
    config.env = codex_child_env(api_key, auth)
    with Codex(config) as codex:
        ensure_api_key_login(codex, auth)
        thread = codex.thread_start(
            cwd=str(workspace),
            sandbox=Sandbox.workspace_write,
            approval_mode=ApprovalMode.auto_review,
            developer_instructions=developer_instructions(project_id, goal),
            **thread_model_kwargs(auth),
        )
        result = thread.run(goal, cwd=str(workspace), source="wharttest_task")
    final_response = result.final_response or ""
    (workspace / "output" / "last-message.md").write_text(final_response, encoding="utf-8")
    return {
        "thread_id": str(getattr(thread, "id", "") or ""),
        "final_response": final_response,
        "workspace": str(workspace),
    }


async def stream_codex_turn(
    *,
    user,
    project,
    session_id: str,
    message: str,
    create_sse_data,
) -> AsyncIterator[str]:
    from asgiref.sync import sync_to_async
    from openai_codex import ApprovalMode, AsyncCodex, Sandbox

    from langgraph_integration.models import ChatMessage, ChatSession
    from .stop_signal import clear_stop_signal, should_stop

    workspace = workspace_for("sessions", session_id)
    title = f"新对话 - {message[:30]}"
    chat_session, _created = await sync_to_async(ChatSession.objects.get_or_create)(
        session_id=session_id,
        defaults={"user": user, "project": project, "title": title},
    )
    yield create_sse_data({
        "type": "start",
        "session_id": session_id,
        "thread_id": load_thread_id(session_id),
        "project_id": str(project.id),
        "display_message": message,
        "mode": "codex",
        "created_at": chat_session.created_at.isoformat() if chat_session.created_at else None,
    })

    await sync_to_async(ChatMessage.objects.create)(
        session=chat_session,
        user=user,
        message_id=f"codex-human-{uuid.uuid4().hex}",
        role="human",
        content=message,
    )

    api_key = await sync_to_async(lookup_api_key)(user)
    instructions = developer_instructions(project.id, message)
    assistant_parts: list[str] = []
    step_count = 0

    try:
        auth = load_local_codex_auth()
        config = build_codex_config(workspace)
        config.env = codex_child_env(api_key, auth)
        model_kwargs = thread_model_kwargs(auth)
        async with AsyncCodex(config) as codex:
            login_result = ensure_api_key_login(codex, auth)
            if hasattr(login_result, "__await__"):
                await login_result
            existing = load_thread_id(session_id)
            if existing:
                thread = await codex.thread_resume(
                    existing,
                    cwd=str(workspace),
                    sandbox=Sandbox.workspace_write,
                    developer_instructions=instructions,
                    **model_kwargs,
                )
            else:
                thread = await codex.thread_start(
                    cwd=str(workspace),
                    sandbox=Sandbox.workspace_write,
                    approval_mode=ApprovalMode.auto_review,
                    developer_instructions=instructions,
                    **model_kwargs,
                )
                save_thread_id(session_id, thread.id)
            turn = await thread.turn(message, cwd=str(workspace), source="wharttest_chat")
            register_turn(session_id, turn)
            try:
                async for notification in turn.stream():
                    if should_stop(session_id):
                        await turn.interrupt()
                        yield create_sse_data({"type": "stopped", "session_id": session_id})
                        break
                    failed = False
                    for event in notification_events(notification):
                        if event.get("type") == "stream":
                            assistant_parts.append(event.get("data") or "")
                        elif event.get("type") == "agent_message" and not assistant_parts:
                            assistant_parts.append(event.get("data") or "")
                            event = {"type": "stream", "data": event.get("data") or ""}
                        elif event.get("type") == "agent_message":
                            continue
                        if event.get("type") == "step_start":
                            step_count += 1
                        if event.get("type") == "error":
                            failed = True
                        yield create_sse_data(event)
                    if failed:
                        return
            finally:
                pop_turn(session_id)
    except Exception as exc:
        logger.exception("Codex 回合失败 session=%s", session_id)
        yield create_sse_data({"type": "error", "message": str(exc)})
        return
    finally:
        clear_stop_signal(session_id)

    final_text = "".join(assistant_parts).strip()
    if final_text:
        await sync_to_async(ChatMessage.objects.create)(
            session=chat_session,
            user=user,
            message_id=f"codex-ai-{uuid.uuid4().hex}",
            role="ai",
            content=final_text,
        )
        (workspace / "output" / "last-message.md").write_text(final_text, encoding="utf-8")
    yield create_sse_data({
        "type": "complete",
        "total_steps": step_count,
        "mode": "codex",
        "thread_id": load_thread_id(session_id),
    })
