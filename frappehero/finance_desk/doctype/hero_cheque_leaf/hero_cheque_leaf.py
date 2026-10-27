# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.finance_desk.cheque_logic import (
	ChequeError,
	LEAF_STATUSES,
	compose_numbers,
	conflicting_numbers,
	generate_range,
	parse_extra_numbers,
	validate_leaf_shape,
	validate_number_changes,
)
from frappehero.flags import as_flag, clean_text


class HeroChequeLeaf(Document):
	def validate(self):
		self.leaf_name = clean_text(self.leaf_name)
		self.prefix = clean_text(self.prefix)
		if not self.leaf_name:
			frappe.throw(_("Leaf name is required."))
		if self.status not in LEAF_STATUSES:
			frappe.throw(_("Status is Draft, Active, or Closed."))
		self._set_bank_details()
		if self.status != "Active":
			self.is_default = 0
		try:
			ranged = generate_range(self.prefix, self.from_number, self.to_number, self.padding)
			extras = parse_extra_numbers(self.extra_numbers)
		except ChequeError as exc:
			frappe.throw(str(exc))
		current = [self._row_dict(row) for row in self.numbers]
		composed = compose_numbers(current, ranged, extras, self.replace_available)
		problems = validate_leaf_shape(
			{"status": self.status, "bank_account": self.bank_account},
			composed,
		)
		problems.extend(validate_number_changes(self._previous_numbers(), composed))
		if problems:
			frappe.throw(problems[0])
		clash = conflicting_numbers(
			[row["cheque_number"] for row in composed],
			self._other_sets(),
		)
		if clash:
			first = clash[0]
			frappe.throw(
				_("{0} is already on Cheque Leaf {1} for this bank account.").format(
					first["cheque_number"], first["leaf"]
				)
			)
		self._apply_numbers(composed)
		self.extra_numbers = ""
		self.replace_available = 0
		self._clear_other_defaults()

	def _set_bank_details(self):
		if not self.bank_account:
			frappe.throw(_("Bank Account is required."))
		if not frappe.db.table_exists("Bank Account"):
			if not self.company:
				frappe.throw(_("Company is required."))
			return
		row = frappe.db.get_value(
			"Bank Account",
			self.bank_account,
			["company", "bank", "is_company_account"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("Bank Account {0} does not exist.").format(self.bank_account))
		if not as_flag(row.is_company_account):
			frappe.throw(_("Cheque Leaves use a company bank account."))
		self.company = row.company
		self.bank = row.bank

	def _previous_numbers(self):
		if self.is_new() or not self.name or not frappe.db.exists(self.doctype, self.name):
			return []
		previous = frappe.get_doc(self.doctype, self.name)
		return [self._row_dict(row) for row in previous.numbers]

	def _other_sets(self):
		if not self.bank_account or not frappe.db.table_exists("Hero Cheque Number"):
			return []
		rows = frappe.db.sql(
			"""
			select leaf.name as leaf, num.cheque_number as cheque_number
			from `tabHero Cheque Number` num
			inner join `tabHero Cheque Leaf` leaf on leaf.name = num.parent
			where leaf.bank_account = %s and ifnull(leaf.name, '') != %s
			""",
			(self.bank_account, self.name or ""),
			as_dict=True,
		)
		grouped = {}
		for row in rows:
			grouped.setdefault(row.leaf, []).append(row.cheque_number)
		return [{"name": name, "numbers": numbers} for name, numbers in grouped.items()]

	def _apply_numbers(self, composed):
		by_name = {row.name: row for row in self.numbers if row.name}
		keep = []
		for item in composed:
			child = by_name.get(item["name"]) if item.get("name") else None
			if child is None:
				child = self.append("numbers", {})
			child.cheque_number = item["cheque_number"]
			child.status = item["status"]
			child.payment_entry = item.get("payment_entry") or ""
			child.party = item.get("party") or ""
			child.posting_date = item.get("posting_date")
			child.remarks = item.get("remarks") or ""
			keep.append(child)
		for row in list(self.numbers):
			if row not in keep:
				self.remove(row)

	def _clear_other_defaults(self):
		if not as_flag(self.is_default) or not frappe.db.table_exists("Hero Cheque Leaf"):
			return
		others = frappe.get_all(
			"Hero Cheque Leaf",
			filters={"bank_account": self.bank_account, "is_default": 1, "name": ["!=", self.name or ""]},
			pluck="name",
		)
		for name in others:
			frappe.db.set_value("Hero Cheque Leaf", name, "is_default", 0, update_modified=False)

	@staticmethod
	def _row_dict(row):
		data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
		return {
			"name": data.get("name") or "",
			"cheque_number": data.get("cheque_number"),
			"status": data.get("status"),
			"payment_entry": data.get("payment_entry"),
			"party": data.get("party"),
			"posting_date": data.get("posting_date"),
			"remarks": data.get("remarks"),
		}
