# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.dispute_desk.apply import apply_releases, collect_actions, sync_invoice_dispute
from frappehero.dispute_desk.logic import (
	DisputeError,
	assert_no_open_dispute,
	normalize_dispute_fields,
	release_invoice_actions,
	same_day,
	validate_status_transition,
)
from frappehero.flags import clean_text


class HeroDispute(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		try:
			status = validate_status_transition(
				previous.status if previous else None,
				self.status or "Open",
				bool(self.is_new()),
			)
			fields = normalize_dispute_fields({**self.as_dict(), "status": status})
		except DisputeError as exc:
			frappe.throw(_(str(exc)))
		for key, value in fields.items():
			setattr(self, key, value)
		if previous:
			self._freeze(previous)
			return
		self._reject_another_open_dispute()
		if not self.releases:
			_updated, releases = release_invoice_actions(self.sales_invoice, collect_actions(self.sales_invoice))
			self.set("releases", releases)

	def after_insert(self):
		apply_releases(self)

	def on_update(self):
		previous = self.get_doc_before_save()
		sync_invoice_dispute(self.sales_invoice)
		if previous and previous.sales_invoice and previous.sales_invoice != self.sales_invoice:
			sync_invoice_dispute(previous.sales_invoice)

	def _reject_another_open_dispute(self):
		if not frappe.db.table_exists("Hero Dispute"):
			return
		existing = frappe.get_all(
			"Hero Dispute",
			filters={"sales_invoice": self.sales_invoice, "status": "Open"},
			fields=["name", "sales_invoice", "status"],
			limit_page_length=0,
		)
		try:
			assert_no_open_dispute(self.sales_invoice, existing, ignore_name=self.name)
		except DisputeError as exc:
			frappe.throw(_(str(exc)))

	def _freeze(self, previous):
		if clean_text(previous.sales_invoice) != clean_text(self.sales_invoice):
			frappe.throw(_("The sales invoice on a dispute cannot change."))
		if clean_text(previous.company) != clean_text(self.company):
			frappe.throw(_("The company on a dispute cannot change."))
		if clean_text(previous.customer) != clean_text(self.customer):
			frappe.throw(_("The customer on a dispute cannot change."))
		if clean_text(previous.reference_doctype) != clean_text(self.reference_doctype):
			frappe.throw(_("The source document on a dispute cannot change."))
		if clean_text(previous.reference_name) != clean_text(self.reference_name):
			frappe.throw(_("The source document on a dispute cannot change."))
		if clean_text(previous.source_module) != clean_text(self.source_module):
			frappe.throw(_("The source module on a dispute cannot change."))
		if not same_day(previous.dispute_date, self.dispute_date):
			frappe.throw(_("The dispute date cannot change."))
		if len(previous.releases or []) != len(self.releases or []):
			frappe.throw(_("Released actions cannot be changed."))
