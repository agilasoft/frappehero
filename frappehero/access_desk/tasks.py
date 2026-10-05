# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe


def daily():
	"""Send due alerts and drop document shares that have passed their end date."""
	from frappehero.access_desk.api import clear_expired_shares, send_due

	for label, method in (("notifications", send_due), ("expired shares", clear_expired_shares)):
		try:
			method()
		except Exception:
			frappe.log_error(title=f"Frappe Hero {label}")
