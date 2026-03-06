import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.llm_router import get_provider_status
from agent.orchestrator import run_orchestrator
from core.models import (
    AgentEvent,
    AgentRun,
    MaintenanceRequest,
    Order,
    Ticket,
    UserProfile,
)
from core.serializers import AgentRunListSerializer, AgentRunSerializer

try:
    from customer_portal.auth import get_authenticated_user as get_portal_authenticated_user
    from customer_portal.models import (
        CustomerChatMessage,
        CustomerChatPreference,
        CustomerConversationMemory,
        CustomerModelProviderProfile,
    )
    from customer_portal.security import decrypt_api_key
except Exception:  # pragma: no cover - portal app import fallback
    get_portal_authenticated_user = None
    CustomerChatMessage = None
    CustomerChatPreference = None
    CustomerConversationMemory = None
    CustomerModelProviderProfile = None
    decrypt_api_key = None


def _infer_tone_style(message, current_style):
    text = (message or "").strip()
    if not text:
        return current_style or "neutral"
    warm_hits = ["请", "麻烦", "谢谢", "辛苦", "拜托"]
    direct_hits = ["快点", "马上", "立刻", "赶紧", "别废话"]
    if any(token in text for token in direct_hits):
        return "direct"
    if any(token in text for token in warm_hits):
        return "warm"
    if len(text) <= 8:
        return "direct"
    return current_style or "neutral"


def _probe_ollama_reachable(base_url):
    if "test" in sys.argv:
        return True, None, (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    target = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    tags_url = f"{target}/api/tags"
    try:
        req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2):
            return True, None, target
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return False, str(exc), target


def _parse_portal_rag_config(request_data):
    cfg = request_data.get("portal_rag_config")
    if not isinstance(cfg, dict):
        return None

    def _to_int(value, fallback, low, high):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(low, min(high, parsed))

    def _to_float(value, fallback, low, high):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(low, min(high, parsed))

    enable_rewrite = cfg.get("enable_rewrite")
    if isinstance(enable_rewrite, str):
        enable_rewrite = enable_rewrite.lower() in {"1", "true", "yes", "on"}
    if not isinstance(enable_rewrite, bool):
        enable_rewrite = True

    return {
        "top_k": _to_int(cfg.get("top_k"), 4, 1, 8),
        "min_score": _to_float(cfg.get("min_score"), 0.32, 0.0, 1.0),
        "min_hits": _to_int(cfg.get("min_hits"), 1, 1, 5),
        "max_bullets": _to_int(cfg.get("max_bullets"), 4, 1, 8),
        "enable_rewrite": enable_rewrite,
    }


def _get_model_provider(request_data):
    provider_type = (
        request_data.get("provider_type")
        or request_data.get("model_provider")
        or os.getenv("MODEL_PROVIDER")
        or "OLLAMA"
    )
    provider_type = provider_type.upper()
    if provider_type in {AgentRun.PROVIDER_OPENAI, "OPENAI_COMPAT", "CUSTOM"}:
        return AgentRun.PROVIDER_OPENAI
    if provider_type == AgentRun.PROVIDER_ANTHROPIC:
        return AgentRun.PROVIDER_ANTHROPIC
    # 中文注释：本地/兼容接口统一落库为 LOCAL，避免违反模型枚举约束
    return AgentRun.PROVIDER_LOCAL


def _get_api_keys(request_data, provider_type=None):
    # 中文注释：仅透传用户临时输入的 API Key，不落库
    api_keys = {}
    openai_key = request_data.get("openai_api_key")
    if openai_key:
        api_keys["openai_api_key"] = openai_key
    anthropic_key = request_data.get("anthropic_api_key")
    if anthropic_key:
        api_keys["anthropic_api_key"] = anthropic_key
    provider_key = request_data.get("provider_api_key")
    provider_type = (provider_type or "").upper()
    if provider_key and provider_type in {"OPENAI", "OPENAI_COMPAT", "CUSTOM"}:
        api_keys.setdefault("openai_api_key", provider_key)
    if provider_key and provider_type == "ANTHROPIC":
        api_keys.setdefault("anthropic_api_key", provider_key)
    return api_keys


