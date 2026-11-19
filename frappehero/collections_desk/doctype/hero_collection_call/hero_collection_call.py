# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.collections_desk.logic import CollectionError, freeze_call, normalize_call
from frappehero.flags import clean_text


class HeroCollectionCall(Document):
	def validate(self):
		if not clean_text(self.collector):
			self.collector = frappe.session.user
		previous = self.get_doc_before_save()
		try:
			fields = normalize_call(self.as_dict())
			if previous:
				freeze_call(previous.as_dict(), fields)
		except CollectionError as exc:
			frappe.throw(_(str(exc)))
		for key, value in fields.items():
			setattr(self, key, value)
