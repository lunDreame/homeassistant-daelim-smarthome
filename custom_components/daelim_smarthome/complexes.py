"""Fetch and parse Daelim SmartHome complex list from official site."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DAELIM_CHOICE_URL = "https://smarthome.daelimcorp.co.kr/main/choice_1.do"


def _find_matching_brace(html: str, start: int) -> int:
    """Find the closing brace, respecting strings and nesting."""
    depth = 1
    pos = start + 1
    while depth > 0 and pos < len(html):
        c = html[pos]
        if c == '"':
            pos += 1
            while pos < len(html):
                if html[pos] == '"' and html[pos - 1] != "\\":
                    break
                pos += 1
            pos += 1
        elif c == "'":
            pos += 1
            while pos < len(html):
                if html[pos] == "'" and html[pos - 1] != "\\":
                    break
                pos += 1
            pos += 1
        elif c == "{":
            depth += 1
            pos += 1
        elif c == "}":
            depth -= 1
            pos += 1
        else:
            pos += 1
    return pos - 1


def _parse_js_object(block: str) -> dict[str, Any]:
    """Parse JS-style key: value pairs from block."""
    obj: dict[str, Any] = {}
    for line in block.split("\n"):
        line = line.strip().rstrip(",").strip()
        if ":" not in line:
            continue
        idx = line.index(":")
        key = line[:idx].strip()
        val = line[idx + 1 :].strip().rstrip(",").strip()
        if not key:
            continue
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1].replace("\\'", "'")
        obj[key] = val
    return obj


def _extract_complexes(html: str) -> list[dict[str, Any]]:
    """Extract complex list from region.push({...}) calls."""
    complexes: list[dict[str, Any]] = []
    start = 0
    while True:
        idx = html.find("region.push(", start)
        if idx < 0:
            break
        brace_start = html.find("{", idx)
        if brace_start < 0:
            break
        brace_end = _find_matching_brace(html, brace_start)
        block = html[brace_start + 1 : brace_end]
        obj = _parse_js_object(block)
        if obj.get("name") and obj.get("ip"):
            complexes.append(
                {
                    "index": obj.get("index", ""),
                    "apartId": obj.get("apartId", ""),
                    "region": obj.get("danjiArea", ""),
                    "name": obj.get("name", ""),
                    "status": obj.get("status", "LIVE"),
                    "serverIp": obj.get("ip", ""),
                    "directoryName": obj.get("danjiDirectoryName", ""),
                    "geolocation": {
                        "state": obj.get("dongStep1", ""),
                        "city": obj.get("dongStep2", ""),
                        "details": obj.get("dongStep3", ""),
                    },
                }
            )
        start = brace_end + 1
    return complexes


def _organize_by_region(complexes: list[dict]) -> list[dict]:
    """Group complexes by region."""
    by_region: dict[str, list[dict]] = {}
    for c in complexes:
        region = c.get("region", "")
        if region not in by_region:
            by_region[region] = []
        by_region[region].append(c)
    return [{"region": r, "complexes": cs} for r, cs in sorted(by_region.items())]


def parse_choice_page(html: str) -> list[dict]:
    """
    Parse choice_1.do HTML and return complexes.
    Returns list of {region: str, complexes: [{name, serverIp, directoryName, ...}]}
    """
    raw = _extract_complexes(html)
    return _organize_by_region(raw)


async def fetch_complexes_from_daelim(session: aiohttp.ClientSession) -> list[dict]:
    """
    Fetch complex list from Daelim SmartHome official site.
    Returns list of {region: str, complexes: [...]} for config flow.
    """
    try:
        async with session.get(DAELIM_CHOICE_URL, ssl=False) as resp:
            if resp.status != 200:
                _LOGGER.warning("Daelim choice page returned %s", resp.status)
                return []
            html = await resp.text()
    except Exception as err:
        _LOGGER.error("Failed to fetch Daelim complexes: %s", err)
        return []
    result = parse_choice_page(html)
    _LOGGER.debug("Fetched %d regions, %d total complexes", len(result), sum(len(r["complexes"]) for r in result))
    return result
