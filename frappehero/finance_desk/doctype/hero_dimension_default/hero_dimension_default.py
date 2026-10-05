# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.finance_desk.logic import DIMENSIONS
from frappehero.flags import clean_text


class HeroDimensionDefault(Document):
	def validate(self):
		self.company = clean_text(self.company)
		self.dimension = clean_text(self.dimension)
		self.account = clean_text(self.account)
		self.default_value = clean_text(self.default_value)
		if self.dimension not in DIMENSIONS:
			frappe.throw(_("Choose Cost Center, Project, or Branch."))
		if not self.company or not self.account or not self.default_value:
			frappe.throw(_("Company, account, and default value are required."))
		duplicate = frappe.db.exists(
			"Hero Dimension Default",
			{"company": self.company, "dimension": self.dimension, "account": self.account},
		)
		if duplicate and duplicate != self.name:
			frappe.throw(_("This account already has a {0} default.").format(self.dimension))
		if frappe.db.table_exists("Account"):
			account = frappe.db.get_value("Account", self.account, ["company", "is_group"], as_dict=True)
			if not account:
				frappe.throw(_("Account {0} does not exist.").format(self.account))
			if account.is_group:
				frappe.throw(_("{0} is a group account. Set the default on its ledgers.").format(self.account))
			if account.company != self.company:
				frappe.throw(_("{0} belongs to {1}, not {2}.").format(self.account, account.company, self.company))
