# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe


def daily_rates():
	"""Fill recent BSP bulletins that are not already stored."""
	from frappehero.finance_desk.api import sync_recent_bsp_rates

	try:
		sync_recent_bsp_rates()
	except Exception:
		frappe.log_error(title="Frappe Hero BSP rates")
