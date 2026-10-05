# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.flags import clean_text


class HeroDefaultSet(Document):
	def validate(self):
		self.set_name = clean_text(self.set_name)
		if not self.set_name:
			frappe.throw(_("Set name is required."))
		if not self.permission_group:
			frappe.throw(_("Permission group is required."))
		seen = set()
		for row in self.values:
			key = clean_text(row.default_key)
			if not key or not clean_text(row.default_value):
				frappe.throw(_("Each default needs a DocType and a value."))
			if key in seen:
				frappe.throw(_("{0} is set twice.").format(key))
			seen.add(key)
