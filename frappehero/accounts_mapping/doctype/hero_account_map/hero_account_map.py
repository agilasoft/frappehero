# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.accounts_mapping.logic import coverage, line_completion, status_by_account, validate_map
from frappehero.flags import clean_text


class HeroAccountMap(Document):
	def validate(self):
		self.map_name = clean_text(self.map_name)
		self._validate_lines()
		self._update_coverage()

	def _validate_lines(self):
		names = []
		for line in self.lines:
			if line.source_account:
				names.append(line.source_account)
			if line.target_account:
				names.append(line.target_account)
		accounts = {}
		if names and frappe.db.table_exists("Account"):
			for row in frappe.get_all(
				"Account",
				filters={"name": ["in", names]},
				fields=["name", "company", "is_group", "account_name", "root_type", "account_type"],
				limit_page_length=0,
				ignore_permissions=True,
			):
				accounts[row.name] = row
		company_of = {name: row.company for name, row in accounts.items()}
		groups = {name for name, row in accounts.items() if row.is_group}
		errors = validate_map(self.as_dict(), company_of, groups)
		if errors:
			frappe.throw("<br>".join(errors), title=_("Check the account map"))
		for line in self.lines:
			info = accounts.get(line.source_account)
			if info:
				line.account_name = info.account_name
				line.root_type = info.root_type
				line.account_type = info.account_type
			line.status = "Mapped" if line_completion(self.mapping_type, line.as_dict()) == "mapped" else "Partial"

	def _update_coverage(self):
		if not self.company or not frappe.db.table_exists("Account"):
			self.mapped_count = 0
			self.partial_count = 0
			self.unmapped_count = 0
			self.leaf_count = 0
			self.coverage_percent = 0
			return
		accounts = frappe.get_all(
			"Account",
			filters={"company": self.company},
			fields=["name", "is_group", "disabled"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		lines = [row.as_dict() for row in self.lines]
		stats = coverage(accounts, status_by_account(accounts, lines, self.mapping_type))
		self.mapped_count = stats["mapped"]
		self.partial_count = stats["partial"]
		self.unmapped_count = stats["unmapped"]
		self.leaf_count = stats["total"]
		self.coverage_percent = stats["percent"]
