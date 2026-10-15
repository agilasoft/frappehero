# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Parse a BSP reference bulletin and decide which Currency Exchange rows to write.

The bulletin quotes Philippine pesos per one unit of foreign currency. USD uses
the BSP reference rate. Other rows use the peso-equivalent column. SDR and
metals are quoted in dollars, so they are left out. Nothing here talks to the
network or to Frappe.
"""

import json
import re
from datetime import date, datetime, timedelta

from frappehero.flags import as_flag, clean_text

QUOTE_CURRENCY = "PHP"
SKIPPED_CURRENCIES = frozenset({"SDR", "XDR", "XAU", "XAG"})
RATE_PLACES = 9
MAX_RANGE_DAYS = 31
DEFAULT_LOOKBACK_DAYS = 5

_MONTHS = {
	"jan": 1,
	"feb": 2,
	"mar": 3,
	"apr": 4,
	"may": 5,
	"jun": 6,
	"jul": 7,
	"aug": 8,
	"sep": 9,
	"oct": 10,
	"nov": 11,
	"dec": 12,
}

# A bulletin row ends with the ISO code and three figures. The last figure is
# the peso equivalent. Titles such as "BAHRAIN DINAR*" still leave the code
# in its own column.
_ROW_PATTERN = re.compile(
	r"^\s*\d+\s+.+?\s+([A-Z]{3})\s+(?:N/A|[\d.,]+)\s+(?:N/A|[\d.,]+)\s+(N/A|[\d.,]+)\s*$"
)
_REFERENCE_RATE_PATTERN = re.compile(r"BSP Reference Rate:\s*PHP\s+([\d.,]+)", re.IGNORECASE)
_TITLE_DATE_PATTERN = re.compile(r"^(\d{1,2})([A-Za-z]{3})(\d{4})$")


def parse_bulletin(text, bulletin_date) -> list[dict]:
	"""Rates from one bulletin's text.

	Each item is ``date``, ``currency``, and ``rate`` (pesos per 1 unit).
	USD is taken from the reference-rate line. The USD row in the table is a
	different figure and is ignored.
	"""
	iso_date = as_iso_date(bulletin_date)
	found = {}
	for line in str(text or "").splitlines():
		match = _ROW_PATTERN.match(line.strip())
		if not match:
			continue
		code = match.group(1)
		if code == "USD" or code in SKIPPED_CURRENCIES or code == QUOTE_CURRENCY:
			continue
		rate = _parse_rate(match.group(2))
		if rate is None or code in found:
			continue
		found[code] = rate

	reference = _REFERENCE_RATE_PATTERN.search(str(text or ""))
	if reference:
		usd = _parse_rate(reference.group(1))
		if usd is not None:
			found["USD"] = usd

	return [
		{"date": iso_date, "currency": code, "rate": found[code]}
		for code in sorted(found)
	]


def parse_title_date(title):
	"""Turn a SharePoint title such as ``29May2026`` into ``YYYY-MM-DD``."""
	compact = re.sub(r"\s+", "", str(title or ""))
	match = _TITLE_DATE_PATTERN.match(compact)
	if not match:
		return None
	month = _MONTHS.get(match.group(2).lower())
	if not month:
		return None
	try:
		return date(int(match.group(3)), month, int(match.group(1))).isoformat()
	except ValueError:
		return None


def read_list_page(payload) -> dict:
	"""Bulletins on one SharePoint list page, in the order they were returned.

	``payload`` is the verbose JSON object, a list of items, or a JSON string.
	Items without a file, and titles that are not dates, are dropped.
	"""
	data = _load_json(payload)
	next_url = None
	if isinstance(data, dict):
		body = data.get("d") if isinstance(data.get("d"), dict) else data
		items = body.get("results") if isinstance(body, dict) else None
		if items is None and isinstance(body, dict):
			items = body.get("value")
		if isinstance(body, dict):
			next_url = body.get("__next") or body.get("odata.nextLink") or None
		if items is None:
			items = []
	elif isinstance(data, list):
		items = data
	else:
		items = []

	bulletins = []
	for item in items:
		if not isinstance(item, dict):
			continue
		iso_date = parse_title_date(item.get("Title") or item.get("title"))
		url = _attachment_url(item)
		if not iso_date or not url:
			continue
		bulletins.append({"date": iso_date, "url": url})
	return {"bulletins": bulletins, "next": clean_text(next_url) or None}


def choose_bulletins(page, start, end) -> dict:
	"""Keep bulletins inside an inclusive range and say when to stop paging.

	The list is newest first. A date older than ``start`` means later pages
	are older still, so the caller should not follow ``next``.
	"""
	start_iso = as_iso_date(start)
	end_iso = as_iso_date(end)
	chosen = []
	stop = False
	for item in page.get("bulletins") or []:
		iso_date = item.get("date")
		if iso_date < start_iso:
			stop = True
			continue
		if iso_date > end_iso:
			continue
		chosen.append(item)
	if not page.get("bulletins"):
		stop = True
	return {"bulletins": chosen, "next": None if stop else page.get("next"), "stop": stop}


def plan_rates(rates, existing, enabled, write_inverse=True) -> dict:
	"""Create, update, or skip one Currency Exchange row per pair.

	A row this sync already owns is updated when the rate changed. A row
	entered by hand for the same date and pair is left alone. Currencies that
	are missing or disabled are reported and skipped. The inverse pair is
	PHP per the foreign currency, turned around, when ``write_inverse`` is set.
	"""
	enabled_codes = _enabled_set(enabled)
	current = _index_existing(existing)
	php_enabled = QUOTE_CURRENCY in enabled_codes
	wanted = []
	for rate in _unique_rates(rates):
		wanted.append((rate, False))
		if as_flag(write_inverse):
			wanted.append((rate, True))

	rows = []
	missing = set()
	for rate, inverse in wanted:
		currency = rate["currency"]
		if not php_enabled:
			missing.add(QUOTE_CURRENCY)
		if currency not in enabled_codes:
			missing.add(currency)
		if inverse:
			pair = (rate["date"], QUOTE_CURRENCY, currency)
			value = round(1 / rate["rate"], RATE_PLACES)
		else:
			pair = (rate["date"], currency, QUOTE_CURRENCY)
			value = rate["rate"]
		if not php_enabled or currency not in enabled_codes:
			rows.append(_row(pair, value, "skip", "Currency is not enabled", None))
			continue
		previous = current.get(pair)
		if previous is None:
			rows.append(_row(pair, value, "create", "New rate", None))
			continue
		if not as_flag(previous.get("hero_bsp")):
			rows.append(_row(pair, value, "skip", "Manual rate", previous.get("name")))
			continue
		if _same_rate(previous.get("exchange_rate"), value):
			rows.append(_row(pair, value, "skip", "Already stored", previous.get("name")))
			continue
		rows.append(_row(pair, value, "update", "BSP republished this rate", previous.get("name")))

	rows.sort(key=lambda row: (row["date"], row["from_currency"], row["to_currency"]))
	counts = {"create": 0, "update": 0, "skip": 0}
	for row in rows:
		counts[row["action"]] += 1
	return {"rows": rows, "missing_currencies": sorted(missing), "counts": counts}


def dates_with_bsp_rows(existing) -> set[str]:
	"""Dates that already have a row written by this sync."""
	found = set()
	for row in existing or []:
		if as_flag(row.get("hero_bsp")):
			found.add(as_iso_date(row.get("date")))
	return found


def clean_lookback(value, default=DEFAULT_LOOKBACK_DAYS) -> int:
	"""Whole days, from 1 to 31, for the daily job."""
	if value is None or value == "":
		return default
	try:
		days = int(value)
	except (TypeError, ValueError) as exc:
		raise ValueError("Lookback days must be a whole number from 1 to 31.") from exc
	if days < 1 or days > 31:
		raise ValueError("Lookback days must be a whole number from 1 to 31.")
	return days


def parse_range(start, end, max_days=MAX_RANGE_DAYS) -> tuple[str, str]:
	"""Inclusive ISO dates. The span cannot be longer than ``max_days``."""
	start_iso = as_iso_date(start)
	end_iso = as_iso_date(end)
	if start_iso > end_iso:
		raise ValueError("The start date is after the end date.")
	start_date = date.fromisoformat(start_iso)
	end_date = date.fromisoformat(end_iso)
	if (end_date - start_date).days > max_days:
		raise ValueError(f"Choose a range of {max_days} days or fewer.")
	return start_iso, end_iso


def add_days(iso_date, days) -> str:
	return (date.fromisoformat(as_iso_date(iso_date)) + timedelta(days=int(days))).isoformat()


def as_iso_date(value) -> str:
	if isinstance(value, datetime):
		return value.date().isoformat()
	if isinstance(value, date):
		return value.isoformat()
	text = clean_text(value)
	if not text:
		raise ValueError("A date is required.")
	try:
		return date.fromisoformat(text[:10]).isoformat()
	except ValueError as exc:
		raise ValueError("Use a date in YYYY-MM-DD form.") from exc


def _row(pair, value, action, reason, name) -> dict:
	return {
		"date": pair[0],
		"from_currency": pair[1],
		"to_currency": pair[2],
		"exchange_rate": value,
		"for_buying": 1,
		"for_selling": 1,
		"action": action,
		"reason": reason,
		"name": name,
	}


def _unique_rates(rates) -> list[dict]:
	found = {}
	for rate in rates or []:
		iso_date = as_iso_date(rate.get("date"))
		currency = clean_text(rate.get("currency")).upper()
		value = _parse_rate(rate.get("rate"))
		if not currency or value is None or currency in SKIPPED_CURRENCIES:
			continue
		found.setdefault((iso_date, currency), value)
	return [
		{"date": iso_date, "currency": currency, "rate": found[(iso_date, currency)]}
		for iso_date, currency in sorted(found)
	]


def _index_existing(existing) -> dict:
	index = {}
	for row in existing or []:
		key = (
			as_iso_date(row.get("date")),
			clean_text(row.get("from_currency")).upper(),
			clean_text(row.get("to_currency")).upper(),
		)
		current = index.get(key)
		if current is None or (as_flag(row.get("hero_bsp")) and not as_flag(current.get("hero_bsp"))):
			index[key] = row
	return index


def _enabled_set(enabled) -> set[str]:
	codes = set()
	for item in enabled or []:
		if isinstance(item, dict):
			code = item.get("name") or item.get("currency")
		else:
			code = item
		code = clean_text(code).upper()
		if code:
			codes.add(code)
	return codes


def _same_rate(left, right) -> bool:
	left_rate = _parse_rate(left)
	right_rate = _parse_rate(right)
	if left_rate is None or right_rate is None:
		return False
	return round(left_rate, RATE_PLACES) == round(right_rate, RATE_PLACES)


def _parse_rate(value):
	if isinstance(value, bool) or value is None:
		return None
	if isinstance(value, (int, float)):
		number = float(value)
	else:
		text = str(value).strip().replace(",", "")
		if not text or text.upper() == "N/A":
			return None
		try:
			number = float(text)
		except ValueError:
			return None
	if number <= 0:
		return None
	return number


def _attachment_url(item) -> str | None:
	files = item.get("AttachmentFiles") or item.get("attachmentFiles") or {}
	if isinstance(files, dict):
		rows = files.get("results") or files.get("value") or []
	elif isinstance(files, list):
		rows = files
	else:
		rows = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		url = clean_text(row.get("ServerRelativeUrl") or row.get("serverRelativeUrl"))
		if url:
			return url
	return clean_text(item.get("ServerRelativeUrl")) or None


def _load_json(payload):
	if isinstance(payload, str):
		if not payload.strip():
			return {}
		return json.loads(payload)
	return payload
