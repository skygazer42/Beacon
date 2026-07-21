import json


PATH_LOGIN = "/login"


class SmokeError(RuntimeError):
    pass


class BeaconWebSession:
    """
    Minimal HTTP helper for Beacon session-based web UI endpoints.

    Goals:
    - requests.Session compatible
    - CSRF-safe POSTs (cookie + header + form token)
    - Keep API tiny; tailored for Cloud POC smoke scripts
    """

    def __init__(self, session, *, base_url: str):
        """处理`init`。"""
        self._session = session
        self._base_url = str(base_url or "").rstrip("/")
        if not self._base_url:
            raise SmokeError("base_url is required")

    def _url(self, path: str) -> str:
        """返回请求 URL。"""
        p = str(path or "").strip()
        if not p.startswith("/"):
            p = "/" + p
        return self._base_url + p

    def _csrf_token(self) -> str:
        """返回CSRF令牌。"""
        cookies = getattr(self._session, "cookies", None)
        if not cookies:
            return ""
        try:
            token = cookies.get("csrftoken")
        except Exception:
            token = ""
        return str(token or "").strip()

    def ensure_csrf(self, *, timeout: int = 10) -> str:
        """处理`ensure`CSRF。
        
        Force csrf cookie to exist by requesting /login (template renders {% csrf_token %}).
        """
        token = self._csrf_token()
        if token:
            return token

        resp = self._session.get(self._url(PATH_LOGIN), timeout=timeout)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise SmokeError(f"GET /login failed: status={getattr(resp, 'status_code', None)}")

        token = self._csrf_token()
        if not token:
            raise SmokeError("missing csrftoken cookie after GET /login")
        return token

    def post_form(self, path: str, *, data: dict, referer_path: str = PATH_LOGIN, timeout: int = 10):
        """发送表单请求。"""
        token = self.ensure_csrf(timeout=timeout)

        form = dict(data or {})
        form.setdefault("csrfmiddlewaretoken", token)

        headers = {
            "X-CSRFToken": token,
            "Referer": self._url(referer_path),
        }
        return self._session.post(self._url(path), data=form, headers=headers, timeout=timeout)

    def login(self, *, username: str, password: str, timeout: int = 10):
        """执行登录流程。"""
        resp = self.post_form(
            PATH_LOGIN,
            data={"username": str(username or ""), "password": str(password or "")},
            referer_path=PATH_LOGIN,
            timeout=timeout,
        )
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise SmokeError(f"POST /login failed: status={getattr(resp, 'status_code', None)}")

        payload = None
        try:
            payload = resp.json()
        except Exception:
            try:
                payload = json.loads(str(getattr(resp, "text", "") or ""))
            except Exception:
                payload = None

        if not isinstance(payload, dict):
            raise SmokeError("POST /login returned non-json payload")

        if int(payload.get("code", 0) or 0) != 1000:
            raise SmokeError(f"login failed: code={payload.get('code')} msg={payload.get('msg')}")
        return payload
