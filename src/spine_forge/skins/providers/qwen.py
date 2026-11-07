"""Qwen image-to-image provider (Alibaba Model Studio / DashScope).

Ported from the hicustom-api `QwenImageClient`, keeping the wire format that is
already proven against this account:

    POST {base}/api/v1/services/aigc/multimodal-generation/generation
    Authorization: Bearer <QIANWEN_API_KEY>
    {"model": "qwen-image-2.1-turbo",
     "input": {"messages": [{"role": "user",
                "content": [{"image": <data-url>}, {"text": <instruction>}]}]},
     "parameters": {"prompt_extend": false, "negative_prompt": "..."}}

The response carries a URL, not bytes, so a second request downloads the image.

This provider is image-to-image: the reference art is sent as the input image,
which is what preserves the original style and framing.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

from PIL import Image

from .. import prompts
from ..base import SkinProvider, SkinProviderError
from ..request import SkinRequest, SkinResult

DEFAULT_BASE_URL = "https://llm-l7jagaoeeeo9jsgi.cn-beijing.maas.aliyuncs.com"
ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_MODEL = "qwen-image-2.1-turbo"


def _to_data_url(image: Image.Image) -> str:
    """Inline an image as a base64 data URL, the form this endpoint accepts."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded


def _extract_url(payload: dict) -> str | None:
    """Pull the image URL out of the response.

    Mirrors the original client: the documented shape is
    ``output.choices[0].message.content[].image``, with a few fallbacks because
    the service has returned other shapes.
    """
    output = payload.get("output") or {}
    choices = output.get("choices") or []
    if choices:
        content = (choices[0] or {}).get("message", {}).get("content") or []
        for item in content:
            if isinstance(item, dict) and item.get("image"):
                return item["image"]
    results = output.get("results") or []
    if results and isinstance(results[0], dict) and results[0].get("url"):
        return results[0]["url"]
    for key in ("url", "image"):
        if output.get(key):
            return output[key]
    return None


class QwenSkinProvider(SkinProvider):
    """Alibaba qwen-image, image-to-image."""

    name = "qwen"
    supports_reference = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 180.0,
    ) -> None:
        if not api_key:
            raise SkinProviderError(
                "qwen provider needs QIANWEN_API_KEY; set it in the project .env"
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ---- transport ---------------------------------------------------

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise SkinProviderError(
                f"qwen generation failed (HTTP {error.code}): {detail}"
            ) from error
        except urllib.error.URLError as error:
            raise SkinProviderError(
                f"qwen generation unreachable: {error.reason}"
            ) from error
        except TimeoutError as error:
            raise SkinProviderError(
                f"qwen generation timed out after {int(self.timeout)}s"
            ) from error

        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise SkinProviderError(
                f"qwen returned non-JSON: {raw[:200]}"
            ) from error

    def _download(self, url: str) -> Image.Image:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            raise SkinProviderError(f"could not download qwen result: {error}") from error
        return Image.open(io.BytesIO(data)).convert("RGBA")

    # ---- protocol ----------------------------------------------------

    def generate(self, request: SkinRequest) -> SkinResult:
        if request.reference is None:
            raise SkinProviderError(
                "qwen is an image-to-image provider; a reference image is required"
            )

        instruction = prompts.compose(request)
        content = [
            {"image": _to_data_url(request.reference)},
            {"text": instruction},
        ]
        body = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {
                # Off by default: prompt extension rewrites the instruction, and
                # this pipeline depends on the wording it composed.
                "prompt_extend": bool(request.extra.get("prompt_extend", False)),
                "negative_prompt": prompts.negative(request),
            },
        }

        payload = self._post(body)
        if payload.get("code") or payload.get("error"):
            message = (
                (payload.get("error") or {}).get("message")
                or payload.get("message")
                or json.dumps(payload)[:300]
            )
            raise SkinProviderError(f"qwen generation rejected: {message}")

        url = _extract_url(payload)
        if not url:
            raise SkinProviderError(
                "qwen returned no image URL: " + json.dumps(payload)[:300]
            )

        image = self._download(url)
        notes: list[str] = []
        if request.width and request.height:
            if image.size != (request.width, request.height):
                notes.append(
                    f"provider returned {image.size[0]}x{image.size[1]}, "
                    f"requested {request.width}x{request.height}"
                )

        return SkinResult(
            image=image,
            provider=self.name,
            model=self.model,
            prompt=instruction,
            notes=notes,
            raw=payload,
        )
