# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import escape_html, today

from frappehero.access_desk.logic import (
	PERM_BITS,
	apply_rows,
	clone_permission_rows,
	default_conflicts,
	diff_roles,
	expired_share_names,
	line_state,
	merge_permissions,
	render_notice,
	review_snapshot,
	role_matrix,
	share_plan,
	should_send,
)
from frappehero.accounts_mapping.logic import coverage, status_by_account
from frappehero.flags import as_flag, clean_text, parse_payload
from frappehero.permission_studio.logic import BLOCKED_USERS

PERM_FIELDS = ["parent", "role", "permlevel", "if_owner", *PERM_BITS]
RESERVED_ROLES = {"Administrator", "Guest", "All"}


def send_due() -> list[str]:
	"""Send every enabled route that has not already gone out today."""
	if not frappe.db.table_exists("Hero Notification Route"):
		return []
	sent = []
	current = today()
	for name in frappe.get_all("Hero Notification Route", filters={"enabled": 1}, pluck="name"):
		try:
			if _deliver(frappe.get_doc("Hero Notification Route", name), current):
				sent.append(name)
		except Exception:
			frappe.log_error(title=f"Frappe Hero notification {name}")
	return sent


def clear_expired_shares() -> list[str]:
	"""Delete DocShares whose Frappe Hero end date is before today."""
	if not frappe.db.table_exists("DocShare"):
		return []
	if not frappe.get_meta("DocShare").has_field("hero_expires_on"):
		return []
	current = today()
	rows = frappe.get_all(
		"DocShare",
		filters={"hero_expires_on": ["<", current]},
		fields=["name", "hero_expires_on"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	names = expired_share_names(rows, current)
	for name in names:
		frappe.delete_doc("DocShare", name, ignore_permissions=True, force=True)
	return names


@frappe.whitelist()
def get_role_matrix(filters: str | dict | None = None) -> dict:
	frappe.only_for("System Manager")
	filters = parse_payload(filters, {})
	perms = _merged_perms()
	doctypes = frappe.get_all(
		"DocType",
		filters={"istable": 0},
		fields=["name", "module"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	matrix = role_matrix(perms, doctypes, filters)
	matrix["modules"] = sorted({row.module for row in doctypes if row.module})
	matrix["all_roles"] = frappe.get_all(
		"Role",
		filters={"disabled": 0},
		pluck="name",
		order_by="name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	return matrix


@frappe.whitelist()
def diff_two_roles(role_a: str, role_b: str) -> list:
	frappe.only_for("System Manager")
	return diff_roles(_merged_perms(), role_a, role_b)


@frappe.whitelist()
def clone_role(source_role: str, new_role: str) -> dict:
	frappe.only_for("System Manager")
	source_role = clean_text(source_role)
	new_role = clean_text(new_role)
	if not source_role or not frappe.db.exists("Role", source_role):
		frappe.throw(_("Choose a role to clone."))
	if not new_role:
		frappe.throw(_("New role name is required."))
	if new_role in RESERVED_ROLES or frappe.db.exists("Role", new_role):
		frappe.throw(_("{0} already exists.").format(new_role))
	frappe.get_doc({"doctype": "Role", "role_name": new_role, "desk_access": 1}).insert(ignore_permissions=True)
	created = 0
	for row in clone_permission_rows(_merged_perms(), source_role, new_role):
		frappe.get_doc({"doctype": "Custom DocPerm", **row}).insert(ignore_permissions=True)
		created += 1
	frappe.clear_cache()
	return {"role": new_role, "permissions": created}


@frappe.whitelist()
def toggle_permission(document_type: str, role: str, bit: str, value=1) -> dict:
	frappe.only_for("System Manager")
	document_type = clean_text(document_type)
	role = clean_text(role)
	bit = clean_text(bit).casefold()
	if bit not in PERM_BITS:
		frappe.throw(_("Choose a permission."))
	if not frappe.db.exists("DocType", document_type) or not frappe.db.exists("Role", role):
		frappe.throw(_("Choose a DocType and a role."))
	from frappe.core.page.permission_manager.permission_manager import add, update

	filters = {"parent": document_type, "role": role, "permlevel": 0, "if_owner": 0}
	if not frappe.db.exists("Custom DocPerm", filters) and not frappe.db.exists("DocPerm", filters):
		add(document_type, role, 0)
	update(document_type, role, 0, bit, as_flag(value), 0)
	return {"ok": 1}


@frappe.whitelist()
def list_reviews() -> list:
	frappe.only_for("System Manager")
	reviews = frappe.get_all(
		"Hero Access Review",
		fields=["name", "review_date", "status", "modified"],
		order_by="review_date desc",
		limit_page_length=0,
	)
	for review in reviews:
		review["lines"] = frappe.db.count("Hero Access Review Line", {"parent": review.name})
		review["stale"] = frappe.db.count("Hero Access Review Line", {"parent": review.name, "status": "Stale"})
		review["pending"] = frappe.db.count("Hero Access Review Line", {"parent": review.name, "status": "Pending"})
	return reviews


@frappe.whitelist()
def get_review(name: str) -> dict:
	frappe.only_for("System Manager")
	return _review_payload(frappe.get_doc("Hero Access Review", name))


@frappe.whitelist()
def create_review(review_name: str, review_date: str | None = None) -> dict:
	frappe.only_for("System Manager")
	review_name = clean_text(review_name)
	if not review_name:
		frappe.throw(_("Review name is required."))
	doc = frappe.new_doc("Hero Access Review")
	doc.review_name = review_name
	doc.review_date = review_date or today()
	doc.status = "Open"
	for group_name in frappe.get_all("Hero Permission Group", filters={"enabled": 1}, pluck="name"):
		snap = review_snapshot(_group_members(group_name), _group_rules(group_name))
		doc.append(
			"lines",
			{
				"permission_group": group_name,
				"status": "Pending",
				"member_count": snap["member_count"],
				"rule_count": snap["rule_count"],
				"member_snapshot": snap["members"],
				"rule_snapshot": snap["rules"],
			},
		)
	doc.insert(ignore_permissions=True)
	return _review_payload(doc)


@frappe.whitelist()
def refresh_review(name: str) -> dict:
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Hero Access Review", name)
	changed = False
	for line in doc.lines:
		current = _current_snapshot(line.permission_group)
		status = line_state(line.status, line.member_snapshot, line.rule_snapshot, current["members"], current["rules"])
		if status != line.status:
			line.status = status
			line.member_count = current["member_count"]
			line.rule_count = current["rule_count"]
			changed = True
	if changed:
		doc.save(ignore_permissions=True)
	return _review_payload(doc)


@frappe.whitelist()
def set_line_status(review: str, line_name: str, status: str, notes: str | None = None) -> dict:
	frappe.only_for("System Manager")
	status = clean_text(status)
	if status not in {"Pending", "Confirmed", "Exception"}:
		frappe.throw(_("Choose Pending, Confirmed, or Exception."))
	doc = frappe.get_doc("Hero Access Review", review)
	line = next((row for row in doc.lines if row.name == line_name), None)
	if not line:
		frappe.throw(_("That line is not on this review."))
	current = _current_snapshot(line.permission_group)
	line.status = status
	line.member_snapshot = current["members"]
	line.rule_snapshot = current["rules"]
	line.member_count = current["member_count"]
	line.rule_count = current["rule_count"]
	line.notes = notes if notes is not None else line.notes
	if status in {"Confirmed", "Exception"}:
		line.reviewer = frappe.session.user
		line.confirmed_on = frappe.utils.now()
	else:
		line.reviewer = None
		line.confirmed_on = None
	doc.save(ignore_permissions=True)
	return _review_payload(doc)


@frappe.whitelist()
def set_review_status(name: str, status: str) -> dict:
	frappe.only_for("System Manager")
	status = clean_text(status)
	if status not in {"Open", "Closed"}:
		frappe.throw(_("Status must be Open or Closed."))
	doc = frappe.get_doc("Hero Access Review", name)
	doc.status = status
	doc.save(ignore_permissions=True)
	return _review_payload(doc)


@frappe.whitelist()
def manual_permissions(search: str | None = None) -> list:
	"""User Permissions that Permission Studio does not own."""
	frappe.only_for("System Manager")
	or_filters = None
	if frappe.get_meta("User Permission").has_field("hero_managed"):
		or_filters = [["hero_managed", "=", 0], ["hero_managed", "is", "not set"]]
	rows = frappe.get_all(
		"User Permission",
		or_filters=or_filters,
		fields=["name", "user", "allow", "for_value", "applicable_for", "is_default"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	query = clean_text(search).casefold()
	if not query:
		return rows
	return [
		row
		for row in rows
		if query in " ".join(clean_text(row.get(key)) for key in ("user", "allow", "for_value", "applicable_for")).casefold()
	]


@frappe.whitelist()
def list_default_sets() -> list:
	frappe.only_for("System Manager")
	return [
		_default_payload(frappe.get_doc("Hero Default Set", name))
		for name in frappe.get_all("Hero Default Set", pluck="name", order_by="modified desc")
	]


@frappe.whitelist()
def save_default_set(set_name: str, permission_group: str, values: str | list | None = None, enabled=1) -> dict:
	frappe.only_for("System Manager")
	set_name = clean_text(set_name)
	if not set_name:
		frappe.throw(_("Set name is required."))
	values = parse_payload(values, [])
	if frappe.db.exists("Hero Default Set", set_name):
		doc = frappe.get_doc("Hero Default Set", set_name)
	else:
		doc = frappe.new_doc("Hero Default Set")
		doc.set_name = set_name
	doc.permission_group = permission_group
	doc.enabled = as_flag(enabled)
	doc.set("values", [])
	for row in values:
		doc.append(
			"values",
			{"default_key": row.get("default_key"), "default_value": row.get("default_value")},
		)
	doc.save(ignore_permissions=True)
	return _default_payload(doc)


@frappe.whitelist()
def apply_default_set(name: str) -> dict:
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Hero Default Set", name)
	if not as_flag(doc.enabled):
		frappe.throw(_("Enable the set before applying it."))
	members = _group_members(doc.permission_group)
	defaults = _default_rows(doc)
	applied = apply_rows(members, defaults)
	for row in applied:
		frappe.defaults.set_user_default(row["key"], row["value"], row["user"])
	return {"applied": len(applied), "set": _default_payload(doc)}


@frappe.whitelist()
def inspect_document(doctype: str, docname: str) -> dict:
	frappe.only_for("System Manager")
	doctype = clean_text(doctype)
	docname = clean_text(docname)
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Choose a DocType."))
	if not docname or not frappe.db.exists(doctype, docname):
		frappe.throw(_("{0} {1} was not found.").format(doctype, docname))
	return {
		"doctype": doctype,
		"docname": docname,
		"roles": _roles_with_read(doctype),
		"user_permissions": _user_permissions_for(doctype, docname),
		"shares": _shares_for(doctype, docname),
		"groups": frappe.get_all(
			"Hero Permission Group",
			filters={"enabled": 1},
			fields=["name"],
			order_by="name asc",
			limit_page_length=0,
		),
	}


@frappe.whitelist()
def share_with_group(
	doctype: str,
	docname: str,
	permission_group: str,
	expires_on: str | None = None,
	read=1,
	write=0,
	submit=0,
	share=0,
) -> dict:
	frappe.only_for("System Manager")
	doctype = clean_text(doctype)
	docname = clean_text(docname)
	permission_group = clean_text(permission_group)
	if not frappe.db.exists(doctype, docname):
		frappe.throw(_("{0} {1} was not found.").format(doctype, docname))
	if not frappe.db.exists("Hero Permission Group", permission_group):
		frappe.throw(_("Choose a permission group."))
	expires_on = clean_text(expires_on) or None
	members = _group_members(permission_group)
	existing = _shares_for(doctype, docname)
	plan = share_plan(members, existing)
	created = []
	for user in plan["missing"]:
		result = frappe.share.add(
			doctype,
			docname,
			user=user,
			read=as_flag(read),
			write=as_flag(write),
			submit=as_flag(submit),
			share=as_flag(share),
			everyone=0,
			notify=0,
		)
		share_name = getattr(result, "name", None) or result
		_stamp_share(share_name, permission_group, expires_on)
		created.append({"name": share_name, "user": user})
	return {"created": created, "already": plan["already"]}


@frappe.whitelist()
def list_routes() -> list:
	frappe.only_for("System Manager")
	routes = frappe.get_all(
		"Hero Notification Route",
		fields=["name", "event", "permission_group", "account_map", "enabled", "last_sent", "last_summary"],
		order_by="modified desc",
		limit_page_length=0,
	)
	for route in routes:
		route["recipients"] = len(_recipient_emails(route.permission_group))
	return routes


@frappe.whitelist()
def save_route(
	route_name: str,
	event: str,
	permission_group: str,
	account_map: str | None = None,
	enabled=1,
) -> dict:
	frappe.only_for("System Manager")
	route_name = clean_text(route_name)
	if not route_name:
		frappe.throw(_("Route name is required."))
	if frappe.db.exists("Hero Notification Route", route_name):
		doc = frappe.get_doc("Hero Notification Route", route_name)
	else:
		doc = frappe.new_doc("Hero Notification Route")
		doc.route_name = route_name
	doc.event = event
	doc.permission_group = permission_group
	doc.account_map = account_map
	doc.enabled = as_flag(enabled)
	doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def send_now(route: str) -> dict:
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Hero Notification Route", route)
	current = today()
	if not should_send(doc.enabled, doc.last_sent, current):
		return {"sent": 0, "reason": _("Already sent today.") if as_flag(doc.enabled) else _("This route is disabled.")}
	_deliver(doc, current)
	return {"sent": 1, "summary": doc.last_summary}


def _deliver(doc, current) -> bool:
	if not should_send(doc.enabled, doc.last_sent, current):
		return False
	notice = render_notice(doc.event, _notice_facts(doc))
	emails = _recipient_emails(doc.permission_group)
	if emails:
		frappe.sendmail(
			recipients=emails,
			subject=notice["subject"],
			message=f"<p>{escape_html(notice['body'])}</p>",
			delayed=False,
		)
		summary = notice["body"]
	else:
		summary = _("No recipients on {0}.").format(doc.permission_group)
	doc.db_set("last_sent", current, update_modified=False)
	doc.db_set("last_summary", summary[:140], update_modified=False)
	doc.last_summary = summary[:140]
	return True


def _notice_facts(doc) -> dict:
	if doc.event == "Unmapped Accounts":
		return _unmapped_facts(doc.account_map)
	if doc.event == "Users Without a Group":
		users = _users_without_group()
		return {"count": len(users), "users": [row["full_name"] or row["name"] for row in users]}
	open_names = frappe.get_all("Hero Access Review", filters={"status": "Open"}, pluck="name")
	stale = 0
	if open_names:
		stale = frappe.db.count("Hero Access Review Line", {"parent": ["in", open_names], "status": "Stale"})
	return {"count": len(open_names), "stale": stale}


def _unmapped_facts(map_name) -> dict:
	if not map_name or not frappe.db.exists("Hero Account Map", map_name):
		return {"count": 0, "map": map_name}
	account_map = frappe.get_doc("Hero Account Map", map_name)
	accounts = frappe.get_all(
		"Account",
		filters={"company": account_map.company},
		fields=["name", "is_group", "disabled"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	lines = [row.as_dict() for row in account_map.lines]
	stats = coverage(accounts, status_by_account(accounts, lines, account_map.mapping_type))
	return {"count": stats["unmapped"], "map": account_map.name}


def _users_without_group() -> list:
	enabled_groups = set(frappe.get_all("Hero Permission Group", filters={"enabled": 1}, pluck="name"))
	grouped = {
		row.user
		for row in frappe.get_all(
			"Hero Permission Member",
			filters={"parenttype": "Hero Permission Group"},
			fields=["user", "parent"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if row.user and row.parent in enabled_groups
	}
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", sorted(BLOCKED_USERS)]},
		fields=["name", "full_name", "email"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	return [row for row in users if row.name not in grouped]


def _recipient_emails(group_name) -> list[str]:
	emails = []
	for member in _group_members(group_name):
		user = member.get("user")
		email = frappe.db.get_value("User", user, "email") if user else None
		email = email or user
		if email and "@" in str(email) and email not in emails:
			emails.append(email)
	return emails


def _merged_perms() -> list[dict]:
	return merge_permissions(_perm_rows("DocPerm"), _perm_rows("Custom DocPerm"))


def _perm_rows(doctype_name) -> list:
	if not frappe.db.table_exists(doctype_name):
		return []
	return frappe.get_all(doctype_name, fields=PERM_FIELDS, limit_page_length=0, ignore_permissions=True)


def _review_payload(doc) -> dict:
	lines = []
	for line in doc.lines:
		current = _current_snapshot(line.permission_group)
		lines.append(
			{
				"name": line.name,
				"permission_group": line.permission_group,
				"status": line_state(
					line.status, line.member_snapshot, line.rule_snapshot, current["members"], current["rules"]
				),
				"stored_status": line.status,
				"member_count": current["member_count"],
				"rule_count": current["rule_count"],
				"reviewer": line.reviewer,
				"confirmed_on": line.confirmed_on,
				"notes": line.notes,
				"members": json.loads(current["members"] or "[]"),
				"rules": json.loads(current["rules"] or "[]"),
			}
		)
	return {
		"name": doc.name,
		"review_name": doc.review_name,
		"review_date": doc.review_date,
		"status": doc.status,
		"notes": doc.notes,
		"lines": lines,
	}


def _current_snapshot(group_name) -> dict:
	if not group_name or not frappe.db.exists("Hero Permission Group", group_name):
		return {"members": "[]", "rules": "[]", "member_count": 0, "rule_count": 0}
	return review_snapshot(_group_members(group_name), _group_rules(group_name))


def _group_members(group_name) -> list:
	if not group_name:
		return []
	return frappe.get_all(
		"Hero Permission Member",
		filters={"parent": group_name, "parenttype": "Hero Permission Group"},
		fields=["user", "full_name"],
		limit_page_length=0,
		ignore_permissions=True,
	)


def _group_rules(group_name) -> list:
	if not group_name:
		return []
	return frappe.get_all(
		"Hero Permission Rule",
		filters={"parent": group_name, "parenttype": "Hero Permission Group"},
		fields=[
			"reference_doctype",
			"for_value",
			"apply_to_all_doctypes",
			"applicable_for",
			"is_default",
			"hide_descendants",
		],
		limit_page_length=0,
		ignore_permissions=True,
	)


def _default_payload(doc) -> dict:
	members = _group_members(doc.permission_group)
	defaults = _default_rows(doc)
	current = {}
	for member in members:
		user = member.get("user")
		for item in defaults:
			current[(user, item["default_key"])] = frappe.defaults.get_user_default(item["default_key"], user) or ""
	conflicts = default_conflicts(members, defaults, current)
	return {
		"name": doc.name,
		"permission_group": doc.permission_group,
		"enabled": doc.enabled,
		"values": defaults,
		"conflicts": conflicts,
		"conflict_count": sum(1 for row in conflicts if row["conflict"]),
	}


def _default_rows(doc) -> list[dict]:
	return [{"default_key": row.default_key, "default_value": row.default_value} for row in doc.values]


def _roles_with_read(doctype_name) -> list[dict]:
	found = []
	seen = set()
	for row in _merged_perms():
		parent = clean_text(row.get("parent"))
		if parent != doctype_name or int(row.get("permlevel") or 0) != 0 or not as_flag(row.get("read")):
			continue
		role = clean_text(row.get("role"))
		if_owner = as_flag(row.get("if_owner"))
		key = (role, if_owner)
		if not role or key in seen:
			continue
		seen.add(key)
		found.append({"role": role, "if_owner": if_owner})
	return found


def _user_permissions_for(doctype_name, docname) -> list:
	meta = frappe.get_meta(doctype_name)
	link_targets = {df.options for df in meta.fields if df.fieldtype == "Link" and df.options}
	rows = frappe.get_all(
		"User Permission",
		filters={"for_value": docname},
		fields=["name", "user", "allow", "for_value", "applicable_for", "apply_to_all_doctypes", "is_default"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	kept = []
	for row in rows:
		if row.allow in link_targets or row.applicable_for == doctype_name or as_flag(row.apply_to_all_doctypes):
			kept.append(row)
	return kept


def _shares_for(doctype_name, docname) -> list:
	fields = ["name", "user", "read", "write", "submit", "share", "everyone"]
	meta = frappe.get_meta("DocShare")
	for fieldname in ("hero_expires_on", "hero_permission_group"):
		if meta.has_field(fieldname):
			fields.append(fieldname)
	return frappe.get_all(
		"DocShare",
		filters={"share_doctype": doctype_name, "share_name": docname},
		fields=fields,
		limit_page_length=0,
		ignore_permissions=True,
	)


def _stamp_share(share_name, permission_group, expires_on):
	meta = frappe.get_meta("DocShare")
	values = {}
	if meta.has_field("hero_permission_group"):
		values["hero_permission_group"] = permission_group
	if meta.has_field("hero_expires_on"):
		values["hero_expires_on"] = expires_on
	if values and share_name:
		frappe.db.set_value("DocShare", share_name, values)
