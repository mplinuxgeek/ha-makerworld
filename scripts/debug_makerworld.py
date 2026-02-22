#!/usr/bin/env python3
"""Standalone MakerWorld debug runner.

Run this script to validate scraping/parsing behavior without restarting Home Assistant.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

MODEL_URL_RE = re.compile(r"^/en/models/(\d+)-([^/?#]+)$")
MODEL_METRIC_KEYS = ["likeCount", "downloadCount", "printCount", "boost"]
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class ScrapeError(RuntimeError):
    """Scraping/parsing failure."""


def _aiohttp():
    try:
        import aiohttp  # type: ignore
    except ModuleNotFoundError as err:
        raise ScrapeError(
            "Missing dependency 'aiohttp'. Run this from your Home Assistant venv "
            "or install aiohttp in your local Python environment."
        ) from err
    return aiohttp


def _beautiful_soup():
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ModuleNotFoundError as err:
        raise ScrapeError(
            "Missing dependency 'beautifulsoup4'. Run this from your Home Assistant venv "
            "or install beautifulsoup4 in your local Python environment."
        ) from err
    return BeautifulSoup


def _normalise_cookie(raw: str) -> str:
    cookie = raw or ""
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1]
    return cookie.strip().replace("\r", "").replace("\n", "").replace("\t", "")


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
    soup = _beautiful_soup()(html, "html.parser")
    refs: Set[Tuple[int, str]] = set()
    for a in soup.find_all("a", href=True):
        m = MODEL_URL_RE.match(a["href"])
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
        value = model.get("metrics", {}).get(metric)
        if isinstance(value, int):
            if best_val is None or value > best_val:
                best_val = value
                best = model
    if not best:
        return None
    return {
        "id": best.get("id"),
        "title": best.get("title"),
        "url": best.get("url"),
        metric: best_val,
    }


async def _fetch_html(
    session: Any, url: str, timeout: int, headers: Dict[str, str]
) -> str:
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.text()


async def _fetch_next_data(
    session: Any, url: str, timeout: int, headers: Dict[str, str]
) -> Dict[str, Any]:
    html = await _fetch_html(session, url, timeout, headers)
    soup = _beautiful_soup()(html, "html.parser")
    node = soup.select_one("script#__NEXT_DATA__")
    if not node or not node.string:
        raise ScrapeError(f"__NEXT_DATA__ not found for {url}")
    return json.loads(node.string)


async def _fetch_next_data_from_candidates(
    session: Any,
    urls: List[str],
    timeout: int,
    headers: Dict[str, str],
    label: str,
) -> Tuple[Dict[str, Any], str]:
    aiohttp = _aiohttp()
    last_err: Optional[Exception] = None
    attempts: List[str] = []
    for url in urls:
        try:
            return await _fetch_next_data(session, url, timeout, headers), url
        except Exception as err:
            last_err = err
            attempts.append(f"{url}: {err}")
            if isinstance(err, aiohttp.ClientResponseError) and err.status not in (403, 404):
                raise

    if isinstance(last_err, aiohttp.ClientResponseError) and last_err.status == 403:
        raise ScrapeError(
            f"{label} blocked with 403 on all known URLs. "
            "Cookie is likely expired or missing permissions."
        ) from last_err

    detail = "; ".join(attempts) if attempts else "no attempts made"
    raise ScrapeError(f"Failed to fetch {label}: {detail}") from last_err


async def _fetch_html_from_candidates(
    session: Any,
    urls: List[str],
    timeout: int,
    headers: Dict[str, str],
    label: str,
) -> Tuple[str, str]:
    aiohttp = _aiohttp()
    last_err: Optional[Exception] = None
    attempts: List[str] = []
    for url in urls:
        try:
            return await _fetch_html(session, url, timeout, headers), url
        except Exception as err:
            last_err = err
            attempts.append(f"{url}: {err}")
            if isinstance(err, aiohttp.ClientResponseError) and err.status not in (403, 404):
                raise

    detail = "; ".join(attempts) if attempts else "no attempts made"
    raise ScrapeError(f"Failed to fetch {label}: {detail}") from last_err


async def _fetch_model_metrics(
    session: Any,
    mid: int,
    slug: str,
    title_hint: Optional[str],
    timeout: int,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    url = f"https://makerworld.com/en/models/{mid}-{slug}"
    next_data = await _fetch_next_data(session, url, timeout, headers)
    info = _best_model_info(next_data)

    metrics: Dict[str, Any] = {}
    for key in MODEL_METRIC_KEYS:
        if key in info:
            value = info.get(key)
            parsed = _coerce_int(value)
            metrics[key] = parsed if parsed is not None else value

    return {
        "id": mid,
        "slug": slug,
        "url": url,
        "title": info.get("title") if isinstance(info.get("title"), str) else title_hint,
        "metrics": metrics,
    }


async def fetch_summary(
    user: str,
    cookie: str,
    user_agent: str,
    timeout: int,
    max_models: int,
) -> Dict[str, Any]:
    clean_user = user.lstrip("@")
    headers = {"User-Agent": user_agent, "Cookie": _normalise_cookie(cookie)}
    profile_urls = [
        f"https://makerworld.com/en/@{clean_user}",
        f"https://makerworld.com/@{clean_user}",
    ]
    upload_urls = [
        f"https://makerworld.com/en/@{clean_user}/upload",
        f"https://makerworld.com/@{clean_user}/upload",
    ]

    aiohttp = _aiohttp()
    async with aiohttp.ClientSession() as session:
        profile_nd, profile_url = await _fetch_next_data_from_candidates(
            session, profile_urls, timeout, headers, "profile"
        )

        user_info = _deep_get(profile_nd, "props.pageProps.userInfo")
        if not isinstance(user_info, dict):
            raise ScrapeError("props.pageProps.userInfo not found")

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
        upload_error = None
        upload_url = None
        try:
            upload_html, upload_url = await _fetch_html_from_candidates(
                session, upload_urls, timeout, headers, "upload page"
            )
            refs_html = _collect_model_refs_from_upload_html(upload_html)

            upload_nd, upload_url = await _fetch_next_data_from_candidates(
                session, upload_urls, timeout, headers, "upload data"
            )
            refs_nd = _collect_model_refs_from_next_data(upload_nd)
        except Exception as err:
            upload_error = str(err)

        merged: Dict[Tuple[int, str], Optional[str]] = dict(refs_nd)
        for mid, slug in refs_html:
            merged.setdefault((mid, slug), None)

        model_refs = list(merged.items())
        model_refs.sort(key=lambda x: x[0][0])
        if max_models > 0:
            model_refs = model_refs[:max_models]

        models: List[Dict[str, Any]] = []
        for (mid, slug), title in model_refs:
            try:
                metrics = await _fetch_model_metrics(
                    session,
                    mid=mid,
                    slug=slug,
                    title_hint=title,
                    timeout=timeout,
                    headers=headers,
                )
                models.append(metrics)
            except Exception as err:
                models.append(
                    {
                        "id": mid,
                        "slug": slug,
                        "title": title,
                        "error": str(err),
                    }
                )

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
            "canSubscribeCommercialLicense": user_info.get("canSubscribeCommercialLicense"),
            "designCount": _deep_get(user_info, "MWCount.designCount"),
            "collectionCount": user_info.get("collectionCount"),
            "downloadCount": user_info.get("downloadCount"),
            "followCount": user_info.get("followCount"),
            "featuredDesignCnt": user_info.get("featuredDesignCnt"),
            "winContestTimes": user_info.get("winContestTimes"),
        }

        return {
            **summary,
            "Top": top,
            "Models": len(merged),
            "Diagnostics": diagnostics,
            "debug": {
                "profile_url": profile_url,
                "upload_url": upload_url,
                "upload_error": upload_error,
                "resolved_model_refs": len(model_refs),
                "parsed_models": len(models),
            },
            "models": models,
        }


def _read_cookie(args: argparse.Namespace) -> str:
    if args.cookie:
        return args.cookie
    if args.cookie_file:
        return args.cookie_file.read().strip()
    raise ScrapeError("Provide --cookie or --cookie-file")


def _print_human(data: Dict[str, Any]) -> None:
    print("Summary:")
    for key in ("Likes", "Downloads", "Prints", "Points", "Followers", "Boosts Received"):
        print(f"  {key}: {data.get(key)}")

    print("\nTop Models:")
    for key in ("Most Liked Model", "Most Downloaded Model", "Most Printed Model"):
        top = data.get("Top", {}).get(key)
        if not top:
            print(f"  {key}: none")
            continue
        print(f"  {key}: {top.get('title')} ({top.get('url')})")

    dbg = data.get("debug", {})
    print("\nDebug:")
    print(f"  profile_url: {dbg.get('profile_url')}")
    print(f"  upload_url: {dbg.get('upload_url')}")
    print(f"  upload_error: {dbg.get('upload_error')}")
    print(f"  resolved_model_refs: {dbg.get('resolved_model_refs')}")
    print(f"  parsed_models: {dbg.get('parsed_models')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug MakerWorld scraping without HA restart.")
    parser.add_argument("--user", required=True, help="MakerWorld username (with or without @)")
    parser.add_argument("--cookie", help="Raw Cookie header value")
    parser.add_argument(
        "--cookie-file",
        type=argparse.FileType("r"),
        help="Path to file containing the raw Cookie header value",
    )
    parser.add_argument("--user-agent", default=DEFAULT_UA, help="User-Agent header")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    parser.add_argument("--max-models", type=int, default=0, help="0 = all")
    parser.add_argument("--json", action="store_true", help="Print full JSON output")
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    try:
        cookie = _read_cookie(args)
        data = await fetch_summary(
            user=args.user,
            cookie=cookie,
            user_agent=args.user_agent,
            timeout=args.timeout,
            max_models=args.max_models,
        )
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        _print_human(data)
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
