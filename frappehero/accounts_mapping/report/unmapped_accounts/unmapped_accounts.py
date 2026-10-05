# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from frappehero.accounts_mapping.api import unmapped_account_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 220},
		{"label": _("Account Name"), "fieldname": "account_name", "fieldtype": "Data", "width": 180},
		{"label": _("Number"), "fieldname": "account_number", "fieldtype": "Data", "width": 100},
		{"label": _("Root Type"), "fieldname": "root_type", "fieldtype": "Data", "width": 110},
		{"label": _("Account Type"), "fieldname": "account_type", "fieldtype": "Data", "width": 140},
		{"label": _("Parent"), "fieldname": "parent_account", "fieldtype": "Link", "options": "Account", "width": 180},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Target Account"), "fieldname": "target_account", "fieldtype": "Link", "options": "Account", "width": 200},
		{"label": _("External Code"), "fieldname": "external_code", "fieldtype": "Data", "width": 120},
		{"label": _("Reporting Group"), "fieldname": "reporting_group", "fieldtype": "Data", "width": 140},
	]
	if not filters.get("map"):
		frappe.msgprint(_("Choose an account map."))
		return columns, []
	rows = unmapped_account_rows(
		filters.map,
		{
			"status": filters.status or "unmapped",
			"search": filters.search,
			"root_types": [filters.root_type] if filters.root_type else [],
			"account_types": [filters.account_type] if filters.account_type else [],
			"include_disabled": filters.include_disabled,
		},
	)
	return columns, rows
