# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.finance_desk.logic import OPENING_PURPOSES, opening_totals
from frappehero.flags import clean_text


class HeroOpeningBatch(Document):
	def validate(self):
		self.batch_name = clean_text(self.batch_name)
		if not self.batch_name:
			frappe.throw(_("Batch name is required."))
		if not self.company:
			frappe.throw(_("Company is required."))
		if not self.posting_date:
			frappe.throw(_("Posting date is required."))
		if self.purpose not in OPENING_PURPOSES:
			frappe.throw(_("Purpose must be Opening Entry or Reclass."))
		if self.status not in ("Draft", "Journal Created"):
			self.status = "Draft"
		for line in self.lines:
			line.debit = round(float(line.debit or 0), 2)
			line.credit = round(float(line.credit or 0), 2)
			if line.matched_account:
				self._check_account(line.matched_account)
				line.match_status = "Matched"
				if not clean_text(line.match_reason):
					line.match_reason = "Chosen on the batch"
			elif line.match_status not in ("Unmatched", "Matched", "Ambiguous"):
				line.match_status = "Unmatched"
		totals = opening_totals([row.as_dict() for row in self.lines])
		self.debit_total = totals["debit"]
		self.credit_total = totals["credit"]
		self.difference = totals["difference"]

	def _check_account(self, account_name):
		if not frappe.db.table_exists("Account"):
			return
		account = frappe.db.get_value("Account", account_name, ["company", "is_group"], as_dict=True)
		if not account:
			frappe.throw(_("Account {0} does not exist.").format(account_name))
		if account.is_group:
			frappe.throw(_("{0} is a group account. Match a ledger instead.").format(account_name))
		if account.company != self.company:
			frappe.throw(_("{0} belongs to {1}, not {2}.").format(account_name, account.company, self.company))
