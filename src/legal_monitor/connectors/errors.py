from __future__ import annotations

from legal_monitor.domain.enums import ErrorCode


class ConnectorError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthenticationRequired(ConnectorError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.AUTH_REQUIRED, "Sessão legítima precisa de autenticação humana")


class CaptchaRequired(ConnectorError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.CAPTCHA_REQUIRED, "CAPTCHA exige intervenção humana")
