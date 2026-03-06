import json
import os
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from cryptography.fernet import Fernet

from customer_portal.models import (
    CustomerAuthToken,
    CustomerModelProviderProfile,
    CustomerProfile,
)
from customer_portal.security import encrypt_api_key


User = get_user_model()
os.environ.setdefault("PORTAL_PROVIDER_SECRET", Fernet.generate_key().decode("utf-8"))


def _dummy_orchestrator_output(text="ok"):
    return SimpleNamespace(
        final_response=text,
        intent=SimpleNamespace(value="GENERAL"),
        risk_level=SimpleNamespace(value="LOW"),
        need_human=False,
        ui_action=None,
        form=None,
        confirm_required=False,
        pending_action=None,
        model_dump=lambda mode="json": {},
    )


class PortalLlmProfileApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800110021", password="12345678")
        self.user2 = User.objects.create_user(username="13800110022", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13800110021", display_name="A")
        CustomerProfile.objects.create(user=self.user2, phone="13800110022", display_name="B")
        self.token = CustomerAuthToken.rotate_token(self.user).token
        self.token2 = CustomerAuthToken.rotate_token(self.user2).token
        self.headers = {"HTTP_AUTHORIZATION": f"Token {self.token}"}
        self.headers2 = {"HTTP_AUTHORIZATION": f"Token {self.token2}"}

    def test_profile_crud_activate_delete(self):
        create_payload = {
            "name": "我的魔搭",
            "provider_type": "OPENAI_COMPAT",
            "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-test-first",
            "model_name": "qwen-plus",
        }
        r1 = self.client.post(
            "/api/portal/llm-profiles",
            data=json.dumps(create_payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r1.status_code, 201)
        data1 = (r1.json() or {}).get("data") or {}
        profile1_id = data1.get("id")
        self.assertTrue(profile1_id)
        self.assertTrue(data1.get("is_active"))

        row1 = CustomerModelProviderProfile.objects.get(id=profile1_id)
        self.assertNotEqual(row1.api_key_ciphertext, "sk-test-first")
        self.assertIn("****", row1.api_key_masked)

        r2 = self.client.post(
            "/api/portal/llm-profiles",
            data=json.dumps(
                {
                    "name": "备用配置",
                    "provider_type": "OPENAI_COMPAT",
                    "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-test-second",
                    "model_name": "qwen2.5-7b-instruct",
                    "is_active": False,
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(r2.status_code, 201)
        profile2_id = ((r2.json() or {}).get("data") or {}).get("id")
        self.assertTrue(profile2_id)

        r3 = self.client.post(f"/api/portal/llm-profiles/{profile2_id}/activate", **self.headers)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(CustomerModelProviderProfile.objects.get(id=profile2_id).is_active, True)
        self.assertEqual(CustomerModelProviderProfile.objects.get(id=profile1_id).is_active, False)

        r4 = self.client.get("/api/portal/llm-profiles", **self.headers)
        self.assertEqual(r4.status_code, 200)
        data4 = (r4.json() or {}).get("data") or {}
        self.assertEqual(data4.get("active_profile_id"), profile2_id)

        r5 = self.client.delete(f"/api/portal/llm-profiles/{profile2_id}", **self.headers)
        self.assertEqual(r5.status_code, 200)
        self.assertEqual(CustomerModelProviderProfile.objects.filter(id=profile2_id).exists(), False)
        self.assertEqual(CustomerModelProviderProfile.objects.get(id=profile1_id).is_active, True)

    def test_create_profile_reuses_existing_key_when_api_key_empty(self):
        first = self.client.post(
            "/api/portal/llm-profiles",
            data=json.dumps(
                {
                    "name": "主配置",
                    "provider_type": "OPENAI_COMPAT",
                    "api_base_url": "https://api-inference.modelscope.cn/v1",
                    "api_key": "sk-reuse-source",
                    "model_name": "Qwen/Qwen2.5-7B-Instruct",
                    "is_active": True,
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(first.status_code, 201)
        first_id = ((first.json() or {}).get("data") or {}).get("id")
        first_row = CustomerModelProviderProfile.objects.get(id=first_id)

        second = self.client.post(
            "/api/portal/llm-profiles",
            data=json.dumps(
                {
                    "name": "同密钥模型",
                    "provider_type": "OPENAI_COMPAT",
                    "api_base_url": "https://api-inference.modelscope.cn/v1",
                    "api_key": "",
                    "model_name": "ZhipuAI/GLM-5",
                    "is_active": False,
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(second.status_code, 201)
        second_id = ((second.json() or {}).get("data") or {}).get("id")
        second_row = CustomerModelProviderProfile.objects.get(id=second_id)

        self.assertEqual(first_row.api_key_ciphertext, second_row.api_key_ciphertext)
        self.assertEqual(first_row.api_key_masked, second_row.api_key_masked)

    def test_create_profile_without_key_fails_when_no_reusable_key(self):
        resp = self.client.post(
            "/api/portal/llm-profiles",
            data=json.dumps(
                {
                    "name": "空密钥",
                    "provider_type": "OPENAI_COMPAT",
                    "api_base_url": "https://api-inference.modelscope.cn/v1",
                    "api_key": "",
                    "model_name": "Qwen/Qwen2.5-7B-Instruct",
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            (((resp.json() or {}).get("error") or {}).get("code")),
            "PROVIDER_CONFIG_INVALID",
        )

    def test_profile_forbidden_between_users(self):
        own = CustomerModelProviderProfile.objects.create(
            user=self.user,
            name="only-me",
            provider_type="OPENAI_COMPAT",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            api_key_ciphertext=encrypt_api_key("sk-only"),
            api_key_masked="sk-****only",
            is_active=True,
        )
        r = self.client.put(
            f"/api/portal/llm-profiles/{own.id}",
            data=json.dumps({"name": "hack"}),
            content_type="application/json",
            **self.headers2,
        )
        self.assertEqual(r.status_code, 403)
        payload = r.json() or {}
        self.assertEqual(((payload.get("error") or {}).get("code")), "PROVIDER_PROFILE_FORBIDDEN")

    @mock.patch("customer_portal.views._fetch_models_by_profile", side_effect=Exception("upstream down"))
    def test_models_and_validate_error_codes(self, _):
        profile = CustomerModelProviderProfile.objects.create(
            user=self.user,
            name="my-profile",
            provider_type="OPENAI_COMPAT",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            api_key_ciphertext=encrypt_api_key("sk-only"),
            api_key_masked="sk-****only",
            is_active=True,
        )
        models_resp = self.client.get(f"/api/portal/llm-profiles/{profile.id}/models", **self.headers)
        self.assertEqual(models_resp.status_code, 502)
        self.assertEqual(
            (((models_resp.json() or {}).get("error") or {}).get("code")),
            "PROVIDER_MODELS_UNAVAILABLE",
        )

        validate_resp = self.client.post(f"/api/portal/llm-profiles/{profile.id}/validate", **self.headers)
        self.assertEqual(validate_resp.status_code, 502)
        self.assertEqual(
            (((validate_resp.json() or {}).get("error") or {}).get("code")),
            "PROVIDER_VALIDATE_FAILED",
        )


class PortalChatProviderProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="13800110023", password="12345678")
        CustomerProfile.objects.create(user=self.user, phone="13800110023", display_name="C")
        self.token = CustomerAuthToken.rotate_token(self.user).token
        self.headers = {"HTTP_AUTHORIZATION": f"Token {self.token}"}

    @mock.patch("core.views.run_orchestrator")
    def test_chat_injects_explicit_provider_profile(self, mock_run_orchestrator):
        profile = CustomerModelProviderProfile.objects.create(
            user=self.user,
            name="显式配置",
            provider_type="OPENAI_COMPAT",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            api_key_ciphertext=encrypt_api_key("sk-profile-explicit"),
            api_key_masked="sk-****icit",
            is_active=True,
        )
        mock_run_orchestrator.return_value = _dummy_orchestrator_output("ok")
        resp = self.client.post(
            "/api/chat",
            data=json.dumps(
                {
                    "message": "你好",
                    "portal_mode": True,
                    "model_provider": "OLLAMA",
                    "provider_profile_id": profile.id,
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        kwargs = mock_run_orchestrator.call_args.kwargs
        provider_config = kwargs.get("provider_config") or {}
        api_keys = kwargs.get("api_keys") or {}
        runtime_context = kwargs.get("runtime_context") or {}

        self.assertEqual(provider_config.get("provider_type"), "OPENAI_COMPAT")
        self.assertEqual(provider_config.get("model"), "qwen-plus")
        self.assertEqual(provider_config.get("base_url"), "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(api_keys.get("openai_api_key"), "sk-profile-explicit")
        self.assertEqual((runtime_context.get("portal_provider_profile") or {}).get("id"), profile.id)
        self.assertNotIn("sk-profile-explicit", str(runtime_context))

    @mock.patch("core.views.run_orchestrator")
    def test_chat_uses_active_profile_when_id_missing(self, mock_run_orchestrator):
        CustomerModelProviderProfile.objects.create(
            user=self.user,
            name="active-one",
            provider_type="OPENAI_COMPAT",
            api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen2.5-7b-instruct",
            api_key_ciphertext=encrypt_api_key("sk-profile-active"),
            api_key_masked="sk-****ctive",
            is_active=True,
        )
        mock_run_orchestrator.return_value = _dummy_orchestrator_output("ok")
        resp = self.client.post(
            "/api/chat",
            data=json.dumps(
                {
                    "message": "查一下订单",
                    "portal_mode": True,
                    "model_provider": "OLLAMA",
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        kwargs = mock_run_orchestrator.call_args.kwargs
        provider_config = kwargs.get("provider_config") or {}
        api_keys = kwargs.get("api_keys") or {}
        self.assertEqual(provider_config.get("provider_type"), "OPENAI_COMPAT")
        self.assertEqual(provider_config.get("model"), "qwen2.5-7b-instruct")
        self.assertEqual(api_keys.get("openai_api_key"), "sk-profile-active")
