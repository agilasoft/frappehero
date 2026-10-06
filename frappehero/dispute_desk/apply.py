# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Apply a dispute to invoice actions, dunning, and holds on a site."""

import frappe

from frappehero.dispute_desk.logic import HOLD_FIELDS, invoice_link_for
from frappehero.flags import as_flag, clean_text


def collect_actions(sales_invoice) -> list[dict]:
	invoice = clean_text(sales_invoice)
	if not invoice:
		return []
	actions = _hero_actions(invoice)
	actions.extend(_hold_actions(invoice))
	actions.extend(_dunning_actions(invoice))
	return actions


def apply_releases(dispute) -> None:
	"""Deactivate recorded actions. Submitted documents are not cancelled."""
	for row in dispute.releases or []:
		_deactivate_action(row, dispute.name)
		_resolve_dunning(row)
		_clear_hold(row)


def sync_invoice_dispute(sales_invoice) -> None:
	invoice = clean_text(sales_invoice)
	if not invoice or not frappe.db.exists("Sales Invoice", invoice):
		return
	meta = frappe.get_meta("Sales Invoice")
	if not meta.has_field("hero_dispute"):
		return
	disputes = frappe.get_all(
		"Hero Dispute",
		filters={"sales_invoice": invoice},
		fields=["name", "sales_invoice", "status"],
		limit_page_length=0,
	)
	values = invoice_link_for(disputes, invoice)
	if not meta.has_field("hero_dispute_status"):
		values.pop("hero_dispute_status", None)
	frappe.db.set_value("Sales Invoice", invoice, values, update_modified=False)


def _hero_actions(sales_invoice) -> list[dict]:
	if not frappe.db.table_exists("Hero Invoice Action"):
		return []
	rows = frappe.get_all(
		"Hero Invoice Action",
		filters={"sales_invoice": sales_invoice},
		fields=["name", "sales_invoice", "action_kind", "source_doctype", "source_name", "state", "active"],
		limit_page_length=0,
	)
	return [
		{
			"sales_invoice": row.sales_invoice,
			"kind": row.action_kind,
			"source_doctype": row.source_doctype,
			"source_name": row.source_name,
			"state": row.state,
			"active": row.active,
			"invoice_action": row.name,
		}
		for row in rows
	]


def _hold_actions(sales_invoice) -> list[dict]:
	if not frappe.db.exists("Sales Invoice", sales_invoice):
		return []
	meta = frappe.get_meta("Sales Invoice")
	doc = frappe.get_doc("Sales Invoice", sales_invoice)
	actions = []
	for fieldname in HOLD_FIELDS:
		if meta.has_field(fieldname) and as_flag(doc.get(fieldname)):
			actions.append(
				{
					"sales_invoice": sales_invoice,
					"kind": "Hold",
					"source_doctype": "Sales Invoice",
					"source_name": sales_invoice,
					"state": fieldname,
					"active": 1,
				}
			)
	return actions


def _dunning_actions(sales_invoice) -> list[dict]:
	if not frappe.db.table_exists("Dunning"):
		return []
	meta = frappe.get_meta("Dunning")
	names = set()
	if meta.has_field("sales_invoice"):
		names.update(
			frappe.get_all(
				"Dunning",
				filters={"sales_invoice": sales_invoice, "docstatus": 1},
				pluck="name",
			)
		)
	for field in meta.fields:
		if field.fieldtype != "Table" or not field.options:
			continue
		if not frappe.db.table_exists(field.options):
			continue
		child = frappe.get_meta(field.options)
		if not child.has_field("sales_invoice"):
			continue
		names.update(
			frappe.get_all(
				field.options,
				filters={"sales_invoice": sales_invoice, "parenttype": "Dunning"},
				pluck="parent",
			)
		)
	actions = []
	for name in sorted(names):
		if not frappe.db.exists("Dunning", name):
			continue
		docstatus = frappe.db.get_value("Dunning", name, "docstatus")
		if int(docstatus or 0) != 1:
			continue
		status = ""
		if meta.has_field("status"):
			status = clean_text(frappe.db.get_value("Dunning", name, "status"))
			if status in {"Resolved", "Cancelled"}:
				continue
		actions.append(
			{
				"sales_invoice": sales_invoice,
				"kind": "Dunning",
				"source_doctype": "Dunning",
				"source_name": name,
				"state": status or "Unresolved",
				"active": 1,
			}
		)
	return actions


def _deactivate_action(row, dispute_name) -> None:
	name = clean_text(row.invoice_action)
	if not name or not frappe.db.exists("Hero Invoice Action", name):
		return
	frappe.db.set_value(
		"Hero Invoice Action",
		name,
		{"active": 0, "dispute": dispute_name},
		update_modified=True,
	)


def _resolve_dunning(row) -> None:
	if clean_text(row.source_doctype) != "Dunning" or not clean_text(row.source_name):
		return
	if not frappe.db.exists("Dunning", row.source_name):
		return
	meta = frappe.get_meta("Dunning")
	if not meta.has_field("status"):
		return
	status = clean_text(frappe.db.get_value("Dunning", row.source_name, "status"))
	if status in {"Resolved", "Cancelled"}:
		return
	frappe.db.set_value("Dunning", row.source_name, "status", "Resolved", update_modified=True)


def _clear_hold(row) -> None:
	if clean_text(row.action_kind) != "Hold":
		return
	fieldname = clean_text(row.previous_state)
	if fieldname not in HOLD_FIELDS or clean_text(row.source_doctype) != "Sales Invoice":
		return
	invoice = clean_text(row.source_name)
	if not invoice or not frappe.db.exists("Sales Invoice", invoice):
		return
	if not frappe.get_meta("Sales Invoice").has_field(fieldname):
		return
	frappe.db.set_value("Sales Invoice", invoice, fieldname, 0, update_modified=False)
