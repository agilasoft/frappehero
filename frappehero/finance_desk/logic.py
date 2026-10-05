# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for dimensions, item tax, and opening journals.

Account matching reuses Account Mapper: a unique account number, otherwise
a unique account name. Ambiguous numbers are not guessed.
"""

from frappehero.accounts_mapping.logic import suggest_for_account
from frappehero.flags import as_flag, clean_text

DIMENSIONS = ("Cost Center", "Project", "Branch")
DIMENSION_FIELDS = {
	"Cost Center": "cost_center",
	"Project": "project",
	"Branch": "branch",
}
OPENING_PURPOSES = ("Opening Entry", "Reclass")


def summarize_dimensions(aggregates) -> dict:
	"""Coverage of one dimension.

	``complete`` means nothing is missing. ``missing`` means every entry is
	missing the dimension. ``empty`` means the account has no GL entries.
	"""
	rows = []
	total_entries = 0
	missing_entries = 0
	for row in aggregates or []:
		total = int(row.get("total") or 0)
		missing = int(row.get("missing") or 0)
		status, percent = _dimension_status(total, missing)
		total_entries += max(total, 0)
		missing_entries += max(min(missing, total), 0)
		rows.append(
			{
				"account": clean_text(row.get("account")),
				"account_name": row.get("account_name"),
				"account_number": row.get("account_number"),
				"total": total,
				"missing": missing,
				"status": status,
				"percent": percent,
			}
		)
	overall_status, overall_percent = _dimension_status(total_entries, missing_entries)
	return {
		"rows": rows,
		"overall": {
			"total": total_entries,
			"missing": missing_entries,
			"status": overall_status,
			"percent": overall_percent,
		},
	}


def filter_dimension_rows(rows, status=None, search=None) -> list[dict]:
	wanted = clean_text(status).casefold()
	query = clean_text(search).casefold()
	kept = []
	for row in rows or []:
		if wanted and wanted != "all" and clean_text(row.get("status")).casefold() != wanted:
			continue
		if query:
			haystack = " ".join(
				clean_text(row.get(key)) for key in ("account", "account_name", "account_number")
			).casefold()
			if query not in haystack:
				continue
		kept.append(row)
	return kept


def value_to_apply(account, current_value, default_row):
	"""Dimension value for a new GL entry, or None when nothing should change.

	A filled dimension is left alone. Defaults apply only when the row opts in.
	"""
	if not default_row:
		return None
	if clean_text(default_row.get("account")) != clean_text(account):
		return None
	if not as_flag(default_row.get("apply_on_new_entries")):
		return None
	if clean_text(current_value):
		return None
	value = clean_text(default_row.get("default_value"))
	return value or None


def group_tax_map(groups) -> list[dict]:
	"""Item groups mapped when they or an ancestor have an item tax template."""
	by_name = {}
	for group in groups or []:
		name = clean_text(group.get("name"))
		if not name:
			continue
		templates = group.get("templates")
		if templates is None and group.get("template"):
			templates = [group.get("template")]
		by_name[name] = {
			"name": name,
			"parent": clean_text(group.get("parent_item_group")),
			"templates": [clean_text(item) for item in templates or [] if clean_text(item)],
		}

	def resolve(name, trail):
		if name in trail or name not in by_name:
			return None, None
		own = by_name[name]["templates"]
		if own:
			return own[0], name
		parent = by_name[name]["parent"]
		if not parent:
			return None, None
		return resolve(parent, trail | {name})

	rows = []
	for name, group in by_name.items():
		template, source = resolve(name, set())
		rows.append(
			{
				"name": name,
				"parent_item_group": group["parent"],
				"status": "mapped" if template else "unmapped",
				"template": template,
				"inherited_from": source if source and source != name else None,
				"own_template": group["templates"][0] if group["templates"] else None,
			}
		)
	return rows


def items_without_tax(items, group_rows) -> list[dict]:
	"""Items with no own template whose item group is also unmapped."""
	status = {row["name"]: row for row in group_rows or []}
	missing = []
	for item in items or []:
		if clean_text(item.get("own_template") or item.get("template")):
			continue
		group_name = clean_text(item.get("item_group"))
		group = status.get(group_name)
		if group and group.get("status") == "mapped":
			continue
		missing.append(
			{
				"name": clean_text(item.get("name")),
				"item_name": item.get("item_name"),
				"item_group": group_name,
			}
		)
	return missing


def filter_named_rows(rows, search, fields) -> list[dict]:
	query = clean_text(search).casefold()
	if not query:
		return list(rows or [])
	kept = []
	for row in rows or []:
		haystack = " ".join(clean_text(row.get(field)) for field in fields).casefold()
		if query in haystack:
			kept.append(row)
	return kept


def parse_trial_balance(text) -> list[dict]:
	"""Paste from a spreadsheet.

	A tab in the first line selects tabs. Otherwise fields are commas.
	Four columns are number, name, debit, credit. Three are name, debit, credit.
	The first line is a header when it contains debit or credit as a column title.
	"""
	raw_lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
	if not raw_lines:
		return []
	delimiter = "\t" if "\t" in raw_lines[0] else ","
	rows = []
	for index, line in enumerate(raw_lines):
		parts = [_unquote(part.strip()) for part in line.split(delimiter)]
		if index == 0 and _is_header(parts):
			continue
		parsed = _parse_balance_parts(parts)
		if parsed:
			rows.append(parsed)
	return rows


def match_opening_lines(lines, candidates) -> list[dict]:
	"""Match pasted lines to ledger accounts in one company."""
	matched = []
	for line in lines or []:
		result = classify_opening_line(line, candidates)
		matched.append(
			{
				"account_number": clean_text(line.get("account_number")),
				"account_name": clean_text(line.get("account_name")),
				"debit": round(float(line.get("debit") or 0), 2),
				"credit": round(float(line.get("credit") or 0), 2),
				**result,
			}
		)
	return matched


def classify_opening_line(line, candidates) -> dict:
	number = clean_text(line.get("account_number"))
	ledgers = [row for row in candidates or [] if not as_flag(row.get("is_group")) and not as_flag(row.get("disabled"))]
	if number:
		matches = [row for row in ledgers if clean_text(row.get("account_number")) == number]
		if len(matches) > 1:
			return {
				"match_status": "Ambiguous",
				"matched_account": None,
				"match_reason": "Account number matches more than one ledger",
			}
	source = {
		"name": clean_text(line.get("account_name")) or number,
		"account_number": number,
		"account_name": clean_text(line.get("account_name")),
		"is_group": 0,
		"disabled": 0,
	}
	suggestion = suggest_for_account(source, candidates or [], "Another Company")
	if suggestion and suggestion.get("target_account"):
		return {
			"match_status": "Matched",
			"matched_account": suggestion["target_account"],
			"match_reason": suggestion.get("reason") or "Matched",
		}
	return {
		"match_status": "Unmatched",
		"matched_account": None,
		"match_reason": "No unique account number or name",
	}


def opening_totals(lines) -> dict:
	debit = round(sum(round(float(line.get("debit") or 0), 2) for line in lines or []), 2)
	credit = round(sum(round(float(line.get("credit") or 0), 2) for line in lines or []), 2)
	return {"debit": debit, "credit": credit, "difference": round(debit - credit, 2)}


def can_create_journal(lines, tolerance=0.005) -> bool:
	"""True when every line is matched and debit minus credit is about zero."""
	if not lines:
		return False
	for line in lines:
		if clean_text(line.get("match_status")) != "Matched" or not clean_text(line.get("matched_account")):
			return False
	return abs(opening_totals(lines)["difference"]) <= tolerance


def _dimension_status(total, missing) -> tuple[str, float]:
	if total <= 0:
		return "empty", 0
	if missing <= 0:
		return "complete", 100.0
	if missing >= total:
		return "missing", 0
	return "partial", round(((total - missing) / total) * 100, 1)


def _is_header(parts) -> bool:
	cells = {clean_text(part).casefold() for part in parts}
	titles = {"account", "account name", "account number", "name", "debit", "credit"}
	return bool(cells & {"debit", "credit"}) and bool(cells & titles)


def _parse_balance_parts(parts) -> dict | None:
	if len(parts) >= 4:
		try:
			debit = _amount(parts[-2])
			credit = _amount(parts[-1])
		except ValueError:
			return None
		return {
			"account_number": parts[0],
			"account_name": ",".join(parts[1:-2]).strip(),
			"debit": debit,
			"credit": credit,
		}
	if len(parts) == 3:
		try:
			debit = _amount(parts[1])
			credit = _amount(parts[2])
		except ValueError:
			return None
		return {"account_number": "", "account_name": parts[0], "debit": debit, "credit": credit}
	return None


def _amount(value) -> float:
	text = clean_text(value).replace(",", "")
	if not text:
		return 0.0
	return round(float(text), 2)


def _unquote(value) -> str:
	if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
		return value[1:-1]
	return value