def _get_provider_config(request_data, model_provider):
    # 中文注释：支持前端自定义模型配置
    provider_type = request_data.get("provider_type") or model_provider
    return {
        "provider_type": provider_type,
        "model": request_data.get("provider_model"),
        "base_url": request_data.get("provider_base_url"),
        "provider_name": request_data.get("provider_name"),
    }


def _parse_provider_profile_id(request_data):
    raw = request_data.get("provider_profile_id")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("provider_profile_id is invalid")


def _mask_base_url(base_url):
    value = (base_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        scheme = parsed.scheme or "https"
        host = parsed.hostname or ""
        path = parsed.path or ""
        return f"{scheme}://{host}{path}"
    except Exception:
        return value


def _resolve_portal_provider_profile(portal_user, request_data):
    if not portal_user or not CustomerModelProviderProfile:
        return None, None

    try:
        explicit_profile_id = _parse_provider_profile_id(request_data)
    except ValueError as exc:
        return None, {
            "code": "PROVIDER_CONFIG_INVALID",
            "message": str(exc),
            "status": status.HTTP_400_BAD_REQUEST,
        }

    profile_qs = CustomerModelProviderProfile.objects.filter(user=portal_user)
    if explicit_profile_id is not None:
        profile = profile_qs.filter(id=explicit_profile_id).first()
        if not profile:
            exists = CustomerModelProviderProfile.objects.filter(id=explicit_profile_id).exists()
            if exists:
                return None, {
                    "code": "PROVIDER_PROFILE_FORBIDDEN",
                    "message": "provider profile forbidden",
                    "status": status.HTTP_403_FORBIDDEN,
                }
            return None, {
                "code": "PROVIDER_PROFILE_NOT_FOUND",
                "message": "provider profile not found",
                "status": status.HTTP_404_NOT_FOUND,
            }
    else:
        profile = profile_qs.filter(is_active=True).order_by("-updated_at", "-id").first()
        if not profile:
            return None, None

    if not decrypt_api_key:
        return None, {
            "code": "ENCRYPTION_CONFIG_ERROR",
            "message": "provider decryptor unavailable",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }

    try:
        api_key = decrypt_api_key(profile.api_key_ciphertext)
    except Exception as exc:
        return None, {
            "code": "ENCRYPTION_CONFIG_ERROR",
            "message": "provider key decrypt failed",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "details": {"detail": str(exc)},
        }

    return (
        {
            "id": profile.id,
            "name": profile.name,
            "provider_type": profile.provider_type,
            "model": profile.model_name,
            "base_url": profile.api_base_url,
            "api_key": api_key,
        },
        None,
    )


def _get_or_create_user_profile(user_id):
    if not user_id:
        return None
    profile, _ = UserProfile.objects.get_or_create(
        id=user_id,
        defaults={"name": "Unknown"},
    )
    return profile


def _resolve_run(request_data, user_id, model_provider):
    portal_mode = bool(request_data.get("portal_mode"))
    stale_minutes = 30

    def _run_last_active_at(run_obj):
        if not run_obj:
            return None
        last_event = (
            AgentEvent.objects.filter(run=run_obj)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        return last_event or getattr(run_obj, "created_at", None)

    def _is_portal_run_stale(run_obj):
        if not portal_mode:
            return False
        last_active_at = _run_last_active_at(run_obj)
        if not last_active_at:
            return False
        return timezone.now() - last_active_at > timedelta(minutes=stale_minutes)

    force_new = bool(request_data.get("force_new_run"))
    run_id = request_data.get("run_id")
    if run_id and not force_new:
        run = AgentRun.objects.filter(id=run_id).first()
        if run and not _is_portal_run_stale(run):
            return run, False
    if portal_mode and user_id and not force_new:
        latest = AgentRun.objects.filter(user_id=user_id).order_by("-created_at").first()
        if latest and not _is_portal_run_stale(latest):
            return latest, False
    run = AgentRun.objects.create(
        user=_get_or_create_user_profile(user_id),
        model_provider=model_provider,
    )
    return run, True


def _next_step_index(run):
    current = (
        AgentEvent.objects.filter(run=run).aggregate(Max("step_index")).get("step_index__max")
    )
    return (current or 0) + 1


def _error_response(message, code, status_code, details=None):
    if details is None:
        details = {}
    return Response(
        {"error": message, "code": code, "details": details},
        status=status_code,
    )


def _tool_error_response(request_data, tool_name, message, code, reasons, status_code, details=None):
    if details is None:
        details = {}
    response_payload = {"error": message, "code": code, "details": details}
    _record_tool_event(
        request_data,
        tool_name,
        response_payload,
        policy_result={"allow": False, "reasons": reasons},
    )
    return Response(response_payload, status=status_code)


def _get_order_provider():
    # 中文注释：集中获取外部订单 provider，便于后续替换为真实 API
    from external.order_provider import get_order_provider

    return get_order_provider()


def _persist_portal_chat_message(user, role, content, run):
    if not user or not CustomerChatMessage:
        return
    text = (content or "").strip()
    if not text:
        return
    try:
        CustomerChatMessage.objects.create(
            user=user,
            role=role,
            content=text,
            run_id=run.id if run else None,
        )
    except Exception:
        # 中文注释：聊天落库失败不影响主流程响应。
        return


class ChatView(APIView):
    def post(self, request):
        message = request.data.get("message")
        if not message:
            user_id = request.data.get("user_id")
            model_provider = _get_model_provider(request.data)
            run = AgentRun.objects.create(
                user=_get_or_create_user_profile(user_id),
                model_provider=model_provider,
            )
            AgentEvent.objects.create(
                run=run,
                step_index=1,
                state=AgentEvent.STATE_ERROR,
                input_json={"message": message, "user_id": user_id},
                output_json={"error": "message is required", "code": "MISSING_PARAM"},
                policy_result={"allow": False, "reasons": ["missing_message"]},
                created_at=timezone.now(),
            )
            return _error_response(
                "message is required",
                "MISSING_PARAM",
                status.HTTP_400_BAD_REQUEST,
                details={"run_id": str(run.id)},
            )

        portal_user = None
        if get_portal_authenticated_user:
            try:
                portal_user = get_portal_authenticated_user(request)
            except Exception:
                portal_user = None

        user_id = request.data.get("user_id")
        if request.data.get("portal_mode") and portal_user and not user_id:
            user_id = portal_user.id
        model_provider = _get_model_provider(request.data)
        run, is_new_run = _resolve_run(request.data, user_id, model_provider)
        if is_new_run:
            AgentEvent.objects.create(
                run=run,
                step_index=1,
                state=AgentEvent.STATE_INIT,
                input_json={"message": message, "user_id": user_id},
                policy_result={"allow": True, "reasons": []},
            )
        else:
            AgentEvent.objects.create(
                run=run,
                step_index=_next_step_index(run),
                state=AgentEvent.STATE_INIT,
                input_json={"message": message, "user_id": user_id, "continued": True},
                policy_result={"allow": True, "reasons": ["continue_run"]},
            )

        try:
            if request.data.get("portal_mode") and portal_user:
                _persist_portal_chat_message(portal_user, "user", message, run)
            provider_config = _get_provider_config(request.data, model_provider)
            api_keys = _get_api_keys(request.data, provider_type=provider_config.get("provider_type"))
            selected_profile = None
            profile_degraded_reason = None
            if request.data.get("portal_mode") and portal_user:
                selected_profile, resolve_error = _resolve_portal_provider_profile(portal_user, request.data)
                if resolve_error:
                    explicit_profile_id = request.data.get("provider_profile_id")
                    can_degrade = (
                        resolve_error.get("code") == "ENCRYPTION_CONFIG_ERROR"
                        and explicit_profile_id in (None, "")
                    )
                    if can_degrade:
                        selected_profile = None
                        profile_degraded_reason = "provider_profile_decrypt_failed"
                    else:
                        return _error_response(
                            resolve_error.get("message") or "provider profile resolve failed",
                            resolve_error.get("code") or "PROVIDER_CONFIG_INVALID",
                            resolve_error.get("status") or status.HTTP_400_BAD_REQUEST,
                            details=resolve_error.get("details") or {},
                        )
                if selected_profile:
                    provider_config["provider_type"] = "OPENAI_COMPAT"
                    provider_config["model"] = selected_profile["model"]
                    provider_config["base_url"] = selected_profile["base_url"]
                    provider_config["provider_name"] = selected_profile["name"]
                    api_keys["openai_api_key"] = selected_profile["api_key"]
            runtime_context = {}
            if request.data.get("portal_mode"):
                runtime_context["portal_mode"] = True
                runtime_context["route_mode"] = request.data.get("route_mode") or "v2"
                runtime_context["write_allowed"] = bool(selected_profile)
                runtime_context["degraded_reason"] = (
                    None
                    if selected_profile
                    else (profile_degraded_reason or "no_cloud_profile")
                )
                runtime_context["portal_model_source"] = "cloud" if selected_profile else "none"
                rag_cfg = _parse_portal_rag_config(request.data)
                if rag_cfg:
                    runtime_context["portal_rag_config"] = rag_cfg
            if selected_profile:
                runtime_context["portal_provider_profile"] = {
                    "id": selected_profile["id"],
                    "provider_type": selected_profile["provider_type"],
                    "model": selected_profile["model"],
                    "base_url": _mask_base_url(selected_profile["base_url"]),
                }
            if portal_user:
                runtime_context["portal_user_id"] = portal_user.id
                runtime_context["portal_phone"] = portal_user.username
                runtime_context["disable_forms"] = True
                runtime_context["portal_tone_style"] = "neutral"
                if CustomerChatPreference:
                    try:
                        preference, _ = CustomerChatPreference.objects.get_or_create(
                            user=portal_user,
                            defaults={"tone_style": "neutral"},
                        )
                        inferred_style = _infer_tone_style(message, preference.tone_style)
                        if inferred_style != preference.tone_style:
                            preference.tone_style = inferred_style
                            preference.save(update_fields=["tone_style", "updated_at"])
                        runtime_context["portal_tone_style"] = preference.tone_style
                    except Exception:
                        runtime_context["portal_tone_style"] = "neutral"
                if CustomerConversationMemory:
                    try:
                        memory, _ = CustomerConversationMemory.objects.get_or_create(
                            user=portal_user,
                            defaults={"memory_json": {}},
                        )
                        runtime_context["portal_memory"] = memory.memory_json or {}
                    except Exception:
                        runtime_context["portal_memory"] = {}
            if runtime_context.get("portal_mode") and runtime_context.get("portal_user_id"):
                provider_type = (provider_config.get("provider_type") or "").upper()
                if provider_type in {"", "OLLAMA", "LOCAL"}:
                    reachable, probe_error, target_base = _probe_ollama_reachable(provider_config.get("base_url"))
                    runtime_context["portal_model_reachable"] = bool(reachable)
                    runtime_context["portal_model_probe_error"] = probe_error
                    runtime_context["portal_model_base_url"] = target_base
                    if not selected_profile:
                        runtime_context["portal_model_source"] = "local" if reachable else "none"
                        runtime_context["write_allowed"] = False
                        runtime_context["degraded_reason"] = (
                            "no_cloud_profile" if reachable else "local_model_unavailable"
                        )
                    if not reachable:
                        AgentEvent.objects.create(
                            run=run,
                            step_index=_next_step_index(run),
                            state=AgentEvent.STATE_PLANNING,
                            input_json={"message": message, "portal_mode": True},
                            output_json={
                                "route": "portal_mode_model_unavailable_degrade",
                                "provider": "OLLAMA",
                                "base_url": target_base,
                                "error": probe_error,
                            },
                            policy_result={"allow": True, "reasons": ["model_unavailable_degrade"]},
                            created_at=timezone.now(),
                        )
            output = run_orchestrator(
                run,
                message,
                user_id,
                model_provider,
                api_keys=api_keys,
                provider_config=provider_config,
                runtime_context=runtime_context or None,
            )
        except Exception as exc:
            AgentEvent.objects.create(
                run=run,
                step_index=_next_step_index(run),
                state=AgentEvent.STATE_ERROR,
                input_json={"message": message, "user_id": user_id},
                output_json={"error": str(exc), "code": "INTERNAL_ERROR"},
                policy_result={"allow": False, "reasons": ["internal_error"]},
                created_at=timezone.now(),
            )
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"run_id": str(run.id)},
            )

        fallback_event = (
            AgentEvent.objects.filter(run=run, state=AgentEvent.STATE_FALLBACK)
            .order_by("-id")
            .first()
        )
        if fallback_event:
            planning_event = (
                AgentEvent.objects.filter(run=run, state=AgentEvent.STATE_PLANNING)
                .order_by("-id")
                .first()
            )
            raw_output = None
            if planning_event and isinstance(planning_event.output_json, dict):
                raw_output = planning_event.output_json.get("raw_output")
            # 中文注释：只有模型返回了内容但解析失败时才返回 422，模型不可用则继续返回兜底响应
            if raw_output:
                details = {
                    "run_id": str(run.id),
                    "fallback": output.model_dump(mode="json"),
                }
                if isinstance(fallback_event.output_json, dict):
                    details["reason"] = fallback_event.output_json.get("reason")
                    details["detail"] = fallback_event.output_json.get("detail")
                return _error_response(
                    "LLM output validation failed",
                    "LLM_PARSE_FAILED",
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    details=details,
                )

        preview_events = (
            AgentEvent.objects.filter(
                run=run,
                state__in=[
                    AgentEvent.STATE_INIT,
                    AgentEvent.STATE_PLANNING,
                    AgentEvent.STATE_TOOL_EXEC,
                    AgentEvent.STATE_RESPOND,
                ],
            )
            .order_by("step_index", "id")
        )
        events_preview = [
            {
                "step_index": preview.step_index,
                "state": preview.state,
                "tool_name": preview.tool_name,
                "policy_result": preview.policy_result,
                "created_at": preview.created_at.isoformat(),
            }
            for preview in preview_events
        ]

        response_data = {
            "run_id": str(run.id),
            "final_response": output.final_response,
            "state": "DONE",
            "intent": output.intent.value,
            "risk_level": output.risk_level.value,
            "need_human": output.need_human,
            "events_preview": events_preview,
        }
        if getattr(output, "ui_action", None):
            response_data["ui_action"] = output.ui_action
            response_data["form"] = output.form
        if getattr(output, "confirm_required", False):
            response_data["confirm_required"] = True
        if getattr(output, "pending_action", None):
            response_data["pending_action"] = output.pending_action
        if getattr(output, "routing", None):
            response_data["routing"] = output.routing
        if request.data.get("portal_mode") and portal_user:
            _persist_portal_chat_message(portal_user, "assistant", output.final_response, run)
        return Response(response_data)


