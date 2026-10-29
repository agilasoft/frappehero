# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Apply a dispute to invoice actions, dunning, and holds on a site."""

import frappe
from frappe import _

from frappehero.dispute_desk.logic import HOLD_FIELDS, invoice_link_for, sales_invoice_dispute_tab
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


def load_invoice_dispute_tab(
	sales_invoice=None,
	customer=None,
	company=None,
	is_return=None,
	return_against=None,
) -> dict:
	"""Credit position and holds for one Sales Invoice form.

	A submitted invoice uses its own customer, company, and credit-note flags.
	A draft uses the values on the form. Holds are read with the invoice, so a
	reader of the invoice can see them.
	"""
	invoice = clean_text(sales_invoice)
	doc = None
	if invoice and frappe.db.exists("Sales Invoice", invoice):
		if not frappe.has_permission("Sales Invoice", "read", invoice):
			frappe.throw(_("Not permitted to read this invoice."), frappe.PermissionError)
		doc = frappe.get_doc("Sales Invoice", invoice)
		if int(doc.docstatus or 0) == 1:
			customer = doc.customer
			company = doc.company
			is_return = doc.get("is_return")
			return_against = doc.get("return_against")
		else:
			customer = clean_text(customer) or doc.customer
			company = clean_text(company) or doc.company
			if is_return is None:
				is_return = doc.get("is_return")
			if not clean_text(return_against):
				return_against = doc.get("return_against")
	else:
		invoice = ""
		customer = clean_text(customer)
		company = clean_text(company)
		if customer and not _can_read("Customer", customer):
			customer = ""
			company = ""
	limit, bypass = _credit_limit(customer, company)
	return sales_invoice_dispute_tab(
		customer=customer,
		company=company,
		currency=_company_currency(company),
		credit_limit=limit,
		outstanding=_outstanding(customer, company),
		bypass_credit_limit_check=bypass,
		is_return=is_return,
		return_against=return_against,
		credit_notes=_credit_notes(invoice),
		holds=_tab_holds(doc, invoice),
		sales_invoice=invoice,
	)


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


def _can_read(doctype, name) -> bool:
	return bool(name) and bool(frappe.has_permission(doctype, "read", name))


def _credit_limit(customer, company):
	"""Return ``(limit or None, bypass)`` for this customer and company.

	A customer row wins. Otherwise the company default is used. Zero means
	no limit, matching ERPNext.
	"""
	if not customer or not company:
		return None, 0
	limit = None
	bypass = 0
	if frappe.db.table_exists("Customer Credit Limit"):
		row = frappe.db.get_value(
			"Customer Credit Limit",
			{"parent": customer, "parenttype": "Customer", "company": company},
			["credit_limit", "bypass_credit_limit_check"],
			as_dict=True,
		)
		if row and row.credit_limit:
			limit = row.credit_limit
			bypass = row.bypass_credit_limit_check
	if limit is None and frappe.db.exists("Company", company):
		meta = frappe.get_meta("Company")
		if meta.has_field("credit_limit"):
			company_limit = frappe.db.get_value("Company", company, "credit_limit")
			if company_limit:
				limit = company_limit
	return limit, bypass


def _outstanding(customer, company) -> float:
	if not customer or not company:
		return 0.0
	try:
		from erpnext.selling.doctype.customer.customer import get_customer_outstanding
	except ImportError:
		return _invoice_outstanding(customer, company)
	return float(get_customer_outstanding(customer, company) or 0)


def _invoice_outstanding(customer, company) -> float:
	if not frappe.db.table_exists("Sales Invoice"):
		return 0.0
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "customer": customer, "company": company},
		fields=["outstanding_amount"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	return round(sum(float(row.outstanding_amount or 0) for row in rows), 2)


def _company_currency(company) -> str:
	if not company or not frappe.db.exists("Company", company):
		return ""
	return clean_text(frappe.db.get_value("Company", company, "default_currency"))


def _credit_notes(sales_invoice) -> list[dict]:
	invoice = clean_text(sales_invoice)
	if not invoice or not frappe.db.table_exists("Sales Invoice"):
		return []
	meta = frappe.get_meta("Sales Invoice")
	if not meta.has_field("is_return") or not meta.has_field("return_against"):
		return []
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "is_return": 1, "return_against": invoice},
		fields=["name", "posting_date", "grand_total", "outstanding_amount", "currency"],
		limit_page_length=0,
	)
	return [dict(row) for row in rows]


def _tab_holds(doc, sales_invoice) -> list[dict]:
	rows = []
	if doc:
		meta = frappe.get_meta("Sales Invoice")
		for fieldname in HOLD_FIELDS:
			if meta.has_field(fieldname) and as_flag(doc.get(fieldname)):
				rows.append(
					{
						"fieldname": fieldname,
						"active": 1,
						"source_name": doc.name,
					}
				)
	invoice = clean_text(sales_invoice)
	if not invoice:
		return rows
	rows.extend(_action_holds(invoice))
	rows.extend(_released_holds(invoice))
	return rows


def _action_holds(sales_invoice) -> list[dict]:
	if not frappe.db.table_exists("Hero Invoice Action"):
		return []
	found = frappe.get_all(
		"Hero Invoice Action",
		filters={"sales_invoice": sales_invoice},
		fields=["name", "action_kind", "source_doctype", "source_name", "state", "active", "dispute"],
		ignore_permissions=True,
		limit_page_length=0,
	)
	return [
		{
			"kind": row.action_kind,
			"source_doctype": row.source_doctype,
			"source_name": row.source_name or row.name,
			"state": row.state,
			"active": row.active,
			"dispute": row.dispute,
		}
		for row in found
	]


def _released_holds(sales_invoice) -> list[dict]:
	if not frappe.db.table_exists("Hero Dispute"):
		return []
	names = frappe.get_all(
		"Hero Dispute",
		filters={"sales_invoice": sales_invoice},
		pluck="name",
		ignore_permissions=True,
		limit_page_length=0,
	)
	if not names or not frappe.db.table_exists("Hero Dispute Release"):
		return []
	found = frappe.get_all(
		"Hero Dispute Release",
		filters={"parent": ["in", names], "parenttype": "Hero Dispute"},
		fields=["parent", "action_kind", "source_doctype", "source_name", "previous_state"],
		ignore_permissions=True,
		limit_page_length=0,
	)
	return [
		{
			"kind": row.action_kind,
			"source_doctype": row.source_doctype,
			"source_name": row.source_name,
			"state": row.previous_state,
			"active": 0,
			"dispute": row.parent,
		}
		for row in found
	]
