# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.collections_desk.logic import CollectionError, freeze_report, normalize_report


class HeroCollectionReport(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		try:
			fields = normalize_report(
				self.as_dict(),
				previous_status=previous.status if previous else None,
				is_new=bool(self.is_new()),
			)
			if previous:
				freeze_report(previous.as_dict(), fields)
		except CollectionError as exc:
			frappe.throw(_(str(exc)))
		for key, value in fields.items():
			if key == "previous_status":
				continue
			setattr(self, key, value)