class RunDetailView(APIView):
    def get(self, request, run_id):
        try:
            run = AgentRun.objects.get(id=run_id)
        except AgentRun.DoesNotExist:
            return _error_response(
                "run not found",
                "NOT_FOUND",
                status.HTTP_404_NOT_FOUND,
                details={"run_id": str(run_id)},
            )

        try:
            serializer = AgentRunSerializer(run)
            events = serializer.data["events"]
            events.sort(key=lambda item: (item["step_index"], item["id"]))
            return Response(
                {
                    "run_id": str(run.id),
                    "created_at": run.created_at.isoformat(),
                    "model_provider": run.model_provider,
                    "events": events,
                }
            )
        except Exception as exc:
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"run_id": str(run_id), "detail": str(exc)},
            )


class RunsListView(APIView):
    def get(self, request):
        limit = request.query_params.get("limit", 20)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        try:
            runs = AgentRun.objects.order_by("-created_at")[:limit]
            serializer = AgentRunListSerializer(runs, many=True)
            return Response({"limit": limit, "items": serializer.data})
        except Exception as exc:
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )


class HealthView(APIView):
    def get(self, request):
        # 中文注释：健康检查用于快速判断依赖是否可用，任一子系统不可用则标记为 degraded
        db_status = {"ok": True, "error": None}
        try:
            AgentRun.objects.count()
        except Exception as exc:
            db_status = {"ok": False, "error": str(exc)}

        from knowledge_base.vector_store import get_kb_status

        # 中文注释：KB 未配置时返回 NOT_CONFIGURED，整体状态可降级为 degraded
        kb_status = get_kb_status()
        model_status = get_provider_status()

        overall_ok = db_status["ok"] and kb_status["ok"] and model_status["ok"]
        return Response(
            {
                "status": "ok" if overall_ok else "degraded",
                "db": db_status,
                "kb": kb_status,
                "model": model_status,
                "time": timezone.now().isoformat(),
            }
        )


