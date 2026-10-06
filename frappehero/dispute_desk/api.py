# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import today

from frappehero.dispute_desk.logic import receivables_aging, statement_of_account
from frappehero.flags import clean_text


def _accounts():
	frappe.only_for(["System Manager", "Accounts Manager"])


@frappe.whitelist()
def raise_dispute(
	reference_doctype: str,
	reference_name: str,
	sales_invoice: str | None = None,
	company: str | None = None,
	customer: str | None = None,
	reason: str | None = None,
	source_module: str | None = None,
	dispute_date: str | None = None,
) -> dict:
	"""Open a dispute from logistics, ERPNext, or any other module.

	When the source is a Sales Invoice and ``sales_invoice`` is omitted, that
	document is the invoice. Hold, collection, dunning, and any other active
	action on the invoice are released.
	"""
	_accounts()
	doc = frappe.new_doc("Hero Dispute")
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.sales_invoice = sales_invoice
	doc.company = company
	doc.customer = customer
	doc.reason = reason
	doc.source_module = source_module
	doc.dispute_date = dispute_date or today()
	doc.status = "Open"
	doc.insert(ignore_permissions=True)
	return _dispute_summary(doc)


@frappe.whitelist()
def register_invoice_action(
	sales_invoice: str,
	action_kind: str,
	company: str,
	customer: str | None = None,
	source_doctype: str | None = None,
	source_name: str | None = None,
	state: str | None = None,
) -> dict:
	"""Register a hold, collection, dunning, or other action against an invoice."""
	_accounts()
	doc = frappe.new_doc("Hero Invoice Action")
	doc.sales_invoice = sales_invoice
	doc.action_kind = action_kind
	doc.company = company
	doc.customer = customer
	doc.source_doctype = source_doctype
	doc.source_name = source_name
	doc.state = state or "Active"
	doc.active = 1
	doc.insert(ignore_permissions=True)
	return _action_summary(doc)


@frappe.whitelist()
def list_disputes(company: str | None = None, status: str | None = None) -> list:
	_accounts()
	filters = {}
	if clean_text(company):
		filters["company"] = clean_text(company)
	if clean_text(status):
		filters["status"] = clean_text(status)
	names = frappe.get_all("Hero Dispute", filters=filters, pluck="name", order_by="modified desc")
	return [_dispute_summary(frappe.get_doc("Hero Dispute", name), include_releases=False) for name in names]


@frappe.whitelist()
def get_dispute(name: str) -> dict:
	_accounts()
	return _dispute_summary(frappe.get_doc("Hero Dispute", name), include_releases=True)


@frappe.whitelist()
def set_dispute_status(name: str, status: str) -> dict:
	_accounts()
	doc = frappe.get_doc("Hero Dispute", name)
	doc.status = status
	doc.save(ignore_permissions=True)
	return _dispute_summary(doc, include_releases=True)


def statement_rows(company, customer, from_date=None, to_date=None) -> dict:
	rows = receivable_invoices(company, customer, from_date=from_date, to_date=to_date)
	disputes = open_dispute_rows(company, customer)
	return statement_of_account(
		rows,
		disputes,
		customer=customer,
		company=company,
		from_date=from_date,
		to_date=to_date,
	)


def aging_rows(company, customer=None, as_of=None) -> dict:
	rows = receivable_invoices(company, customer, as_of=as_of)
	disputes = open_dispute_rows(company, customer)
	return receivables_aging(rows, disputes, as_of, customer=customer, company=company)


def receivable_invoices(company, customer=None, from_date=None, to_date=None, as_of=None) -> list[dict]:
	if not company or not frappe.db.table_exists("Sales Invoice"):
		return []
	filters = {"docstatus": 1, "company": company, "outstanding_amount": [">", 0]}
	if clean_text(customer):
		filters["customer"] = clean_text(customer)
	posting = _posting_filter(from_date, to_date, as_of)
	if posting:
		filters["posting_date"] = posting
	rows = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", "customer", "company", "posting_date", "due_date", "outstanding_amount"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	return [
		{
			"sales_invoice": row.name,
			"customer": row.customer,
			"company": row.company,
			"posting_date": row.posting_date,
			"due_date": row.due_date,
			"outstanding": row.outstanding_amount,
		}
		for row in rows
	]


def open_dispute_rows(company, customer=None) -> list[dict]:
	if not company or not frappe.db.table_exists("Hero Dispute"):
		return []
	filters = {"status": "Open", "company": company}
	if clean_text(customer):
		filters["customer"] = clean_text(customer)
	return frappe.get_all(
		"Hero Dispute",
		filters=filters,
		fields=["name", "sales_invoice", "status", "company", "customer"],
		limit_page_length=0,
		ignore_permissions=True,
	)


def _posting_filter(from_date, to_date, as_of):
	start = clean_text(from_date)
	end = clean_text(to_date)
	as_of_text = clean_text(as_of)
	if start and end:
		upper = end if not as_of_text or as_of_text > end else as_of_text
		return ["between", [start, upper]]
	if start:
		return [">=", start]
	upper = end or as_of_text
	if as_of_text and end and as_of_text < end:
		upper = as_of_text
	if upper:
		return ["<=", upper]
	return None


def _dispute_summary(doc, include_releases: bool = False) -> dict:
	releases = [_release_summary(row) for row in doc.releases]
	payload = {
		"name": doc.name,
		"company": doc.company,
		"customer": doc.customer,
		"sales_invoice": doc.sales_invoice,
		"dispute_date": doc.dispute_date,
		"status": doc.status,
		"reference_doctype": doc.reference_doctype,
		"reference_name": doc.reference_name,
		"source_module": doc.source_module,
		"reason": doc.reason,
		"release_count": len(releases),
	}
	if include_releases:
		payload["releases"] = releases
	return payload


def _release_summary(row) -> dict:
	return {
		"action_kind": row.action_kind,
		"source_doctype": row.source_doctype,
		"source_name": row.source_name,
		"previous_state": row.previous_state,
		"invoice_action": row.invoice_action,
	}


def _action_summary(doc) -> dict:
	return {
		"name": doc.name,
		"sales_invoice": doc.sales_invoice,
		"customer": doc.customer,
		"company": doc.company,
		"action_kind": doc.action_kind,
		"source_doctype": doc.source_doctype,
		"source_name": doc.source_name,
		"state": doc.state,
		"active": doc.active,
		"dispute": doc.dispute,
	}
