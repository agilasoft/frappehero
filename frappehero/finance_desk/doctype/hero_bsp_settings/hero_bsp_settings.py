# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from frappehero.finance_desk.bsp import clean_lookback
from frappehero.flags import as_flag


class HeroBSPSettings(Document):
	def validate(self):
		self.enabled = as_flag(self.enabled)
		self.write_inverse = as_flag(self.write_inverse)
		try:
			self.lookback_days = clean_lookback(self.lookback_days)
		except ValueError as exc:
			frappe.throw(str(exc))
