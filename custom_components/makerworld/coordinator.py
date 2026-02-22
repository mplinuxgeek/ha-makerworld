"""Data coordinator for MakerWorld integration."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import async_timeout
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COOKIE,
    CONF_MAX_MODELS,
    CONF_USER,
    CONF_USER_AGENT,
    DEFAULT_MAX_MODELS,
    DEFAULT_UA,
    DOMAIN,
)

MODEL_URL_RE = re.compile(r"^/en/models/(\d+)-([^/?#]+)$")
MODEL_METRIC_KEYS = ["likeCount", "downloadCount", "printCount", "boost"]
_LOGGER = logging.getLogger(__name__)


def _normalise_cookie(raw: str) -> str:
    cookie = raw or ""
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1]
    return cookie.strip().replace("\r", "").replace("\n", "").replace("\t", "")


def _compact_snippet(text: str, max_len: int = 300) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_len:
        return compact
    return compact[:max_len] + "...(truncated)"


def _cookie_fingerprint(cookie: str) -> str:
    """Short non-reversible cookie identifier for debug logs."""
    if not cookie:
        return "empty"
    return f"len={len(cookie)} prefix={cookie[:8]!r} suffix={cookie[-8:]!r}"


def _deep_get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _iter_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def _coerce_int(x: Any) -> Optional[int]:
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.isdigit():
        return int(x)
    return None


def _model_ref_from_dict(d: Dict[str, Any]) -> Optional[Tuple[int, str, Optional[str]]]:
    mid = d.get("id") if isinstance(d.get("id"), int) else None
    slug = d.get("slug") if isinstance(d.get("slug"), str) else None
    title = d.get("title") if isinstance(d.get("title"), str) else None
    if mid and slug:
        return (mid, slug, title)
    return None


def _collect_model_refs_from_upload_html(html: str) -> Set[Tuple[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    refs: Set[Tuple[int, str]] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = MODEL_URL_RE.match(href)
        if m:
            refs.add((int(m.group(1)), m.group(2)))
    return refs


def _collect_model_refs_from_next_data(next_data: Dict[str, Any]) -> Dict[Tuple[int, str], Optional[str]]:
    found: Dict[Tuple[int, str], Optional[str]] = {}
    for d in _iter_dicts(next_data):
        ref = _model_ref_from_dict(d)
        if ref:
            mid, slug, title = ref
            found[(mid, slug)] = title
    return found


def _build_model_url(mid: int, slug: str) -> str:
    return f"https://makerworld.com/en/models/{mid}-{slug}"


def _best_model_info(next_data: Dict[str, Any]) -> Dict[str, Any]:
    best_score = 0
    best: Dict[str, Any] = {}
    for d in _iter_dicts(next_data):
        score = 0
        if isinstance(d.get("title"), str):
            score += 3
        if isinstance(d.get("slug"), str):
            score += 2
        if isinstance(d.get("id"), int) or isinstance(d.get("modelId"), int):
            score += 2
        score += sum(1 for k in MODEL_METRIC_KEYS if k in d)
        if score > best_score:
            best_score = score
            best = d
    return best


def _top_by(models: List[Dict[str, Any]], metric: str) -> Optional[Dict[str, Any]]:
    best = None
    best_val: Optional[int] = None

    for model in models:
        v = model.get("metrics", {}).get(metric)
        if isinstance(v, int):
            if best_val is None or v > best_val:
                best_val = v
                best = model

    if not best:
        return None

    return {
        "id": best.get("id"),
        "title": best.get("title"),
        "url": best.get("url"),
        metric: best_val,
    }


class MakerWorldDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator to fetch MakerWorld stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        session,
        config: Dict[str, Any],
        options: Dict[str, Any],
        update_interval,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self._session = session
        self._user = config[CONF_USER].lstrip("@")
        self._cookie = _normalise_cookie(config.get(CONF_COOKIE, ""))
        self._user_agent = config.get(CONF_USER_AGENT, DEFAULT_UA)
        self._max_models = options.get(CONF_MAX_MODELS, DEFAULT_MAX_MODELS)
        self._last_update = None
        _LOGGER.debug(
            "MakerWorld coordinator init: user=%s cookie=%s",
            self._user,
            _cookie_fingerprint(self._cookie),
        )

    @property
    def last_update(self):
        return self._last_update

    async def _fetch_html(self, url: str, timeout: int) -> str:
        headers = {"User-Agent": self._user_agent, "Cookie": self._cookie}
        _LOGGER.debug(
            "MakerWorld request start: url=%s timeout=%ss cookie=%s ua=%s",
            url,
            timeout,
            _cookie_fingerprint(self._cookie),
            self._user_agent,
        )
        async with async_timeout.timeout(timeout):
            async with self._session.get(url, headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    hist = [str(h.url) for h in resp.history]
                    _LOGGER.warning(
                        (
                            "MakerWorld HTTP error: status=%s reason=%s request_url=%s "
                            "response_url=%s redirects=%s content_type=%s server=%s cf_ray=%s "
                            "location=%s cookie=%s body_snippet=%s"
                        ),
                        resp.status,
                        resp.reason,
                        url,
                        resp.url,
                        hist,
                        resp.headers.get("content-type"),
                        resp.headers.get("server"),
                        resp.headers.get("cf-ray"),
                        resp.headers.get("location"),
                        _cookie_fingerprint(self._cookie),
                        _compact_snippet(body),
                    )
                resp.raise_for_status()
                _LOGGER.debug(
                    "MakerWorld request success: request_url=%s response_url=%s status=%s body_len=%s",
                    url,
                    resp.url,
                    resp.status,
                    len(body),
                )
                return body

    async def _fetch_next_data(self, url: str, timeout: int) -> Dict[str, Any]:
        html = await self._fetch_html(url, timeout)
        soup = BeautifulSoup(html, "html.parser")
        node = soup.select_one("script#__NEXT_DATA__")
        if not node or not node.string:
            raise UpdateFailed(f"__NEXT_DATA__ not found for {url}")
        return json.loads(node.string)

    async def _fetch_next_data_from_candidates(
        self, urls: List[str], timeout: int, label: str
    ) -> Tuple[Dict[str, Any], str]:
        """Fetch __NEXT_DATA__ using the first working URL candidate."""
        last_err: Optional[Exception] = None
        attempts: List[str] = []

        for url in urls:
            _LOGGER.debug("Trying %s candidate URL: %s", label, url)
            try:
                data = await self._fetch_next_data(url, timeout)
                _LOGGER.debug(
                    "Selected %s candidate URL: %s (top-level keys: %s)",
                    label,
                    url,
                    list(data.keys()) if isinstance(data, dict) else type(data),
                )
                return data, url
            except Exception as err:
                last_err = err
                attempts.append(f"{url}: {err}")
                _LOGGER.debug("Failed %s candidate URL %s: %s", label, url, err)
                if isinstance(err, ClientResponseError) and err.status not in (403, 404):
                    raise

        if isinstance(last_err, ClientResponseError) and last_err.status == 403:
            raise UpdateFailed(
                f"{label} blocked with 403 on all known URLs. "
                "The MakerWorld cookie is likely expired or missing permissions."
            ) from last_err

        detail = "; ".join(attempts) if attempts else "no attempts made"
        raise UpdateFailed(f"Failed to fetch {label}: {detail}") from last_err

    async def _fetch_html_from_candidates(
        self, urls: List[str], timeout: int, label: str
    ) -> Tuple[str, str]:
        """Fetch HTML using the first working URL candidate."""
        last_err: Optional[Exception] = None
        attempts: List[str] = []

        for url in urls:
            _LOGGER.debug("Trying %s candidate URL: %s", label, url)
            try:
                html = await self._fetch_html(url, timeout)
                _LOGGER.debug(
                    "Selected %s candidate URL: %s (html_len=%s)",
                    label,
                    url,
                    len(html),
                )
                return html, url
            except Exception as err:
                last_err = err
                attempts.append(f"{url}: {err}")
                _LOGGER.debug("Failed %s candidate URL %s: %s", label, url, err)
                if isinstance(err, ClientResponseError) and err.status not in (403, 404):
                    raise

        detail = "; ".join(attempts) if attempts else "no attempts made"
        raise UpdateFailed(f"Failed to fetch {label}: {detail}") from last_err

    async def _fetch_model_metrics(
        self,
        mid: int,
        slug: str,
        title_hint: Optional[str],
        timeout: int,
    ) -> Dict[str, Any]:
        url = _build_model_url(mid, slug)
        nd = await self._fetch_next_data(url, timeout)
        info = _best_model_info(nd)

        metrics: Dict[str, Any] = {}
        for key in MODEL_METRIC_KEYS:
            if key in info:
                v = info.get(key)
                iv = _coerce_int(v)
                metrics[key] = iv if iv is not None else v

        return {
            "id": mid,
            "slug": slug,
            "url": url,
            "title": info.get("title") if isinstance(info.get("title"), str) else title_hint,
            "metrics": metrics,
        }

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            profile_urls = [
                f"https://makerworld.com/en/@{self._user}",
                f"https://makerworld.com/@{self._user}",
            ]
            upload_urls = [
                f"https://makerworld.com/en/@{self._user}/upload",
                f"https://makerworld.com/@{self._user}/upload",
            ]
            timeout = 20
            _LOGGER.debug(
                "Starting MakerWorld refresh for user='%s' profile_candidates=%s upload_candidates=%s",
                self._user,
                profile_urls,
                upload_urls,
            )

            profile_nd, profile_url = await self._fetch_next_data_from_candidates(
                profile_urls, timeout, "profile"
            )
            user_info = _deep_get(profile_nd, "props.pageProps.userInfo")
            if not isinstance(user_info, dict):
                _LOGGER.debug(
                    "profile data keys under props.pageProps: %s",
                    list(_deep_get(profile_nd, "props.pageProps", {}).keys())
                    if isinstance(_deep_get(profile_nd, "props.pageProps", {}), dict)
                    else type(_deep_get(profile_nd, "props.pageProps", {})),
                )
                raise UpdateFailed("props.pageProps.userInfo not found")

            points = (
                user_info.get("point")
                or user_info.get("points")
                or user_info.get("pointCount")
                or _deep_get(profile_nd, "props.pageProps.summary.Points")
            )

            summary = {
                "Likes": user_info.get("likeCount"),
                "Downloads": _deep_get(user_info, "MWCount.myDesignDownloadCount"),
                "Prints": _deep_get(user_info, "MWCount.myDesignPrintCount"),
                "Points": points,
                "Followers": user_info.get("fanCount"),
                "Boosts Received": user_info.get("boostGained"),
            }

            refs_html: Set[Tuple[int, str]] = set()
            refs_nd: Dict[Tuple[int, str], Optional[str]] = {}
            try:
                upload_html, _ = await self._fetch_html_from_candidates(
                    upload_urls, timeout, "upload page"
                )
                refs_html = _collect_model_refs_from_upload_html(upload_html)

                upload_nd, _ = await self._fetch_next_data_from_candidates(
                    upload_urls, timeout, "upload data"
                )
                refs_nd = _collect_model_refs_from_next_data(upload_nd)
                _LOGGER.debug(
                    "Upload refs extracted: html=%s next_data=%s",
                    len(refs_html),
                    len(refs_nd),
                )
            except UpdateFailed as err:
                _LOGGER.warning(
                    "Failed to load upload data for user '%s'; continuing with profile summary only. "
                    "Profile URL: %s. Error: %s",
                    self._user,
                    profile_url,
                    err,
                )

            merged: Dict[Tuple[int, str], Optional[str]] = dict(refs_nd)
            for mid, slug in refs_html:
                merged.setdefault((mid, slug), None)

            model_refs = list(merged.items())
            model_refs.sort(key=lambda x: x[0][0])
            _LOGGER.debug("Merged model refs before max_models limit: %s", len(model_refs))

            if self._max_models and self._max_models > 0:
                model_refs = model_refs[: self._max_models]
                _LOGGER.debug(
                    "Applied max_models=%s, scanning refs=%s",
                    self._max_models,
                    len(model_refs),
                )

            models: List[Dict[str, Any]] = []
            for (mid, slug), title in model_refs:
                try:
                    models.append(await self._fetch_model_metrics(mid, slug, title, timeout))
                except Exception:
                    _LOGGER.debug("Failed model metrics fetch for id=%s slug=%s", mid, slug)
                    continue

            top = {
                "Most Liked Model": _top_by(models, "likeCount"),
                "Most Downloaded Model": _top_by(models, "downloadCount"),
                "Most Printed Model": _top_by(models, "printCount"),
            }

            diagnostics = {
                "bannedPermission": user_info.get("bannedPermission"),
                "handle": user_info.get("handle"),
                "name": user_info.get("name"),
                "uid": user_info.get("uid"),
                "badges": user_info.get("badges"),
                "certificated": user_info.get("certificated"),
                "canSubscribeCommercialLicense": user_info.get(
                    "canSubscribeCommercialLicense"
                ),
                "designCount": _deep_get(user_info, "MWCount.designCount"),
                "collectionCount": user_info.get("collectionCount"),
                "downloadCount": user_info.get("downloadCount"),
                "followCount": user_info.get("followCount"),
                "featuredDesignCnt": user_info.get("featuredDesignCnt"),
                "winContestTimes": user_info.get("winContestTimes"),
            }

            last_update_val = dt_util.utcnow()
            _LOGGER.debug("Setting last_update to: %s (type: %s)", last_update_val, type(last_update_val))
            
            data = {
                **summary,
                "Top": top,
                "Models": len(merged),
                "Diagnostics": diagnostics,
                "last_update": last_update_val,
            }
            _LOGGER.debug("Coordinator data keys: %s", data.keys())
            return data
        except Exception as err:
            _LOGGER.exception("MakerWorld refresh failed for user '%s': %s", self._user, err)
            raise UpdateFailed(str(err)) from err
