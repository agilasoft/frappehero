# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today

from frappehero.dispute_desk.api import aging_rows
from frappehero.dispute_desk.logic import DisputeError, rows_for_desk
from frappehero.flags import clean_text


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = _columns()
	company = clean_text(filters.get("company"))
	if not company:
		frappe.msgprint(_("Company is required."))
		return columns, []
	as_of = filters.get("as_of") or today()
	try:
		result = aging_rows(company, clean_text(filters.get("customer")) or None, as_of)
	except DisputeError as exc:
		frappe.throw(_(str(exc)))
	# Disputed lines travel with the result so the printout can section them.
	# The report script takes them off the table.
	return columns, rows_for_desk(result), None, None, _summary(result)


def _columns():
	return [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Sales Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 110},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Float", "width": 120},
		{"label": _("Age"), "fieldname": "age_days", "fieldtype": "Int", "width": 80},
		{"label": _("Current"), "fieldname": "current", "fieldtype": "Float", "width": 110},
		{"label": _("1-30"), "fieldname": "days_1_30", "fieldtype": "Float", "width": 110},
		{"label": _("31-60"), "fieldname": "days_31_60", "fieldtype": "Float", "width": 110},
		{"label": _("61-90"), "fieldname": "days_61_90", "fieldtype": "Float", "width": 110},
		{"label": _("91 and over"), "fieldname": "days_91_over", "fieldtype": "Float", "width": 120},
	]


def _summary(result):
	summary = [
		{"value": result["amount_due"], "label": _("Amount Due"), "datatype": "Float"},
		{"value": result["disputed_outstanding"], "label": _("Disputed"), "datatype": "Float"},
	]
	for label, amount in result["buckets"].items():
		summary.append({"value": amount, "label": _(label), "datatype": "Float"})
	return summary
