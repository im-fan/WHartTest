"""全站只有一条激活配置。模型走 ChatOpenAI，Codex 走本机 CLI。"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class NoActiveConfig(RuntimeError):
    """没有可用的激活配置。"""


def _active_config():
    try:
        from django.apps import apps
        from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured
    except ImportError:
        return None
    try:
        if not apps.ready:
            return None
    except (AppRegistryNotReady, ImproperlyConfigured):
        return None
    from langgraph_integration.models import LLMConfig

    return LLMConfig.objects.filter(is_active=True).first()


def active_provider() -> str:
    config = _active_config()
    if config is not None:
        return config.provider
    return os.environ.get("AGENT_RUNTIME", "codex").strip().lower() or "codex"


def get_active_config():
    config = _active_config()
    if config is None:
        raise NoActiveConfig("没有激活的 LLM 配置")
    return config


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def messages_to_prompt(messages) -> tuple[str, str]:
    system_parts = []
    user_parts = []
    for message in messages or []:
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "user")
            content = _content_text(message.get("content"))
        else:
            role = str(getattr(message, "type", "") or message.__class__.__name__)
            content = _content_text(getattr(message, "content", ""))
        role = role.lower()
        if role in {"system", "systemmessage"}:
            system_parts.append(content)
        elif role in {"human", "user", "humanmessage"}:
            user_parts.append(content)
        elif content:
            user_parts.append(f"{role}: {content}")
    return "\n\n".join(part for part in system_parts if part), "\n\n".join(part for part in user_parts if part)


class CompletionResult:
    def __init__(self, content: str):
        self.content = content


class ActiveRuntime:
    """对业务代码暴露 invoke()，内部按激活配置选择后端。"""

    def __init__(self, config, temperature: float = 0.7):
        self.config = config
        self.temperature = temperature
        self._llm = None

    @property
    def provider(self) -> str:
        if self.config is None:
            return active_provider()
        return self.config.provider

    def invoke(self, messages):
        if self.provider == "codex":
            system, prompt = messages_to_prompt(messages)
            return CompletionResult(codex_complete(prompt, system=system))
        if self._llm is None:
            from langgraph_integration.views import create_llm_instance

            self._llm = create_llm_instance(self.config, temperature=self.temperature)
        return self._llm.invoke(messages)


def get_active_runtime(temperature: float = 0.7) -> ActiveRuntime:
    config = _active_config()
    if config is None and active_provider() != "codex":
        raise NoActiveConfig("没有激活的 LLM 配置")
    return ActiveRuntime(config, temperature=temperature)


def complete(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = get_active_runtime().invoke(messages)
    return _content_text(getattr(response, "content", response))


def codex_complete(prompt: str, system: str = "", timeout_s: int = 20) -> str:
    from orchestrator_integration.codex_runtime import run_codex_completion

    return run_codex_completion(prompt, system=system, timeout_s=timeout_s)
