# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.access_desk.logic import REVIEW_STATUSES
from frappehero.flags import clean_text


class HeroAccessReview(Document):
	def validate(self):
		self.review_name = clean_text(self.review_name)
		if not self.review_name:
			frappe.throw(_("Review name is required."))
		if self.status not in ("Open", "Closed"):
			frappe.throw(_("Status must be Open or Closed."))
		seen = set()
		for line in self.lines:
			group = clean_text(line.permission_group)
			if not group:
				frappe.throw(_("Every line needs a permission group."))
			if group in seen:
				frappe.throw(_("{0} is on this review twice.").format(group))
			seen.add(group)
			if line.status not in REVIEW_STATUSES:
				line.status = "Pending"
