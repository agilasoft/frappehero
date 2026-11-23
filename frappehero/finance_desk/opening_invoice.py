# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Extend Opening Invoice Creation Tool with credit notes and debit notes.

ERPNext treats every invoice type other than Sales as a purchase invoice, and
newer versions look up a child table named after that type. Credit Note and
Debit Note are swapped to Sales and Purchase while the standard tool builds
the invoice, then stamped as returns.
"""

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Count, Sum
from frappe.utils import escape_html

from frappehero.finance_desk.opening_invoice_logic import (
	OpeningInvoiceError,
	against_can_link,
	apply_note,
	fold_opening_summary,
	invoice_kind,
	retitle,
)
from frappehero.flags import clean_text


def _base_class():
	from erpnext.accounts.doctype.opening_invoice_creation_tool.opening_invoice_creation_tool import (
		OpeningInvoiceCreationTool as ERPNextOpeningInvoiceCreationTool,
	)

	return ERPNextOpeningInvoiceCreationTool


class OpeningInvoiceCreationTool(_base_class()):
	def get_opening_invoice_summary(self):
		companies = frappe.get_list("Company", fields=["name as company", "default_currency as currency"])
		if not companies:
			return None, None

		company_currency = {row.company: row.currency for row in companies}
		rows_by_doctype = {
			doctype: _opening_invoice_rows(doctype, list(company_currency))
			for doctype in ("Sales Invoice", "Purchase Invoice")
		}
		summary, max_count = fold_opening_summary(company_currency, rows_by_doctype)
		escaped = {escape_html(company): values for company, values in summary.items()}
		return escaped, max_count

	def set_missing_values(self, row):
		kind = self._kind()
		self._as_base(kind, lambda: super(OpeningInvoiceCreationTool, self).set_missing_values(row))
		if kind["is_return"]:
			row.party_type = kind["party_type"]
			row.item_name = retitle(row.item_name, kind["item_name"])

	def get_invoice_dict(self, row=None):
		kind = self._kind()
		invoice = self._as_base(kind, lambda: super(OpeningInvoiceCreationTool, self).get_invoice_dict(row))
		if not invoice or not kind["is_return"]:
			return invoice
		against = clean_text(row.get("hero_against_invoice") if row is not None else "")
		linked = _against_is_submitted(kind["doctype"], against, self.company)
		return apply_note(invoice, kind, against, linked)

	def _kind(self) -> dict:
		try:
			return invoice_kind(self.invoice_type)
		except OpeningInvoiceError as exc:
			frappe.throw(str(exc))

	def _as_base(self, kind, call):
		original = self.invoice_type
		self.invoice_type = kind["base_type"]
		try:
			return call()
		finally:
			self.invoice_type = original


def _opening_invoice_rows(doctype, companies):
	"""Submitted opening invoices, grouped by company and return flag."""
	invoice = frappe.qb.DocType(doctype)
	company = frappe.qb.DocType("Company")
	outstanding = (
		Case()
		.when(invoice.party_account_currency == company.default_currency, invoice.outstanding_amount)
		.else_(invoice.outstanding_amount * invoice.conversion_rate)
	)
	return (
		frappe.qb.from_(invoice)
		.join(company)
		.on(invoice.company == company.name)
		.select(
			invoice.company,
			invoice.is_return,
			Count(invoice.name).as_("total_invoices"),
			Sum(outstanding).as_("outstanding_amount"),
		)
		.where((invoice.is_opening == "Yes") & (invoice.docstatus == 1) & (invoice.company.isin(companies)))
		.groupby(invoice.company, invoice.is_return)
	).run(as_dict=True)


def _against_is_submitted(doctype, name, company) -> bool:
	name = clean_text(name)
	if not name or not frappe.db.exists(doctype, name):
		return False
	row = frappe.db.get_value(doctype, name, ["company", "docstatus"], as_dict=True)
	if not row:
		return False
	return against_can_link(name, company, row.company, row.docstatus)
