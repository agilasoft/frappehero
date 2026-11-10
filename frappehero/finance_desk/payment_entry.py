# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Let one Payment Entry clear invoices on more than one party account.

ERPNext keeps a single paid-from or paid-to party account and posts exchange
gain or loss in a follow-up journal. A payment that spans accounts posts each
party line, the advance, the rate difference, and the bank line on the Payment
Entry itself. A payment that stays on one account uses ERPNext unchanged.
"""

import frappe
from frappe import _
from frappe.utils import flt

from frappehero.finance_desk.multi_currency_payment import (
	prepare_payment_entry,
	uses_multiple_accounts,
)
from frappehero.flags import clean_text


def _base_class():
	from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry as ERPNextPaymentEntry

	return ERPNextPaymentEntry


class PaymentEntry(_base_class()):
	def validate(self):
		if not self._uses_multiple_accounts():
			return super().validate()
		from erpnext.accounts.doctype.mode_of_payment.mode_of_payment import validate_enabled_mode_of_payment

		validate_enabled_mode_of_payment(self.mode_of_payment)
		self.setup_party_account_field()
		self.set_missing_values()
		self.validate_payment_type()
		self.validate_party_details()
		self.set_exchange_rate()
		self.validate_mandatory()
		self.validate_reference_documents()
		self.set_amounts()
		self.validate_amounts()
		self.set_amounts_after_tax()
		self.clear_unallocated_reference_document_rows()
		self.validate_transaction_reference()
		self.set_title()
		self.set_remarks()
		self.validate_duplicate_entry()
		self.validate_payment_type_with_outstanding()
		if not self._is_cancel():
			self.validate_paid_invoices()
		self.ensure_supplier_is_not_blocked()
		self.set_status()
		self.set_total_in_words()

	def set_missing_ref_details(
		self,
		force: bool = False,
		update_ref_details_only_for: list | None = None,
		reference_exchange_details: dict | None = None,
	) -> None:
		if self._uses_multiple_accounts():
			return
		super().set_missing_ref_details(
			force=force,
			update_ref_details_only_for=update_ref_details_only_for,
			reference_exchange_details=reference_exchange_details,
		)

	def validate_reference_documents(self):
		if not self._uses_multiple_accounts():
			return super().validate_reference_documents()
		expected, party_field, account_field = _reference_fields(self.party_type)
		for row in self.get("references"):
			if not row.allocated_amount:
				continue
			if row.reference_doctype != expected:
				frappe.throw(
					_("A {0} payment allocates {1}s. {2} is a {3}.").format(
						_(self.party_type),
						_(expected),
						row.reference_name,
						_(row.reference_doctype),
					)
				)
			if not row.reference_name or not frappe.db.exists(row.reference_doctype, row.reference_name):
				frappe.throw(_("{0} {1} does not exist").format(row.reference_doctype, row.reference_name))
			ref_doc = frappe.get_doc(row.reference_doctype, row.reference_name)
			if self.party != ref_doc.get(party_field):
				frappe.throw(
					_("{0} {1} is not associated with {2} {3}").format(
						_(row.reference_doctype), row.reference_name, _(self.party_type), self.party
					)
				)
			if int(ref_doc.docstatus or 0) != 1:
				frappe.throw(
					_("{0} {1} must be submitted").format(_(row.reference_doctype), row.reference_name)
				)
			if ref_doc.doctype == "Purchase Invoice" and ref_doc.get("on_hold"):
				frappe.throw(
					_("{0} {1} is on hold").format(_(row.reference_doctype), row.reference_name),
					title=_("Invalid Purchase Invoice"),
				)
			invoice_account = ref_doc.get(account_field)
			if clean_text(row.get("hero_account")) != invoice_account:
				frappe.throw(
					_("{0} {1} is on {2}, not {3}.").format(
						_(row.reference_doctype),
						row.reference_name,
						invoice_account,
						row.get("hero_account"),
					)
				)

	def validate_allocated_amount(self):
		if self._uses_multiple_accounts():
			return
		super().validate_allocated_amount()

	def set_amounts(self):
		if not self._uses_multiple_accounts():
			return super().set_amounts()
		if self._is_cancel():
			self.difference_amount = 0
			return
		prepared = self._prepared_payment()
		self.base_paid_amount = prepared["base_paid_amount"]
		self.base_received_amount = prepared["base_paid_amount"]
		self.difference_amount = 0
		for row in self.get("references"):
			row.exchange_gain_loss = 0

	def set_amounts_after_tax(self):
		if not self._uses_multiple_accounts():
			return super().set_amounts_after_tax()
		self.paid_amount_after_tax = self.paid_amount
		self.received_amount_after_tax = self.received_amount
		self.base_paid_amount_after_tax = self.base_paid_amount
		self.base_received_amount_after_tax = self.base_received_amount

	def set_difference_amount(self):
		if not self._uses_multiple_accounts():
			return super().set_difference_amount()
		self.difference_amount = 0

	def build_gl_map(self):
		if not self._uses_multiple_accounts():
			return super().build_gl_map()
		prepared = self._prepared_payment()
		if not self.get("party_account_field"):
			self.setup_party_account_field()
		self._set_bank_transaction_currency(prepared)
		gl_entries = [self._gl_from_line(line, prepared) for line in prepared["accounts"]]
		self.set_transaction_currency_and_rate_in_gl_map(gl_entries)
		return gl_entries

	def make_gl_entries(self, cancel=0, adv_adj=0):
		if not self._uses_multiple_accounts():
			return super().make_gl_entries(cancel=cancel, adv_adj=adv_adj)
		from erpnext.accounts.general_ledger import make_gl_entries as post_gl_entries
		from erpnext.accounts.general_ledger import make_reverse_gl_entries
		from erpnext.accounts.utils import cancel_exchange_gain_loss_journal

		if cancel:
			make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)
			cancel_exchange_gain_loss_journal(frappe._dict(doctype=self.doctype, name=self.name))
			return
		post_gl_entries(self.build_gl_map(), cancel=0, adv_adj=adv_adj)

	def _uses_multiple_accounts(self) -> bool:
		meta = getattr(self, "meta", None)
		if not meta or not meta.has_field("hero_multi_account"):
			return False
		return bool(self.get("hero_multi_account")) or uses_multiple_accounts(self)

	def _prepared_payment(self):
		prepared = getattr(self.flags, "hero_payment", None)
		if prepared:
			return prepared
		if self._is_cancel():
			frappe.throw(_("This payment could not be cancelled from its saved amounts."))
		return prepare_payment_entry(self)

	def _is_cancel(self) -> bool:
		if clean_text(getattr(self, "_action", None)) == "cancel":
			return True
		try:
			return int(self.docstatus or 0) == 2
		except (TypeError, ValueError):
			return False

	def _set_bank_transaction_currency(self, prepared):
		bank_currency = prepared["bank_currency"]
		self.transaction_currency = bank_currency
		if bank_currency == self.company_currency:
			self.transaction_exchange_rate = 1
		else:
			self.transaction_exchange_rate = prepared["bank_exchange_rate"] or 1

	def _gl_from_line(self, line, prepared):
		is_party = bool(line.get("party"))
		payload = {
			"account": line["account"],
			"account_currency": line.get("account_currency"),
			"against": self.party if not is_party else prepared["bank_account"],
			"debit": line["debit"],
			"credit": line["credit"],
			"debit_in_account_currency": line["debit_in_account_currency"],
			"credit_in_account_currency": line["credit_in_account_currency"],
		}
		cost_center = line.get("cost_center") or self.get("cost_center")
		if cost_center:
			payload["cost_center"] = cost_center
		if is_party:
			payload["party_type"] = line.get("party_type")
			payload["party"] = line.get("party")
			if line.get("reference_name"):
				payload["against_voucher_type"] = line.get("reference_type")
				payload["against_voucher"] = line.get("reference_name")
		rate = flt(self.transaction_exchange_rate) or 1
		account_currency = line.get("account_currency")
		if account_currency == self.transaction_currency:
			payload["debit_in_transaction_currency"] = line["debit_in_account_currency"]
			payload["credit_in_transaction_currency"] = line["credit_in_account_currency"]
		else:
			precision = self.precision("paid_amount")
			payload["debit_in_transaction_currency"] = flt(flt(line["debit"]) / rate, precision)
			payload["credit_in_transaction_currency"] = flt(flt(line["credit"]) / rate, precision)
		return self.get_gl_dict(payload, account_currency=account_currency, item=self)


def _reference_fields(party_type):
	if party_type == "Customer":
		return "Sales Invoice", "customer", "debit_to"
	if party_type == "Supplier":
		return "Purchase Invoice", "supplier", "credit_to"
	frappe.throw(_("Multiple accounts are available for customers and suppliers."))
