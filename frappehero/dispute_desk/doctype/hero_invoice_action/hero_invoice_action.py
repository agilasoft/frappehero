# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.dispute_desk.logic import DisputeError, prepare_invoice_action
from frappehero.flags import clean_text


class HeroInvoiceAction(Document):
	def validate(self):
		disputes = []
		if self.sales_invoice and frappe.db.table_exists("Hero Dispute"):
			disputes = frappe.get_all(
				"Hero Dispute",
				filters={"sales_invoice": self.sales_invoice, "status": "Open"},
				fields=["name", "sales_invoice", "status"],
				limit_page_length=0,
			)
		try:
			prepared = prepare_invoice_action(self.as_dict(), disputes)
		except DisputeError as exc:
			frappe.throw(_(str(exc)))
		self.sales_invoice = prepared["sales_invoice"]
		self.customer = clean_text(prepared.get("customer"))
		self.company = clean_text(prepared.get("company"))
		self.action_kind = prepared["kind"]
		self.source_doctype = prepared["source_doctype"]
		self.source_name = prepared["source_name"]
		self.state = prepared["state"]
		self.active = prepared["active"]
		if not self.company:
			frappe.throw(_("Company is required."))
