# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappehero.finance_desk.logic import (
	DIMENSIONS,
	can_create_journal,
	filter_dimension_rows,
	filter_named_rows,
	group_tax_map,
	items_without_tax,
	match_opening_lines,
	parse_trial_balance,
	summarize_dimensions,
)
from frappehero.flags import as_flag, clean_text, parse_payload


def _finance():
	frappe.only_for(["System Manager", "Accounts Manager"])


@frappe.whitelist()
def get_dimension_coverage(company: str, dimension: str, status: str | None = None, search: str | None = None) -> dict:
	_finance()
	company = clean_text(company)
	dimension = clean_text(dimension)
	if dimension not in DIMENSIONS:
		frappe.throw(_("Choose Cost Center, Project, or Branch."))
	if not company:
		frappe.throw(_("Company is required."))
	fieldname = {"Cost Center": "cost_center", "Project": "project", "Branch": "branch"}[dimension]
	supported = bool(frappe.db.table_exists("GL Entry") and frappe.get_meta("GL Entry").has_field(fieldname))
	aggregates = _gl_aggregates(company, fieldname) if supported else []
	by_account = {row.account: row for row in aggregates}
	accounts = []
	if frappe.db.table_exists("Account"):
		accounts = frappe.get_all(
			"Account",
			filters={"company": company, "is_group": 0},
			fields=["name", "account_name", "account_number"],
			limit_page_length=0,
			ignore_permissions=True,
		)
	combined = []
	seen = set()
	for account in accounts:
		seen.add(account.name)
		stats = by_account.get(account.name)
		combined.append(
			{
				"account": account.name,
				"account_name": account.account_name,
				"account_number": account.account_number,
				"total": int(stats.total or 0) if stats else 0,
				"missing": int(stats.missing or 0) if stats else 0,
			}
		)
	for account_name, stats in by_account.items():
		if account_name in seen:
			continue
		combined.append(
			{
				"account": account_name,
				"account_name": account_name,
				"total": int(stats.total or 0),
				"missing": int(stats.missing or 0),
			}
		)
	summary = summarize_dimensions(combined)
	defaults = {
		row.account: row
		for row in frappe.get_all(
			"Hero Dimension Default",
			filters={"company": company, "dimension": dimension},
			fields=["name", "account", "default_value", "apply_on_new_entries"],
			limit_page_length=0,
		)
	}
	for row in summary["rows"]:
		row["default"] = defaults.get(row["account"])
	summary["rows"] = filter_dimension_rows(summary["rows"], status, search)
	summary["supported"] = supported
	summary["company"] = company
	summary["dimension"] = dimension
	return summary


