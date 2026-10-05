# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for account maps.

A map sends each ledger account somewhere else: another company's account,
an external code, or a reporting group. These functions classify lines,
filter the chart, build the tree, and suggest matches. They do not touch
the database.
"""

from frappehero.flags import clean_text

MAPPING_TYPES = ("Another Company", "External Code", "Reporting Group")
ROOT_TYPES = ("Asset", "Liability", "Equity", "Income", "Expense")


def line_completion(mapping_type: str, line: dict) -> str:
	"""``mapped`` when the line has the target its map type asks for, else ``partial``."""
	if mapping_type == "Another Company":
		return "mapped" if clean_text(line.get("target_account")) else "partial"
	if mapping_type == "External Code":
		return "mapped" if clean_text(line.get("external_code")) else "partial"
	if mapping_type == "Reporting Group":
		return "mapped" if clean_text(line.get("reporting_group")) else "partial"
	return "partial"


def index_lines(lines: list[dict]) -> dict:
	indexed = {}
	for line in lines or []:
		source = clean_text(line.get("source_account"))
		if source and source not in indexed:
			indexed[source] = line
	return indexed


def account_status(account_name: str, lines_by_source: dict, mapping_type: str) -> str:
	line = lines_by_source.get(account_name)
	if not line:
		return "unmapped"
	return line_completion(mapping_type, line)


def coverage(accounts: list[dict], status_by_name: dict) -> dict:
	"""Coverage of non-disabled ledger accounts. Groups are not counted."""
	leaves = [
		account
		for account in accounts
		if not _is_group(account) and not _is_disabled(account)
	]
	mapped = sum(1 for account in leaves if status_by_name.get(account["name"]) == "mapped")
	partial = sum(1 for account in leaves if status_by_name.get(account["name"]) == "partial")
	total = len(leaves)
	unmapped = total - mapped - partial
	percent = round((mapped / total) * 100, 1) if total else 0
	return {
		"mapped": mapped,
		"partial": partial,
		"unmapped": unmapped,
		"total": total,
		"percent": percent,
	}


def validate_map(account_map: dict, account_company: dict, group_accounts: set | None = None) -> list[str]:
	"""Problems with a map and its lines.

	``account_company`` maps an account name to its company. Missing keys mean
	the account does not exist. ``group_accounts`` are folders, which are not
	mapped themselves.
	"""
	group_accounts = group_accounts or set()
	errors = []
	mapping_type = clean_text(account_map.get("mapping_type"))
	if mapping_type not in MAPPING_TYPES:
		errors.append("Choose a mapping type.")
		return errors

	company = clean_text(account_map.get("company"))
	if not company:
		errors.append("Company is required.")

	target_company = clean_text(account_map.get("target_company"))
	if mapping_type == "Another Company":
		if not target_company:
			errors.append("Target company is required when mapping to another company.")
		elif target_company == company:
			errors.append("Target company must be different from the source company.")

	seen = set()
	for line in account_map.get("lines") or []:
		source = clean_text(line.get("source_account"))
		if not source:
			errors.append("Every line needs a source account.")
			continue
		if source in seen:
			errors.append(f"{source} is mapped more than once.")
		seen.add(source)
		if source in group_accounts:
			errors.append(f"{source} is a group account. Map its ledgers instead.")
		source_company = account_company.get(source)
		if source_company is None:
			errors.append(f"Source account {source} does not exist.")
		elif company and source_company != company:
			errors.append(f"{source} belongs to {source_company}, not {company}.")

		target = clean_text(line.get("target_account"))
		if target:
			target_owner = account_company.get(target)
			expected = target_company if mapping_type == "Another Company" else company
			if target_owner is None:
				errors.append(f"Target account {target} does not exist.")
			elif expected and target_owner != expected:
				errors.append(f"{target} belongs to {target_owner}, not {expected}.")
			if target == source:
				errors.append(f"{source} cannot be mapped to itself.")
	return errors


def status_by_account(accounts: list[dict], lines: list[dict], mapping_type: str) -> dict:
	lines_by_source = index_lines(lines)
	return {
		account["name"]: account_status(account["name"], lines_by_source, mapping_type)
		for account in accounts
	}


def visible_tree(accounts: list[dict], status_by_name: dict, filters: dict | None = None) -> list[dict]:
	"""Chart of accounts pruned by the filters, with ancestors kept so it still reads as a tree.

	Group nodes carry ``mapped_leaves`` and ``total_leaves`` for the leaves that
	remain visible under them.
	"""
	filters = filters or {}
	by_name = {account["name"]: account for account in accounts}
	children = {account["name"]: [] for account in accounts}
	for account in accounts:
		parent = account.get("parent_account")
		if parent in children:
			children[parent].append(account["name"])

	active_leaves = []
	for account in accounts:
		if _is_group(account):
			continue
		if not _passes_common(account, filters):
			continue
		if not _passes_search(account, filters, by_name):
			continue
		status = status_by_name.get(account["name"], "unmapped")
		if not _passes_status(status, filters):
			continue
		active_leaves.append(account["name"])

	visible_leaves = list(dict.fromkeys(active_leaves))
	visible = set(visible_leaves)
	for leaf_name in visible_leaves:
		parent = by_name[leaf_name].get("parent_account")
		while parent and parent in by_name and parent not in visible:
			visible.add(parent)
			parent = by_name[parent].get("parent_account")

	def build(name: str) -> dict:
		account = by_name[name]
		node = dict(account)
		node["status"] = status_by_name.get(name, "unmapped")
		node["children"] = [build(child) for child in children[name] if child in visible]
		if _is_group(account):
			mapped, partial, total = _count_built(node)
			node["mapped_leaves"] = mapped
			node["partial_leaves"] = partial
			node["total_leaves"] = total
			if total == 0:
				node["status"] = "unmapped"
			elif mapped == total:
				node["status"] = "mapped"
			elif mapped == 0 and partial == 0:
				node["status"] = "unmapped"
			else:
				node["status"] = "partial"
		else:
			node["mapped_leaves"] = 1 if node["status"] == "mapped" else 0
			node["partial_leaves"] = 1 if node["status"] == "partial" else 0
			node["total_leaves"] = 1
		return node

	roots = []
	for account in accounts:
		parent = account.get("parent_account")
		if account["name"] in visible and parent not in visible:
			roots.append(build(account["name"]))
	return roots


def suggest_for_account(source: dict, candidates: list[dict], mapping_type: str) -> dict | None:
	"""One suggestion for a ledger account, or None when nothing is unambiguous."""
	if _is_group(source):
		return None
	if mapping_type == "Another Company":
		return _suggest_account(source, candidates)
	if mapping_type == "External Code":
		number = clean_text(source.get("account_number"))
		if not number:
			return None
		return {
			"external_code": number,
			"external_name": clean_text(source.get("account_name")) or source.get("name"),
			"reason": "Account number",
		}
	if mapping_type == "Reporting Group":
		account_type = clean_text(source.get("account_type"))
		if account_type:
			return {"reporting_group": account_type, "reason": "Account type"}
		root_type = clean_text(source.get("root_type"))
		if root_type:
			return {"reporting_group": root_type, "reason": "Root type"}
	return None


def suggest_mappings(
	sources: list[dict],
	candidates: list[dict],
	mapping_type: str,
	already_mapped: set[str] | None = None,
) -> list[dict]:
	done = already_mapped or set()
	suggestions = []
	for source in sources:
		if _is_group(source) or _is_disabled(source):
			continue
		if source.get("name") in done:
			continue
		suggestion = suggest_for_account(source, candidates, mapping_type)
		if not suggestion:
			continue
		suggestions.append({"source_account": source["name"], "account_name": source.get("account_name"), **suggestion})
	return suggestions


def unmapped_rows(accounts: list[dict], lines: list[dict], mapping_type: str, filters: dict | None = None) -> list[dict]:
	"""Flat rows for the Unmapped Accounts report. Groups are omitted."""
	filters = filters or {}
	status_by_name = status_by_account(accounts, lines, mapping_type)
	lines_by_source = index_lines(lines)
	rows = []
	for account in accounts:
		if _is_group(account):
			continue
		if not _passes_common(account, filters):
			continue
		status = status_by_name.get(account["name"], "unmapped")
		if not _passes_status(status, filters):
			continue
		if not _passes_search(account, filters, {item["name"]: item for item in accounts}):
			continue
		line = lines_by_source.get(account["name"]) or {}
		rows.append(
			{
				"account": account["name"],
				"account_name": account.get("account_name"),
				"account_number": account.get("account_number"),
				"root_type": account.get("root_type"),
				"account_type": account.get("account_type"),
				"parent_account": account.get("parent_account"),
				"status": status,
				"target_account": line.get("target_account"),
				"external_code": line.get("external_code"),
				"reporting_group": line.get("reporting_group"),
			}
		)
	return rows


def _suggest_account(source: dict, candidates: list[dict]) -> dict | None:
	number = clean_text(source.get("account_number"))
	ledgers = [candidate for candidate in candidates if not _is_group(candidate) and not _is_disabled(candidate)]
	if number:
		matches = [candidate for candidate in ledgers if clean_text(candidate.get("account_number")) == number]
		if len(matches) == 1:
			return {
				"target_account": matches[0]["name"],
				"reason": "Same account number",
			}
		if len(matches) > 1:
			return None
	name = _norm(source.get("account_name"))
	if name:
		matches = [candidate for candidate in ledgers if _norm(candidate.get("account_name")) == name]
		if len(matches) == 1:
			return {
				"target_account": matches[0]["name"],
				"reason": "Same account name",
			}
	return None


def _count_built(node: dict) -> tuple[int, int, int]:
	if not node.get("children"):
		if _is_group(node):
			return 0, 0, 0
		mapped = 1 if node.get("status") == "mapped" else 0
		partial = 1 if node.get("status") == "partial" else 0
		return mapped, partial, 1
	mapped = partial = total = 0
	for child in node["children"]:
		child_mapped, child_partial, child_total = _count_built(child)
		mapped += child_mapped
		partial += child_partial
		total += child_total
	return mapped, partial, total


def _passes_common(account: dict, filters: dict) -> bool:
	if _is_disabled(account) and not _truthy(filters.get("include_disabled")):
		return False
	root_types = [clean_text(value) for value in filters.get("root_types") or [] if clean_text(value)]
	if root_types and clean_text(account.get("root_type")) not in root_types:
		return False
	account_types = [clean_text(value) for value in filters.get("account_types") or [] if clean_text(value)]
	if account_types and not _is_group(account) and clean_text(account.get("account_type")) not in account_types:
		return False
	return True


def _passes_status(status: str, filters: dict) -> bool:
	wanted = clean_text(filters.get("status") or "all").casefold()
	if wanted in ("", "all"):
		return True
	return status == wanted


def _passes_search(account: dict, filters: dict, by_name: dict) -> bool:
	query = _search_text(filters)
	if not query:
		return True
	if _text_matches(account, query):
		return True
	parent = account.get("parent_account")
	while parent and parent in by_name:
		if _text_matches(by_name[parent], query):
			return True
		parent = by_name[parent].get("parent_account")
	return False


def _search_text(filters: dict) -> str:
	return clean_text(filters.get("search")).casefold()


def _text_matches(account: dict, query: str) -> bool:
	parts = [
		account.get("name"),
		account.get("account_name"),
		account.get("account_number"),
		account.get("account_type"),
		account.get("root_type"),
	]
	return query in " ".join(clean_text(part) for part in parts).casefold()


def _is_group(account: dict) -> bool:
	return bool(as_int(account.get("is_group")))


def _is_disabled(account: dict) -> bool:
	return bool(as_int(account.get("disabled")))


def _truthy(value) -> bool:
	return bool(as_int(value))


def as_int(value) -> int:
	from frappehero.flags import as_flag

	return as_flag(value)


def _norm(value) -> str:
	return clean_text(value).casefold()
