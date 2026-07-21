import hashlib
import json
import os
import tempfile
from datetime import timedelta

from django.apps import apps
from django.test import TestCase
from django.utils import timezone


class ApiKeyAuthTest(TestCase):
    def setUp(self):
        super().setUp()
        # Ensure legacy single-token auth is disabled for this test so we can
        # verify DB-managed API keys.
        os.environ.pop("BEACON_OPEN_API_TOKEN", None)
        self.addCleanup(os.environ.pop, "BEACON_OPEN_API_TOKEN", None)

        os.environ["BEACON_API_KEY_PEPPER"] = "pepper-test"
        self.addCleanup(os.environ.pop, "BEACON_API_KEY_PEPPER", None)

    def _hash(self, token: str) -> str:
        pepper = str(os.environ.get("BEACON_API_KEY_PEPPER") or "")
        return hashlib.sha256((pepper + token).encode("utf-8")).hexdigest()

    def test_db_api_key_allows_ops_healthz(self):
        """
        Roadmap: API Key 管理（创建/轮换/吊销/过期/作用域）

        最小闭环：
        - token 存 DB（仅存 hash，不存明文）
        - /healthz 这类 ops 端点可用 DB key 授权
        """
        try:
            ApiKey = apps.get_model("app", "ApiKey")
        except LookupError:
            self.fail("ApiKey model is missing (expected app.ApiKey)")

        token = "k_test_ops_1"
        ApiKey.objects.create(
            name="k1",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_allows_open_ops_health_alias(self):
        """
        /open/ops/* endpoints are OpenAPI-style aliases for ops probes and should
        be authorized by `ops`-scoped keys (not `openapi`).
        """
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_alias_1"
        ApiKey.objects.create(
            name="k-ops-alias",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/open/ops/health",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_list_item_csv_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_list_item_csv_1"
        ApiKey.objects.create(
            name="k-ops-list-item-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops,openapi"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_list_item_pipe_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_list_item_pipe_1"
        ApiKey.objects.create(
            name="k-ops-list-item-pipe",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops|openapi"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_list_item_whitespace_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_list_item_space_1"
        ApiKey.objects.create(
            name="k-ops-list-item-space",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops openapi"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_list_item_newline_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_list_item_newline_1"
        ApiKey.objects.create(
            name="k-ops-list-item-newline",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops\nopenapi"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_scope_matching_is_case_insensitive(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_upper_1"
        ApiKey.objects.create(
            name="k-ops-upper",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["OPS"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_csv_scope_string_compat(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_csv_1"
        ApiKey.objects.create(
            name="k-ops-csv",
            token_hash=self._hash(token),
            scopes_json="ops, openapi",
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_csv_scope_string_with_quotes(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_csv_quote_1"
        ApiKey.objects.create(
            name="k-ops-csv-quote",
            token_hash=self._hash(token),
            scopes_json='"ops", "openapi"',
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_whitespace_scope_string_compat(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_space_1"
        ApiKey.objects.create(
            name="k-ops-space",
            token_hash=self._hash(token),
            scopes_json="ops openapi",
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_semicolon_scope_string_compat(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_semicolon_1"
        ApiKey.objects.create(
            name="k-ops-semicolon",
            token_hash=self._hash(token),
            scopes_json="ops;openapi",
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_pipe_scope_string_compat(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_pipe_1"
        ApiKey.objects.create(
            name="k-ops-pipe",
            token_hash=self._hash(token),
            scopes_json="ops|openapi",
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_quoted_csv_scope_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_quoted_csv_1"
        ApiKey.objects.create(
            name="k-ops-top-quoted-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps('"ops, openapi"', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_nested_quoted_semicolon_scope_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_nested_semicolon_1"
        ApiKey.objects.create(
            name="k-ops-top-nested-semicolon",
            token_hash=self._hash(token),
            scopes_json=json.dumps('"ops;openapi"', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_nested_quoted_whitespace_scope_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_nested_space_1"
        ApiKey.objects.create(
            name="k-ops-top-nested-space",
            token_hash=self._hash(token),
            scopes_json=json.dumps('"ops openapi"', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_json_array_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-top-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps('["ops","openapi"]', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_single_quoted_json_array_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_single_quote_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-top-single-quote-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps("['ops','openapi']", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_tuple_scope_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_tuple_scope_1"
        ApiKey.objects.create(
            name="k-ops-top-tuple-scope",
            token_hash=self._hash(token),
            scopes_json=json.dumps("('ops','openapi')", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_nested_quoted_json_array_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_nested_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-top-nested-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps('"[\\"ops\\",\\"openapi\\"]"', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_json_object_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_json_obj_1"
        ApiKey.objects.create(
            name="k-ops-top-json-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps('{"ops":true,"openapi":false}', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_single_quoted_json_object_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_single_quote_json_obj_1"
        ApiKey.objects.create(
            name="k-ops-top-single-quote-json-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps("{'ops': True, 'openapi': False}", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_single_quoted_json_object_with_scopes_list_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_single_quote_json_obj_scopes_list_1"
        ApiKey.objects.create(
            name="k-ops-top-single-quote-json-obj-scopes-list",
            token_hash=self._hash(token),
            scopes_json=json.dumps("{'scopes': ['ops', 'openapi']}", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_single_quoted_json_object_with_scope_alias_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_single_quote_json_obj_scope_alias_1"
        ApiKey.objects.create(
            name="k-ops-top-single-quote-json-obj-scope-alias",
            token_hash=self._hash(token),
            scopes_json=json.dumps("{'scope': 'ops'}", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_single_quoted_json_object_with_scopes_csv_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_single_quote_json_obj_scopes_csv_1"
        ApiKey.objects.create(
            name="k-ops-top-single-quote-json-obj-scopes-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps("{'scopes': 'ops,openapi'}", ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_top_level_nested_quoted_json_object_string_payload(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_top_nested_json_obj_1"
        ApiKey.objects.create(
            name="k-ops-top-nested-json-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps('"{\\"ops\\":true,\\"openapi\\":false}"', ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_true_values(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_1"
        ApiKey.objects.create(
            name="k-ops-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"ops": True, "openapi": False}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_json_scope_object_ignores_false_string_values(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_false_1"
        ApiKey.objects.create(
            name="k-ops-obj-false",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"ops": "false"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 401, msg=res.content)

    def test_db_api_key_json_scope_object_accepts_quoted_true_string_values(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_quoted_true_1"
        ApiKey.objects.create(
            name="k-ops-obj-quoted-true",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"ops": '"true"', "openapi": '"false"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_list(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_list_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-list",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": ["ops", "openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_list_item_csv_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_list_item_csv_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-list-item-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": ["ops,openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_list_item_whitespace_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_list_item_space_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-list-item-space",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": ["ops openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_key_case_insensitive(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_key_case_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-key-case",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"Scopes": ["ops", "openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_list_with_nested_quotes(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_nested_quote_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-nested-quote",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": ['""ops""', "openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_csv(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_csv_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": "ops, openapi"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_pipe_delimited(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_pipe_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-pipe",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": "ops|openapi"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_quoted_csv(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_quoted_csv_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-quoted-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": '"ops, openapi"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_nested_quoted_semicolon_csv(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_nested_semicolon_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-nested-semicolon",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": '"ops;openapi"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_json_array_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": '["ops","openapi"]'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_single_quoted_json_array_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_single_quote_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-single-quote-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": "['ops','openapi']"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_tuple_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_tuple_scope_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-tuple-scope",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": "('ops','openapi')"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_nested_quoted_json_array_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_nested_json_arr_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-nested-json-arr",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": '"[\\"ops\\",\\"openapi\\"]"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_nested_quoted_json_object_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_nested_json_obj_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-nested-json-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": '"{\\"ops\\":true,\\"openapi\\":false}"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_single_quoted_json_object_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_single_quote_json_obj_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-single-quote-json-obj",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": "{'ops': True, 'openapi': False}"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scopes_map(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scopes_map_1"
        ApiKey.objects.create(
            name="k-ops-obj-scopes-map",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scopes": {"ops": True, "openapi": False}}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "fixture"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": "ops"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_tuple_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "fixture"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-tuple",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": "('ops','openapi')"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_pipe_delimited(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scope_alias_pipe_1"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-pipe",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": "ops|openapi"}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_quoted_csv(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scope_alias_quoted_csv_1"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-quoted-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": '"ops, openapi"'}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_list(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "fixture"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-list",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": ["ops", "openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_list_item_csv_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scope_alias_list_item_csv_1"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-list-item-csv",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": ["ops,openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_list_item_whitespace_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scope_alias_list_item_space_1"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-list-item-space",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": ["ops openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_db_api_key_accepts_json_scope_object_scope_alias_list_item_pipe_scope_string(self):
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_test_ops_obj_scope_alias_list_item_pipe_1"
        ApiKey.objects.create(
            name="k-ops-obj-scope-alias-list-item-pipe",
            token_hash=self._hash(token),
            scopes_json=json.dumps({"scope": ["ops|openapi"]}, ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        res = self.client.get(
            "/healthz",
            REMOTE_ADDR="8.8.8.8",
            HTTP_X_BEACON_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, msg=res.content)

    def test_ops_scoped_key_cannot_access_open_file_service(self):
        """
        Scope enforcement:
        - ops scope is enough for /healthz
        - but should NOT grant access to /open/* APIs by default
        """
        ApiKey = apps.get_model("app", "ApiKey")

        token = "k_ops_only"
        ApiKey.objects.create(
            name="k-ops-only",
            token_hash=self._hash(token),
            scopes_json=json.dumps(["ops"], ensure_ascii=False),
            expires_at=timezone.now() + timedelta(days=1),
        )

        from app.views import api as api_view

        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "hello.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("hello")

            setattr(api_view.g_config, "fileServiceEnabled", True)
            setattr(api_view.g_config, "fileServiceRootDir", tmp)

            res = self.client.get(
                "/open/fileService/hello.txt",
                REMOTE_ADDR="8.8.8.8",
                HTTP_X_BEACON_TOKEN=token,
            )

        self.assertEqual(res.status_code, 401)
