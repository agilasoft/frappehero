# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from frappehero.finance_desk.multi_currency_payment import calculate, cancel_journal, post_journal


class HeroMultiCurrencyPayment(Document):
	def before_validate(self):
		# Runs before the mandatory check, so the invoice account is filled in
		# before Frappe requires it. Cancel leaves the saved amounts alone.
		if int(self.docstatus or 0) == 2:
			return
		if int(self.docstatus or 0) == 1 and self.journal_entry:
			return
		calculate(self)

	def on_submit(self):
		prepared = getattr(self.flags, "hero_payment", None)
		if not prepared:
			prepared = calculate(self)
		post_journal(self, prepared)

	def on_cancel(self):
		cancel_journal(self)
