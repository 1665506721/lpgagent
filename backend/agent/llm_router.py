import json
import os


class LLMRouter:
    def __init__(self, provider, api_keys=None, provider_config=None):
        self.provider = provider
        self.api_keys = api_keys or {}
        self.provider_config = provider_config or {}

    def _resolve_provider(self):
        # 中文注释：优先使用请求指定的 provider，未指定时回退环境变量
        provider = (
            self.provider_config.get("provider_type")
            or self.provider
            or os.getenv("MODEL_PROVIDER")
            or "OLLAMA"
        ).upper()
        if provider == "LOCAL":
            raise ValueError("MODEL_PROVIDER=LOCAL 已停用，请改用 OLLAMA")
        if provider in {"CUSTOM", "OPENAI_COMPAT"}:
            return "OPENAI_COMPAT"
        if provider not in {"OLLAMA", "OPENAI", "ANTHROPIC", "OPENAI_COMPAT"}:
            provider = "OLLAMA"
        return provider

    def _build_ollama(self):
        # 中文注释：构建本地 Ollama 客户端，使用环境变量指定模型
        from langchain_ollama import ChatOllama

        base_url = self.provider_config.get("base_url") or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        model = self.provider_config.get("model") or os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")
        return ChatOllama(
            base_url=base_url,
            model=model,
            temperature=0.2,
            num_predict=512,
        )

    def _get_openai_key(self):
        return self.api_keys.get("openai_api_key") or os.getenv("OPENAI_API_KEY")

    def _get_anthropic_key(self):
        return self.api_keys.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")

    def _build_openai(self, model=None, base_url=None, api_key=None):
        # 中文注释：仅在选择 OPENAI 时惰性加载并校验 API Key
        api_key = api_key or self._get_openai_key()
        if not api_key:
            raise ValueError("OPENAI_API_KEY 未配置，无法使用 OPENAI provider")
        os.environ["OPENAI_API_KEY"] = api_key
        if base_url:
            os.environ["OPENAI_API_BASE"] = base_url
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
            temperature=0.2,
            max_tokens=512,
            timeout=20,
            max_retries=1,
        )

    def _build_anthropic(self, model=None, api_key=None):
        # 中文注释：仅在选择 ANTHROPIC 时惰性加载并校验 API Key
        api_key = api_key or self._get_anthropic_key()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 未配置，无法使用 ANTHROPIC provider")
        os.environ["ANTHROPIC_API_KEY"] = api_key
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or os.getenv("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20240620",
            temperature=0.2,
            max_tokens=512,
        )

    def get_llm(self):
        # 中文注释：统一对外返回 LangChain 可调用的 LLM 实例
        provider = self._resolve_provider()
        if provider == "OLLAMA":
            return LLMTextWrapper(self._build_ollama())
        if provider == "OPENAI":
            return LLMTextWrapper(
                self._build_openai(
                    model=self.provider_config.get("model"),
                    base_url=self.provider_config.get("base_url"),
                    api_key=self.api_keys.get("openai_api_key"),
                )
            )
        if provider == "OPENAI_COMPAT":
            return LLMTextWrapper(
                self._build_openai(
                    model=self.provider_config.get("model"),
                    base_url=self.provider_config.get("base_url"),
                    api_key=self.api_keys.get("openai_api_key"),
                )
            )
        if provider == "ANTHROPIC":
            return LLMTextWrapper(
                self._build_anthropic(
                    model=self.provider_config.get("model"),
                    api_key=self.api_keys.get("anthropic_api_key"),
                )
            )
        raise ValueError(f"Unsupported provider: {provider}")


def get_provider_status():
    # 中文注释：健康检查只验证配置是否完整，不实际调用模型
    provider = (os.getenv("MODEL_PROVIDER") or "OLLAMA").upper()
    if provider not in {"OLLAMA", "OPENAI", "ANTHROPIC", "LOCAL"}:
        provider = "OLLAMA"
    if provider == "OPENAI" and not os.getenv("OPENAI_API_KEY"):
        return {"provider": provider, "ok": False, "error": "OPENAI_API_KEY 未配置"}
    if provider == "ANTHROPIC" and not os.getenv("ANTHROPIC_API_KEY"):
        return {"provider": provider, "ok": False, "error": "ANTHROPIC_API_KEY 未配置"}
    if provider == "LOCAL":
        return {"provider": provider, "ok": False, "error": "MODEL_PROVIDER=LOCAL 已停用"}
    return {"provider": provider, "ok": True, "error": None}


def get_language_guard():
    # 中文注释：统一提供中文输出约束，避免 LLM 输出英文说明
    return "请只用中文回答，避免英文或中英混杂。"


class LLMTextWrapper:
    # 中文注释：包装 LLM 输出为纯文本，避免上层解析失败
    def __init__(self, inner):
        self._inner = inner

    def invoke(self, messages):
        try:
            response = self._inner.invoke(messages)
        except Exception as exc:
            raise ValueError(f"模型调用失败：{exc}")
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception as exc:
            raise ValueError(f"模型输出不是文本：{exc}")
