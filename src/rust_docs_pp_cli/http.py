from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

USER_AGENT = f"rust-docs-pp-cli/{__version__} (+https://github.com/WolCarlos/Wol-rust-docs-pp-cli)"


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class Response:
    body: bytes
    url: str
    content_type: str

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.rsplit("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class HTTPClient:
    def __init__(self, timeout: float = 60.0, retries: int = 2):
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str) -> Response:
        if not url.startswith(("https://", "http://")):
            raise FetchError(f"Unsupported URL: {url}")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html, text/plain, application/octet-stream;q=0.8",
                "Accept-Encoding": "gzip",
            },
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding", "").lower() == "gzip":
                        body = gzip.decompress(body)
                    status = getattr(response, "status", 200)
                    if status != 200:
                        raise FetchError(f"HTTP {status} from {url}")
                    return Response(
                        body=body,
                        url=response.geturl(),
                        content_type=response.headers.get("Content-Type", ""),
                    )
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else 2**attempt
                    time.sleep(min(delay, 10.0))
                    continue
                raise FetchError(f"HTTP {exc.code} from {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise FetchError(f"Unable to fetch {url}: {exc}") from exc
        raise FetchError(f"Unable to fetch {url}")
