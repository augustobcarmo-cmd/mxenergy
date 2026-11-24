"""Descargas HTTP con reintentos, una sesión por hilo y respaldo de navegador.

`requests` resuelve casi todo. Si un sitio responde 403/503 a un cliente que
no parece navegador, se reintenta con curl_cffi imitando a Chrome.
"""

from __future__ import annotations

import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("mxenergy.red")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36 (+https://github.com/augustobcarmo-cmd/mxenergy)")
CABECERAS = {"User-Agent": UA, "Accept-Language": "es-MX,es;q=0.9,en;q=0.6"}


class ErrorRed(RuntimeError):
    pass


class Red:
    def __init__(self, timeout: tuple[float, float] = (10, 45), reintentos: int = 3,
                 espera: float = 1.5):
        self.timeout = timeout
        self.reintentos = reintentos
        self.espera = espera
        self._local = threading.local()
        self.peticiones = 0
        self._lock = threading.Lock()

    def _sesion(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            reintento = Retry(total=self.reintentos, connect=self.reintentos,
                              read=self.reintentos, backoff_factor=self.espera,
                              status_forcelist=(429, 500, 502, 504),
                              allowed_methods=("GET",), respect_retry_after_header=True,
                              raise_on_status=False)
            adaptador = HTTPAdapter(max_retries=reintento, pool_maxsize=8)
            s.mount("https://", adaptador)
            s.mount("http://", adaptador)
            s.headers.update(CABECERAS)
            self._local.s = s
        return s

    def get(self, url: str, verify: bool = True, **kw) -> requests.Response:
        with self._lock:
            self.peticiones += 1
        try:
            r = self._sesion().get(url, timeout=self.timeout, verify=verify, **kw)
        except requests.RequestException as e:
            self._local.s = None  # sesión nueva tras una falla de conexión
            raise ErrorRed(f"{type(e).__name__}: {e}") from e
        if r.status_code in (403, 503):
            alterna = self._como_navegador(url, verify)
            if alterna is not None:
                return alterna
        if r.status_code >= 400:
            raise ErrorRed(f"HTTP {r.status_code} en {url}")
        return r

    def _como_navegador(self, url: str, verify: bool):
        try:
            from curl_cffi import requests as cffi
        except ImportError:
            return None
        try:
            time.sleep(1)
            r = cffi.get(url, impersonate="chrome", timeout=self.timeout[1], verify=verify,
                         headers={"Accept-Language": CABECERAS["Accept-Language"]})
        except Exception as e:  # noqa: BLE001
            log.debug("curl_cffi falló en %s: %s", url, e)
            return None
        if r.status_code >= 400:
            return None
        log.debug("%s respondió a curl_cffi tras 403/503", url)
        return r

    def texto(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = getattr(r, "apparent_encoding", None) or "utf-8"
        return r.text

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()

    def contenido(self, url: str, **kw) -> bytes:
        return self.get(url, **kw).content
