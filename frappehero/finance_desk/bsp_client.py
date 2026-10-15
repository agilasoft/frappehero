# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Download BSP reference bulletins and turn each PDF into rates.

The list is the public SharePoint list named RERB. One item is one banking
day, and the attachment is the bulletin PDF. Callers can pass ``get`` so the
download can be tested without the network.
"""

import json
from urllib.parse import urlencode

from frappehero.finance_desk.bsp import (
	as_iso_date,
	choose_bulletins,
	parse_bulletin,
	read_list_page,
)

HOST = "https://www.bsp.gov.ph"
LIST_PATH = "/_api/web/lists/getByTitle('RERB')/items"
JSON_ACCEPT = "application/json;odata=verbose"
USER_AGENT = "Mozilla/5.0 (compatible; FrappeHero/1.0; +https://github.com/agilasoft/frappehero)"
PAGE_LIMIT = 5


class BspError(Exception):
	"""The bulletin list or a PDF could not be used."""


def fetch_rates(start, end, get=None, stored_dates=None) -> dict:
	"""Rates for bulletins in the inclusive range.

	Dates in ``stored_dates`` are left for another run. They are listed and
	not downloaded again.
	"""
	getter = get or http_get
	listed = discover(start, end, getter)
	stored = {as_iso_date(item) for item in (stored_dates or [])}
	rates = []
	empty = []
	fetched = []
	skipped = []
	for item in listed:
		if item["date"] in stored:
			skipped.append(item["date"])
			continue
		data = getter(item["url"])
		if isinstance(data, str):
			data = data.encode("utf-8")
		parsed = parse_bulletin(pdf_text(data), item["date"])
		fetched.append(item["date"])
		if parsed:
			rates.extend(parsed)
		else:
			empty.append(item["date"])
	return {
		"rates": rates,
		"fetched": fetched,
		"empty": empty,
		"skipped": skipped,
		"listed": [row["date"] for row in listed],
	}


def discover(start, end, get) -> list[dict]:
	"""Bulletin dates and absolute PDF URLs, newest page first."""
	url = _list_url()
	found = []
	seen_dates = set()
	seen_urls = set()
	for _ in range(PAGE_LIMIT):
		if url in seen_urls:
			break
		seen_urls.add(url)
		page = _read_page(get(url, accept=JSON_ACCEPT))
		chosen = choose_bulletins(page, start, end)
		for item in chosen["bulletins"]:
			if item["date"] in seen_dates:
				continue
			seen_dates.add(item["date"])
			found.append({"date": item["date"], "url": absolute_url(item["url"])})
		if chosen["stop"] or not chosen["next"]:
			break
		url = chosen["next"]
	return found


def absolute_url(url) -> str:
	text = str(url or "").strip()
	if text.startswith("https://") or text.startswith("http://"):
		return text
	if not text.startswith("/"):
		text = "/" + text
	return HOST + text


def pdf_text(data) -> str:
	"""Plain text of a bulletin PDF."""
	blob = bytes(data or b"")
	if not blob.startswith(b"%PDF"):
		raise BspError("BSP did not return a bulletin PDF.")
	try:
		from pypdf import PdfReader
	except ImportError as exc:
		raise BspError("pypdf is required to read the BSP bulletin.") from exc
	from io import BytesIO

	try:
		reader = PdfReader(BytesIO(blob))
		return "\n".join((page.extract_text() or "") for page in reader.pages)
	except Exception as exc:
		raise BspError("The bulletin PDF could not be read.") from exc


def http_get(url, accept=None, timeout=120) -> bytes:
	import urllib.error
	import urllib.request

	request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
	if accept:
		request.add_header("Accept", accept)
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			return response.read()
	except urllib.error.HTTPError as exc:
		raise BspError(f"BSP refused the bulletin request ({exc.code}).") from exc
	except urllib.error.URLError as exc:
		raise BspError("BSP could not be reached.") from exc


def _list_url() -> str:
	query = urlencode(
		{
			"$top": "100",
			"$orderby": "Id desc",
			"$expand": "AttachmentFiles",
			"$select": "Id,Title,AttachmentFiles",
		}
	)
	return f"{HOST}{LIST_PATH}?{query}"


def _read_page(body) -> dict:
	if isinstance(body, bytes):
		body = body.decode("utf-8", errors="replace")
	try:
		return read_list_page(body)
	except json.JSONDecodeError as exc:
		raise BspError("BSP did not return the bulletin list.") from exc
