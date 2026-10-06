# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappehero.dispute_desk.api import statement_rows
from frappehero.dispute_desk.logic import DisputeError, rows_for_desk
from frappehero.flags import clean_text


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = _columns()
	company = clean_text(filters.get("company"))
	customer = clean_text(filters.get("customer"))
	if not company or not customer:
		frappe.msgprint(_("Choose a company and a customer."))
		return columns, []
	try:
		result = statement_rows(company, customer, filters.get("from_date"), filters.get("to_date"))
	except DisputeError as exc:
		frappe.throw(_(str(exc)))
	# Disputed lines travel with the result so the printout can section them.
	# The report script takes them off the table.
	return columns, rows_for_desk(result), None, None, _summary(result)


def _columns():
	return [
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Sales Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 110},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Float", "width": 120},
		{"label": _("Running Balance"), "fieldname": "running_balance", "fieldtype": "Float", "width": 140},
	]


def _summary(result):
	return [
		{"value": result["amount_due"], "label": _("Amount Due"), "datatype": "Float"},
		{"value": result["disputed_outstanding"], "label": _("Disputed"), "datatype": "Float"},
	]
