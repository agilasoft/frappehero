# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for roles, access reviews, defaults, shares, and alerts.

Nothing in this module imports Frappe. Desk pages and the scheduler apply
the results.
"""

import json

from frappehero.flags import as_flag, clean_text

PERM_BITS = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"print",
	"email",
	"share",
	"import",
)

REVIEW_STATUSES = ("Pending", "Confirmed", "Exception", "Stale")
NOTIFY_EVENTS = ("Unmapped Accounts", "Users Without a Group", "Open Access Reviews")


def merge_permissions(standard_rows, custom_rows) -> list[dict]:
	"""Custom DocPerm replaces the standard row for the same key.

	The key is DocType, role, permlevel, and if_owner. The grid the desk
	shows uses permlevel 0 and if_owner 0.
	"""
	merged = {}
	for row in standard_rows or []:
		merged[_perm_key(row)] = dict(row)
	for row in custom_rows or []:
		merged[_perm_key(row)] = dict(row)
	return list(merged.values())


def role_matrix(perms, doctypes, filters=None) -> dict:
	"""DocTypes by role at permlevel 0, if_owner 0.

	By default a DocType appears when any role has a permission on it.
	``missing_read`` keeps DocTypes where no role has read, including
	DocTypes that have no permission row at all.
	"""
	filters = filters or {}
	search = clean_text(filters.get("search")).casefold()
	module = clean_text(filters.get("module"))
	bit = clean_text(filters.get("bit")).casefold()
	if bit not in PERM_BITS:
		bit = ""
	missing_read = as_flag(filters.get("missing_read"))
	role_filter = [clean_text(role) for role in filters.get("roles") or [] if clean_text(role)]

	module_of = {}
	catalog = []
	for item in doctypes or []:
		name = clean_text(item.get("name"))
		if not name:
			continue
		module_of[name] = clean_text(item.get("module"))
		catalog.append(name)

	cells = {}
	roles_seen = []
	for row in _grid_rows(perms):
		doctype_name = _doctype_of(row)
		role = clean_text(row.get("role"))
		if not doctype_name or not role:
			continue
		if role not in roles_seen:
			roles_seen.append(role)
		bucket = cells.setdefault(doctype_name, {}).setdefault(role, _empty_bits())
		for name in PERM_BITS:
			if as_flag(row.get(name)):
				bucket[name] = 1

	if missing_read:
		universe = catalog or list(cells)
		universe = [name for name in universe if not _anyone(cells.get(name), "read")]
	elif catalog:
		universe = [name for name in catalog if name in cells]
	else:
		universe = list(cells)

	rows = []
	for doctype_name in universe:
		module_name = module_of.get(doctype_name, "")
		if module and module_name != module:
			continue
		if search and search not in f"{doctype_name} {module_name}".casefold():
			continue
		role_cells = cells.get(doctype_name, {})
		if bit:
			someone = _anyone(role_cells, bit)
			if missing_read and bit == "read":
				if someone:
					continue
			elif not someone:
				continue
		rows.append(
			{
				"doctype": doctype_name,
				"module": module_name,
				"nobody_read": not _anyone(role_cells, "read"),
				"cells": {role: role_cells.get(role, _empty_bits()) for role in role_filter} if role_filter else role_cells,
			}
		)

	if role_filter:
		roles = role_filter
	else:
		roles = [role for role in roles_seen if any(role in row["cells"] for row in rows)] or roles_seen
	return {"roles": roles, "bits": list(PERM_BITS), "rows": rows}


def diff_roles(perms, role_a, role_b, bits=None) -> list[dict]:
	"""Permission bits that differ between two roles at permlevel 0, if_owner 0."""
	wanted = [bit for bit in (bits or PERM_BITS) if bit in PERM_BITS]
	left = _bits_for_role(perms, role_a)
	right = _bits_for_role(perms, role_b)
	diffs = []
	for doctype_name in sorted(set(left) | set(right)):
		for bit in wanted:
			lval = left.get(doctype_name, {}).get(bit, 0)
			rval = right.get(doctype_name, {}).get(bit, 0)
			if lval != rval:
				diffs.append({"doctype": doctype_name, "bit": bit, "left": lval, "right": rval})
	return diffs


def clone_permission_rows(perms, source_role, new_role) -> list[dict]:
	"""Custom DocPerm payloads that copy one role onto another."""
	source_role = clean_text(source_role)
	new_role = clean_text(new_role)
	copied = []
	seen = set()
	for row in perms or []:
		if clean_text(row.get("role")) != source_role:
			continue
		doctype_name = _doctype_of(row)
		permlevel = int(row.get("permlevel") or 0)
		if_owner = as_flag(row.get("if_owner"))
		key = (doctype_name, permlevel, if_owner)
		if not doctype_name or key in seen:
			continue
		seen.add(key)
		payload = {
			"parent": doctype_name,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": new_role,
			"permlevel": permlevel,
			"if_owner": if_owner,
		}
		for bit in PERM_BITS:
			payload[bit] = as_flag(row.get(bit))
		copied.append(payload)
	return copied


def review_snapshot(members, rules) -> dict:
	"""Stable JSON for the members and rules a reviewer confirmed."""
	member_rows = sorted(
		(
			{"user": clean_text(row.get("user")), "full_name": clean_text(row.get("full_name"))}
			for row in members or []
			if clean_text(row.get("user"))
		),
		key=lambda row: row["user"],
	)
	rule_rows = sorted(
		(
			{
				"reference_doctype": clean_text(row.get("reference_doctype")),
				"for_value": clean_text(row.get("for_value")),
				"apply_to_all_doctypes": as_flag(row.get("apply_to_all_doctypes")),
				"applicable_for": clean_text(row.get("applicable_for")),
				"is_default": as_flag(row.get("is_default")),
				"hide_descendants": as_flag(row.get("hide_descendants")),
			}
			for row in rules or []
			if clean_text(row.get("reference_doctype")) and clean_text(row.get("for_value"))
		),
		key=lambda row: (row["reference_doctype"], row["for_value"], row["applicable_for"]),
	)
	return {
		"members": json.dumps(member_rows, sort_keys=True),
		"rules": json.dumps(rule_rows, sort_keys=True),
		"member_count": len(member_rows),
		"rule_count": len(rule_rows),
	}


def line_state(stored_status, stored_members, stored_rules, current_members, current_rules) -> str:
	"""Confirmed and Exception become Stale when the group snapshot changes."""
	status = clean_text(stored_status) or "Pending"
	if status not in REVIEW_STATUSES:
		status = "Pending"
	changed = str(stored_members or "") != str(current_members or "") or str(stored_rules or "") != str(current_rules or "")
	if status in {"Confirmed", "Exception"} and changed:
		return "Stale"
	return status


def default_conflicts(members, defaults, current) -> list[dict]:
	"""Users whose saved default differs from the set.

	An empty current value is not a conflict. A different value is.
	"""
	rows = []
	for member in members or []:
		user = clean_text(member.get("user"))
		if not user:
			continue
		for item in defaults or []:
			key = clean_text(item.get("default_key") or item.get("key"))
			wanted = clean_text(item.get("default_value") or item.get("value"))
			if not key or not wanted:
				continue
			current_text = clean_text(current.get((user, key)))
			rows.append(
				{
					"user": user,
					"key": key,
					"wanted": wanted,
					"current": current_text,
					"conflict": bool(current_text) and current_text != wanted,
				}
			)
	return rows


def apply_rows(members, defaults) -> list[dict]:
	"""Rows a caller can pass to frappe.defaults.set_user_default."""
	rows = []
	for member in members or []:
		user = clean_text(member.get("user"))
		if not user:
			continue
		for item in defaults or []:
			key = clean_text(item.get("default_key") or item.get("key"))
			value = clean_text(item.get("default_value") or item.get("value"))
			if key and value:
				rows.append({"user": user, "key": key, "value": value})
	return rows


def share_plan(members, shares) -> dict:
	"""Members who still need a DocShare, and members who already have one."""
	wanted = []
	for member in members or []:
		user = clean_text(member.get("user") if isinstance(member, dict) else member)
		if user and user not in wanted:
			wanted.append(user)
	already_users = []
	for share in shares or []:
		user = clean_text(share.get("user") if isinstance(share, dict) else share)
		if user and user not in already_users:
			already_users.append(user)
	already_set = set(already_users)
	return {
		"missing": [user for user in wanted if user not in already_set],
		"already": [user for user in wanted if user in already_set],
	}


def expired_share_names(shares, today) -> list[str]:
	"""DocShare names whose hero_expires_on is before today. Blank dates stay."""
	today_text = str(today or "")
	names = []
	for share in shares or []:
		expires = str(share.get("hero_expires_on") or "")
		name = clean_text(share.get("name"))
		if name and expires and expires < today_text:
			names.append(name)
	return names


def should_send(enabled, last_sent, today) -> bool:
	"""Enabled routes send once per calendar day."""
	if not as_flag(enabled):
		return False
	return str(last_sent or "")[:10] != str(today or "")[:10]


def render_notice(event, facts) -> dict:
	"""Subject and body for one alert. ``facts`` supplies the counts."""
	facts = facts or {}
	count = facts.get("count", 0)
	if event == "Unmapped Accounts":
		map_name = clean_text(facts.get("map"))
		subject = f"Unmapped accounts: {count}"
		body = (
			f"{count} ledger accounts are still unmapped on {map_name}."
			if map_name
			else f"{count} ledger accounts are still unmapped."
		)
	elif event == "Users Without a Group":
		subject = f"Users without a group: {count}"
		body = f"{count} enabled users are not in a permission group."
		names = [clean_text(name) for name in facts.get("users") or [] if clean_text(name)]
		if names:
			body = f"{body} {', '.join(names[:20])}."
	elif event == "Open Access Reviews":
		subject = f"Open access reviews: {count}"
		body = f"{count} access reviews are still open."
		stale = facts.get("stale") or 0
		if stale:
			body = f"{body} {stale} confirmed lines are stale."
	else:
		subject = clean_text(event) or "Frappe Hero"
		body = "Frappe Hero notification."
	return {"subject": subject, "body": body}


def _perm_key(row) -> tuple:
	return (
		_doctype_of(row),
		clean_text(row.get("role")),
		int(row.get("permlevel") or 0),
		as_flag(row.get("if_owner")),
	)


def _doctype_of(row) -> str:
	return clean_text(row.get("parent") or row.get("doctype"))


def _grid_rows(perms):
	return [row for row in perms or [] if int(row.get("permlevel") or 0) == 0 and as_flag(row.get("if_owner")) == 0]


def _empty_bits() -> dict:
	return {name: 0 for name in PERM_BITS}


def _anyone(role_cells, bit) -> bool:
	return any((bits or {}).get(bit) for bits in (role_cells or {}).values())


def _bits_for_role(perms, role) -> dict:
	role = clean_text(role)
	found = {}
	for row in _grid_rows(perms):
		if clean_text(row.get("role")) != role:
			continue
		doctype_name = _doctype_of(row)
		if not doctype_name:
			continue
		bucket = found.setdefault(doctype_name, _empty_bits())
		for bit in PERM_BITS:
			if as_flag(row.get(bit)):
				bucket[bit] = 1
	return found
