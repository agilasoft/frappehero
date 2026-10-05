# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappehero.accounts_mapping.logic import (
	ROOT_TYPES,
	coverage,
	index_lines,
	status_by_account,
	suggest_mappings,
	unmapped_rows,
	visible_tree,
)
from frappehero.flags import as_flag, clean_text, parse_payload

ACCOUNT_FIELDS = [
	"name",
	"account_name",
	"account_number",
	"parent_account",
	"is_group",
	"root_type",
	"report_type",
	"account_type",
	"disabled",
	"lft",
]


@frappe.whitelist()
def get_mapper_state(
	company: str | None = None,
	map_name: str | None = None,
	filters: str | dict | None = None,
) -> dict:
	"""Company chart, the selected map, and the accounts that match the filters."""
	_allow()
	_require_accounts()
	filters = parse_payload(filters, {})
	companies = frappe.get_all(
		"Company",
		pluck="name",
		order_by="name asc",
		limit_page_length=0,
		ignore_permissions=True,
	)
	company = clean_text(company) or frappe.defaults.get_user_default("Company") or (companies[0] if companies else "")
	maps = []
	if company:
		maps = frappe.get_all(
			"Hero Account Map",
			filters={"company": company},
			fields=[
				"name",
				"mapping_type",
				"target_company",
				"enabled",
				"coverage_percent",
				"mapped_count",
				"partial_count",
				"unmapped_count",
				"leaf_count",
			],
			order_by="name asc",
			limit_page_length=0,
		)
	selected = _selected_map(map_name, company, maps)
	state = {
		"companies": companies,
		"company": company,
		"maps": maps,
		"map": None,
		"tree": [],
		"coverage": {"mapped": 0, "partial": 0, "unmapped": 0, "total": 0, "percent": 0},
		"account_types": [],
		"root_types": list(ROOT_TYPES),
	}
	if not selected:
		return state
	accounts = _account_rows(selected.company)
	lines = [row.as_dict() for row in selected.lines]
	status = status_by_account(accounts, lines, selected.mapping_type)
	tree = visible_tree(accounts, status, filters)
	_attach_lines(tree, index_lines(lines))
	state.update(
		{
			"map": _public_map(selected),
			"tree": tree,
			"coverage": coverage(accounts, status),
			"account_types": sorted({clean_text(row.account_type) for row in accounts if clean_text(row.account_type)}),
		}
	)
	return state


@frappe.whitelist()
def create_map(
	map_name: str,
	company: str,
	mapping_type: str,
	target_company: str | None = None,
	description: str | None = None,
) -> dict:
	_allow()
	doc = frappe.get_doc(
		{
			"doctype": "Hero Account Map",
			"map_name": clean_text(map_name),
			"company": clean_text(company),
			"mapping_type": clean_text(mapping_type),
			"target_company": clean_text(target_company) or None,
			"description": description or "",
			"enabled": 1,
		}
	)
	doc.insert()
	return {"name": doc.name}


@frappe.whitelist()
def update_map(
	name: str,
	description: str | None = None,
	enabled: int | str = 1,
	target_company: str | None = None,
) -> dict:
	_allow()
	doc = frappe.get_doc("Hero Account Map", name)
	doc.description = description or ""
	doc.enabled = as_flag(enabled)
	if doc.mapping_type == "Another Company":
		doc.target_company = clean_text(target_company) or doc.target_company
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def delete_map(name: str) -> dict:
	_allow()
	frappe.delete_doc("Hero Account Map", name)
	return {"name": name}


@frappe.whitelist()
def set_mappings(map_name: str, rows: str | list) -> dict:
	"""Create or update lines. Only fields present on each row are written."""
	_allow()
	doc = frappe.get_doc("Hero Account Map", map_name)
	by_source = {row.source_account: row for row in doc.lines}
	writable = ("target_account", "external_code", "external_name", "reporting_group", "notes")
	for item in parse_payload(rows, []):
		source = clean_text(item.get("source_account"))
		if not source:
			continue
		line = by_source.get(source)
		if line is None:
			line = doc.append("lines", {"source_account": source})
			by_source[source] = line
		for fieldname in writable:
			if fieldname not in item:
				continue
			value = item.get(fieldname)
			if fieldname == "notes":
				line.set(fieldname, (value or "").strip() or None)
			else:
				line.set(fieldname, clean_text(value) or None)
	doc.save()
	return {"name": doc.name, "lines": len(doc.lines)}


@frappe.whitelist()
def clear_mappings(map_name: str, source_accounts: str | list) -> dict:
	_allow()
	doc = frappe.get_doc("Hero Account Map", map_name)
	wanted = {clean_text(name) for name in parse_payload(source_accounts, []) if clean_text(name)}
	for line in list(doc.lines):
		if line.source_account in wanted:
			doc.remove(line)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def suggest(map_name: str) -> list:
	"""Suggest targets for ledger accounts that are not mapped yet."""
	_allow()
	doc = frappe.get_doc("Hero Account Map", map_name)
	accounts = _account_rows(doc.company)
	lines = [row.as_dict() for row in doc.lines]
	status = status_by_account(accounts, lines, doc.mapping_type)
	already = {name for name, state in status.items() if state == "mapped"}
	candidates = []
	if doc.mapping_type == "Another Company" and doc.target_company:
		candidates = _account_rows(doc.target_company)
	return suggest_mappings(accounts, candidates, doc.mapping_type, already)


def unmapped_account_rows(map_name: str, filters: dict | None = None) -> list[dict]:
	_allow()
	doc = frappe.get_doc("Hero Account Map", map_name)
	return unmapped_rows(_account_rows(doc.company), [row.as_dict() for row in doc.lines], doc.mapping_type, filters or {})


def _allow():
	frappe.only_for(["System Manager", "Accounts Manager"])


def _require_accounts():
	if frappe.db.table_exists("Account") and frappe.db.table_exists("Company"):
		return
	frappe.throw(
		_("Account Mapper needs ERPNext, because it reads the chart of accounts."),
		title=_("ERPNext required"),
	)


def _selected_map(map_name: str | None, company: str, maps: list[dict]):
	map_name = clean_text(map_name)
	if map_name and frappe.db.exists("Hero Account Map", map_name):
		doc = frappe.get_doc("Hero Account Map", map_name)
		if not company or doc.company == company:
			return doc
	if maps:
		return frappe.get_doc("Hero Account Map", maps[0].name)
	return None


def _account_rows(company: str) -> list[dict]:
	if not company:
		return []
	return frappe.get_all(
		"Account",
		filters={"company": company},
		fields=ACCOUNT_FIELDS,
		order_by="lft asc",
		limit_page_length=0,
		ignore_permissions=True,
	)


def _public_map(doc) -> dict:
	return {
		"name": doc.name,
		"company": doc.company,
		"mapping_type": doc.mapping_type,
		"target_company": doc.target_company,
		"description": doc.description or "",
		"enabled": doc.enabled,
		"coverage_percent": doc.coverage_percent or 0,
	}


def _attach_lines(nodes: list[dict], lines_by_source: dict):
	for node in nodes:
		line = lines_by_source.get(node["name"])
		node["line"] = _public_line(line) if line else None
		_attach_lines(node.get("children") or [], lines_by_source)


def _public_line(line: dict) -> dict:
	return {
		"target_account": line.get("target_account"),
		"external_code": line.get("external_code"),
		"external_name": line.get("external_name"),
		"reporting_group": line.get("reporting_group"),
		"notes": line.get("notes"),
		"status": line.get("status"),
	}
