# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Mobile web app for uploading a proof of payment.

The desk page redirects here. Guests go to the login screen first.
"""

from urllib.parse import quote

import frappe

no_cache = 1

_ROLES = {"System Manager", "Accounts Manager", "Accounts User"}


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/proof-of-payment")
		raise frappe.Redirect
	context.no_cache = 1
	# This template is ours. The website sandbox blocks the JSON we embed for the app.
	context.safe_render = False
	context.permitted = bool(set(frappe.get_roles()).intersection(_ROLES))
	context.csrf_token = frappe.sessions.get_csrf_token() if context.permitted else ""
	context.user = frappe.session.user
	context.date_format = frappe.get_system_settings("date_format") or "yyyy-mm-dd"
