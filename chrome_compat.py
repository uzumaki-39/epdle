"""chrome_compat.py — shim for curl_cffi AsyncSession with proxy support."""
from curl_cffi.requests import AsyncSession

class ChromeSession:
    def __init__(self, impersonate: str = "chrome131", proxies: dict = None, timeout: int = 12):
        self._impersonate = impersonate
        self._proxies = proxies
        self._timeout = timeout
        self._session = None

    async def __aenter__(self):
        self._session = AsyncSession(impersonate=self._impersonate)
        if self._proxies:
            self._session.proxies = self._proxies
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

import sys as _sys
_sys.modules['curl_compat'] = _sys.modules[__name__]