class OllamaModelsView(APIView):
    def get(self, request):
        base_url = (
            (request.query_params.get("base_url") or "").strip()
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434"
        ).rstrip("/")
        tags_url = f"{base_url}/api/tags"
        fallback_model = os.getenv("OLLAMA_MODEL") or "deepseek-r1:8b"
        models = []
        reachable = False
        error_text = None
        try:
            req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                for item in payload.get("models", []):
                    name = item.get("name")
                    if isinstance(name, str) and name and name not in models:
                        models.append(name)
                reachable = True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            error_text = str(exc)

        if fallback_model not in models:
            models.insert(0, fallback_model)
        if not models:
            models = ["deepseek-r1:8b"]

        return Response(
            {
                "provider": "OLLAMA",
                "base_url": base_url,
                "models": models,
                "reachable": reachable,
                "error": error_text,
            }
        )


class OllamaWarmupView(APIView):
    def post(self, request):
        base_url = (
            (request.data.get("base_url") or "").strip()
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434"
        ).rstrip("/")
        model = (request.data.get("model") or "").strip() or (os.getenv("OLLAMA_MODEL") or "deepseek-r1:8b")
        payload = {
            "model": model,
            "prompt": "你好，请只回复：ok",
            "stream": False,
            "options": {"num_predict": 8},
            "keep_alive": "5m",
        }
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            return Response(
                {
                    "ok": False,
                    "provider": "OLLAMA",
                    "base_url": base_url,
                    "model": model,
                    "error": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "ok": True,
                "provider": "OLLAMA",
                "base_url": base_url,
                "model": model,
                "response": (result.get("response") or "").strip(),
            }
        )


