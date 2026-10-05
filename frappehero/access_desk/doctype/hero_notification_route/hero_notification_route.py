# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from frappehero.access_desk.logic import NOTIFY_EVENTS
from frappehero.flags import clean_text


class HeroNotificationRoute(Document):
	def validate(self):
		self.route_name = clean_text(self.route_name)
		if not self.route_name:
			frappe.throw(_("Route name is required."))
		if self.event not in NOTIFY_EVENTS:
			frappe.throw(_("Choose an event."))
		if not self.permission_group:
			frappe.throw(_("Permission group is required."))
		if self.event == "Unmapped Accounts" and not self.account_map:
			frappe.throw(_("Choose the account map this alert should watch."))
		if self.event != "Unmapped Accounts":
			self.account_map = None