@frappe.whitelist()
def set_dimension_default(company: str, dimension: str, account: str, default_value: str, apply_on_new_entries=0) -> dict:
	_finance()
	company = clean_text(company)
	dimension = clean_text(dimension)
	account = clean_text(account)
	existing = frappe.db.get_value(
		"Hero Dimension Default",
		{"company": company, "dimension": dimension, "account": account},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Hero Dimension Default", existing)
	else:
		doc = frappe.new_doc("Hero Dimension Default")
		doc.company = company
		doc.dimension = dimension
		doc.account = account
	doc.default_value = default_value
	doc.apply_on_new_entries = as_flag(apply_on_new_entries)
	doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def clear_dimension_default(name: str) -> dict:
	_finance()
	if name and frappe.db.exists("Hero Dimension Default", name):
		frappe.delete_doc("Hero Dimension Default", name, ignore_permissions=True)
	return {"ok": 1}


@frappe.whitelist()
def get_tax_state(company: str, search: str | None = None) -> dict:
	_finance()
	company = clean_text(company)
	if not company:
		frappe.throw(_("Company is required."))
	allowed = set(
		frappe.get_all("Item Tax Template", filters={"company": company}, pluck="name", limit_page_length=0) or []
	)
	groups = frappe.get_all(
		"Item Group",
		fields=["name", "parent_item_group"],
		order_by="lft asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	templates_by_group = {}
	for row in _item_tax_rows("Item Group"):
		if row.item_tax_template in allowed:
			templates_by_group.setdefault(row.parent, []).append(row.item_tax_template)
	for group in groups:
		group["templates"] = templates_by_group.get(group.name, [])
	mapped_groups = group_tax_map(groups)
	own = {}
	for row in _item_tax_rows("Item"):
		if row.item_tax_template in allowed and row.parent not in own:
			own[row.parent] = row.item_tax_template
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0},
		fields=["name", "item_name", "item_group"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for item in items:
		item["own_template"] = own.get(item.name)
	missing_items = items_without_tax(items, mapped_groups)
	return {
		"company": company,
		"templates": sorted(allowed),
		"groups": filter_named_rows(mapped_groups, search, ("name", "template", "parent_item_group", "status")),
		"items": filter_named_rows(missing_items, search, ("name", "item_name", "item_group")),
		"unmapped_groups": sum(1 for row in mapped_groups if row["status"] == "unmapped"),
		"mapped_groups": sum(1 for row in mapped_groups if row["status"] == "mapped"),
	}


@frappe.whitelist()
def assign_group_templates(item_groups: str | list, item_tax_template: str) -> dict:
	_finance()
	item_tax_template = clean_text(item_tax_template)
	if not item_tax_template or not frappe.db.exists("Item Tax Template", item_tax_template):
		frappe.throw(_("Choose an item tax template."))
	names = [clean_text(name) for name in parse_payload(item_groups, []) if clean_text(name)]
	updated = []
	for name in names:
		if _assign_template(name, item_tax_template):
			updated.append(name)
	return {"updated": updated}


@frappe.whitelist()
def clear_group_template(item_group: str, company: str) -> dict:
	_finance()
	item_group = clean_text(item_group)
	company = clean_text(company)
	allowed = set(frappe.get_all("Item Tax Template", filters={"company": company}, pluck="name") or [])
	doc = frappe.get_doc("Item Group", item_group)
	kept = [row for row in doc.taxes if row.item_tax_template not in allowed]
	doc.set("taxes", [])
	for row in kept:
		doc.append("taxes", {"item_tax_template": row.item_tax_template, "tax_category": row.tax_category})
	doc.save(ignore_permissions=True)
	return {"ok": 1}


@frappe.whitelist()
def list_opening_batches(company: str | None = None) -> list:
	_finance()
	filters = {"company": company} if clean_text(company) else None
	names = frappe.get_all("Hero Opening Batch", filters=filters, pluck="name", order_by="modified desc")
	return [_batch_summary(frappe.get_doc("Hero Opening Batch", name), include_lines=False) for name in names]


@frappe.whitelist()
def get_opening_batch(name: str) -> dict:
	_finance()
	return _batch_summary(frappe.get_doc("Hero Opening Batch", name), include_lines=True)


@frappe.whitelist()
def create_opening_batch(batch_name: str, company: str, posting_date: str, purpose: str = "Opening Entry") -> dict:
	_finance()
	doc = frappe.new_doc("Hero Opening Batch")
	doc.batch_name = batch_name
	doc.company = company
	doc.posting_date = posting_date
	doc.purpose = purpose or "Opening Entry"
	doc.status = "Draft"
	doc.insert(ignore_permissions=True)
	return _batch_summary(doc, include_lines=True)


@frappe.whitelist()
def import_opening_text(batch: str, text: str) -> dict:
	_finance()
	doc = frappe.get_doc("Hero Opening Batch", batch)
	if doc.journal_entry or doc.status == "Journal Created":
		frappe.throw(_("This batch already has a journal entry."))
	parsed = parse_trial_balance(text)
	if not parsed:
		frappe.throw(_("No lines found. Paste account number, account name, debit, and credit."))
	accounts = frappe.get_all(
		"Account",
		filters={"company": doc.company},
		fields=["name", "account_name", "account_number", "is_group", "disabled"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	doc.set("lines", [])
	for row in match_opening_lines(parsed, accounts):
		doc.append("lines", {key: value for key, value in row.items() if value is not None})
	doc.save(ignore_permissions=True)
	return _batch_summary(doc, include_lines=True)


@frappe.whitelist()
def set_opening_match(batch: str, line_name: str, account: str | None = None) -> dict:
	_finance()
	doc = frappe.get_doc("Hero Opening Batch", batch)
	if doc.journal_entry:
		frappe.throw(_("This batch already has a journal entry."))
	line = next((row for row in doc.lines if row.name == line_name), None)
	if not line:
		frappe.throw(_("That line is not on this batch."))
	account = clean_text(account)
	if account:
		line.matched_account = account
		line.match_status = "Matched"
		line.match_reason = "Chosen on the batch"
	else:
		line.matched_account = None
		line.match_status = "Unmatched"
		line.match_reason = "Cleared on the batch"
	doc.save(ignore_permissions=True)
	return _batch_summary(doc, include_lines=True)


@frappe.whitelist()
def create_opening_journal(batch: str) -> dict:
	_finance()
	doc = frappe.get_doc("Hero Opening Batch", batch)
	if doc.journal_entry:
		frappe.throw(_("This batch already has a journal entry."))
	lines = [row.as_dict() for row in doc.lines]
	if not can_create_journal(lines):
		frappe.throw(_("Match every line and balance debit and credit before creating the journal."))
	payload = {
		"doctype": "Journal Entry",
		"voucher_type": "Opening Entry" if doc.purpose == "Opening Entry" else "Journal Entry",
		"company": doc.company,
		"posting_date": doc.posting_date,
		"user_remark": _("Frappe Hero {0}: {1}").format(doc.purpose, doc.name),
		"accounts": [
			{
				"account": line.matched_account,
				"debit_in_account_currency": line.debit,
				"credit_in_account_currency": line.credit,
			}
			for line in doc.lines
		],
	}
	if doc.purpose == "Opening Entry" and frappe.get_meta("Journal Entry").has_field("is_opening"):
		payload["is_opening"] = "Yes"
	journal = frappe.get_doc(payload)
	journal.insert(ignore_permissions=True)
	doc.journal_entry = journal.name
	doc.status = "Journal Created"
	doc.save(ignore_permissions=True)
	return {"journal_entry": journal.name, "batch": _batch_summary(doc, include_lines=True)}


def _gl_aggregates(company, fieldname):
	if fieldname == "cost_center":
		return frappe.db.sql(
			"""
			select account, count(*) as total,
				sum(case when coalesce(cost_center, '') = '' then 1 else 0 end) as missing
			from `tabGL Entry`
			where company = %s and coalesce(is_cancelled, 0) = 0
			group by account
			""",
			(company,),
			as_dict=True,
		)
	if fieldname == "project":
		return frappe.db.sql(
			"""
			select account, count(*) as total,
				sum(case when coalesce(project, '') = '' then 1 else 0 end) as missing
			from `tabGL Entry`
			where company = %s and coalesce(is_cancelled, 0) = 0
			group by account
			""",
			(company,),
			as_dict=True,
		)
	if fieldname == "branch":
		return frappe.db.sql(
			"""
			select account, count(*) as total,
				sum(case when coalesce(branch, '') = '' then 1 else 0 end) as missing
			from `tabGL Entry`
			where company = %s and coalesce(is_cancelled, 0) = 0
			group by account
			""",
			(company,),
			as_dict=True,
		)
	return []


def _item_tax_rows(parenttype):
	if not frappe.db.table_exists("Item Tax"):
		return []
	return frappe.get_all(
		"Item Tax",
		filters={"parenttype": parenttype},
		fields=["parent", "item_tax_template"],
		limit_page_length=0,
		ignore_permissions=True,
	)


def _assign_template(item_group, item_tax_template) -> bool:
	if not frappe.db.exists("Item Group", item_group):
		return False
	doc = frappe.get_doc("Item Group", item_group)
	if any(row.item_tax_template == item_tax_template for row in doc.taxes):
		return False
	doc.append("taxes", {"item_tax_template": item_tax_template})
	doc.save(ignore_permissions=True)
	return True


def _batch_summary(doc, include_lines: bool) -> dict:
	lines = [row.as_dict() for row in doc.lines]
	payload = {
		"name": doc.name,
		"company": doc.company,
		"posting_date": doc.posting_date,
		"purpose": doc.purpose,
		"status": doc.status,
		"journal_entry": doc.journal_entry,
		"debit_total": doc.debit_total,
		"credit_total": doc.credit_total,
		"difference": doc.difference,
		"line_count": len(lines),
		"unmatched": sum(1 for row in lines if row.get("match_status") != "Matched"),
		"can_create": bool(can_create_journal(lines) and not doc.journal_entry),
	}
	if include_lines:
		payload["lines"] = lines
	return payload