class ExternalOrderDetailView(APIView):
    def get(self, request, order_id):
        provider = _get_order_provider()
        try:
            order = provider.get_order(order_id)
        except Exception as exc:
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        if not order:
            return _error_response(
                "order not found",
                "NOT_FOUND",
                status.HTTP_404_NOT_FOUND,
                details={"order_id": order_id},
            )
        return Response(order)


class ExternalOrderListView(APIView):
    def get(self, request):
        phone = request.query_params.get("phone")
        if not phone:
            return _error_response(
                "phone is required",
                "MISSING_PARAM",
                status.HTTP_400_BAD_REQUEST,
                details={"param": "phone"},
            )
        limit = request.query_params.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(50, limit))
        provider = _get_order_provider()
        try:
            items = provider.list_orders_by_phone(phone, limit=limit)
        except Exception as exc:
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        return Response({"phone": phone, "limit": limit, "items": items})


class ExternalOrderSeedView(APIView):
    def post(self, request):
        # 中文注释：仅用于演示，触发 mock 数据重建
        provider = _get_order_provider()
        try:
            items = provider.reseed()
        except Exception as exc:
            return _error_response(
                "internal error",
                "INTERNAL_ERROR",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        return Response({"count": len(items)})


class CreateOrderView(APIView):
    def post(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return _tool_error_response(
                request.data,
                "create_order",
                "user_id is required",
                "MISSING_PARAM",
                ["missing_user_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            quantity_value = request.data.get("quantity") or 1
            quantity = int(quantity_value)
        except (TypeError, ValueError):
            return _tool_error_response(
                request.data,
                "create_order",
                "quantity is invalid",
                "MISSING_PARAM",
                ["invalid_quantity"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            profile = _get_or_create_user_profile(user_id)
            order = Order.objects.create(
                user=profile,
                product_type=request.data.get("product_type", ""),
                quantity=quantity,
                address=request.data.get("address", ""),
                status=Order.STATUS_CREATED,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "create_order",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        response_payload = {
            "order_id": order.id,
            "status": order.status,
            "message": "Order created",
        }
        _record_tool_event(request.data, "create_order", response_payload)
        return Response(response_payload)


class QueryOrderView(APIView):
    def post(self, request):
        order_id = request.data.get("order_id")
        if not order_id:
            return _tool_error_response(
                request.data,
                "query_order",
                "order_id is required",
                "MISSING_PARAM",
                ["missing_order_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return _tool_error_response(
                request.data,
                "query_order",
                "order not found",
                "NOT_FOUND",
                ["order_not_found"],
                status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "query_order",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        response_payload = {
            "order_id": order.id,
            "status": order.status,
            "product_type": order.product_type,
            "quantity": order.quantity,
            "address": order.address,
            "created_at": order.created_at.isoformat(),
        }
        _record_tool_event(request.data, "query_order", response_payload)
        return Response(response_payload)


class ModifyOrderAddressView(APIView):
    def post(self, request):
        order_id = request.data.get("order_id")
        if not order_id:
            return _tool_error_response(
                request.data,
                "modify_order_address",
                "order_id is required",
                "MISSING_PARAM",
                ["missing_order_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        new_address = request.data.get("new_address")
        if not new_address:
            return _tool_error_response(
                request.data,
                "modify_order_address",
                "new_address is required",
                "MISSING_PARAM",
                ["missing_new_address"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return _tool_error_response(
                request.data,
                "modify_order_address",
                "order not found",
                "NOT_FOUND",
                ["order_not_found"],
                status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "modify_order_address",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        old_address = order.address
        order.address = new_address
        order.save(update_fields=["address", "updated_at"])
        response_payload = {
            "order_id": order.id,
            "old_address": old_address,
            "new_address": order.address,
            "status": order.status,
            "message": "Address updated",
        }
        _record_tool_event(request.data, "modify_order_address", response_payload)
        return Response(response_payload)


class CreateTicketView(APIView):
    def post(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return _tool_error_response(
                request.data,
                "create_ticket",
                "user_id is required",
                "MISSING_PARAM",
                ["missing_user_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            profile = _get_or_create_user_profile(user_id)
            order_id = request.data.get("order_id")
            order = Order.objects.filter(id=order_id).first()
            ticket = Ticket.objects.create(
                user=profile,
                order=order,
                category=request.data.get("category", Ticket.CATEGORY_OTHER),
                description=request.data.get("description", ""),
                status=Ticket.STATUS_OPEN,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "create_ticket",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        response_payload = {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "message": "Ticket created",
        }
        _record_tool_event(request.data, "create_ticket", response_payload)
        return Response(response_payload)


class QueryTicketView(APIView):
    def post(self, request):
        ticket_id = request.data.get("ticket_id")
        if not ticket_id:
            return _tool_error_response(
                request.data,
                "query_ticket",
                "ticket_id is required",
                "MISSING_PARAM",
                ["missing_ticket_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return _tool_error_response(
                request.data,
                "query_ticket",
                "ticket not found",
                "NOT_FOUND",
                ["ticket_not_found"],
                status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "query_ticket",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        response_payload = {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "category": ticket.category,
            "description": ticket.description,
            "created_at": ticket.created_at.isoformat(),
        }
        _record_tool_event(request.data, "query_ticket", response_payload)
        return Response(response_payload)


class CreateMaintenanceRequestView(APIView):
    def post(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return _tool_error_response(
                request.data,
                "create_maintenance_request",
                "user_id is required",
                "MISSING_PARAM",
                ["missing_user_id"],
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            profile = _get_or_create_user_profile(user_id)
            maintenance = MaintenanceRequest.objects.create(
                user=profile,
                issue=request.data.get("issue", ""),
                status=MaintenanceRequest.STATUS_OPEN,
            )
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "create_maintenance_request",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        response_payload = {
            "maintenance_id": maintenance.id,
            "status": maintenance.status,
            "message": "Maintenance request created",
        }
        _record_tool_event(request.data, "create_maintenance_request", response_payload)
        return Response(response_payload)


class SafetySearchView(APIView):
    def post(self, request):
        from knowledge_base.retriever import search_safety

        query = request.data.get("query", "")
        if not query:
            return _tool_error_response(
                request.data,
                "safety_search",
                "query is required",
                "MISSING_PARAM",
                ["missing_query"],
                status.HTTP_400_BAD_REQUEST,
            )
        top_k = request.data.get("top_k", 4)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 4

        try:
            results = search_safety(query, top_k=top_k)
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "safety_search",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )
        results = [
            {
                "doc_id": item.get("doc_id", ""),
                "title": item.get("title", ""),
                "bullets": item.get("bullets", []),
                "score": item.get("score", 0.0),
            }
            for item in results
        ]
        response_payload = {
            "query": query,
            "results": results,
        }
        _record_tool_event(request.data, "safety_search", response_payload)
        return Response(response_payload)


class KnowledgeBaseSearchView(APIView):
    def post(self, request):
        from knowledge_base.retriever import retrieve_by_domain

        domain = (request.data.get("domain") or "").strip()
        if not domain:
            return _tool_error_response(
                request.data,
                "kb_search",
                "domain is required",
                "MISSING_PARAM",
                ["missing_domain"],
                status.HTTP_400_BAD_REQUEST,
            )
        if domain not in {"safety", "biz"}:
            return _tool_error_response(
                request.data,
                "kb_search",
                "domain is invalid",
                "MISSING_PARAM",
                ["invalid_domain"],
                status.HTTP_400_BAD_REQUEST,
            )

        query = request.data.get("query", "")
        if not query:
            return _tool_error_response(
                request.data,
                "kb_search",
                "query is required",
                "MISSING_PARAM",
                ["missing_query"],
                status.HTTP_400_BAD_REQUEST,
            )

        top_k = request.data.get("top_k", 4)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 4

        try:
            results = retrieve_by_domain(domain, query, top_k=top_k)
        except Exception as exc:
            return _tool_error_response(
                request.data,
                "kb_search",
                "internal error",
                "INTERNAL_ERROR",
                ["internal_error"],
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"detail": str(exc)},
            )

        response_payload = {
            "domain": domain,
            "query": query,
            "results": results,
        }
        _record_tool_event(request.data, "kb_search", response_payload)
        return Response(response_payload)


def _record_tool_event(request_data, tool_name, tool_output, policy_result=None):
    run_id = request_data.get("run_id")
    user_id = request_data.get("user_id")
    if run_id:
        run = AgentRun.objects.filter(id=run_id).first()
    else:
        run = None
    if not run:
        run = AgentRun.objects.create(
            user=_get_or_create_user_profile(user_id),
            model_provider=os.getenv("MODEL_PROVIDER", AgentRun.PROVIDER_OPENAI),
        )
    if policy_result is None:
        policy_result = {"allow": True, "reasons": []}
    AgentEvent.objects.create(
        run=run,
        step_index=_next_step_index(run),
        state=AgentEvent.STATE_TOOL_EXEC,
        tool_name=tool_name,
        tool_input=request_data,
        tool_output=tool_output,
        policy_result=policy_result,
        created_at=timezone.now(),
    )
