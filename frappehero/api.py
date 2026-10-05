# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe

from frappehero.catalog import ideas_for


@frappe.whitelist()
def has_app_permission() -> bool:
	roles = set(frappe.get_roles())
	return bool(roles.intersection({"System Manager", "Accounts Manager"}))


@frappe.whitelist()
def get_module_ideas(area: str | None = None, text: str | None = None) -> list:
	frappe.only_for(["System Manager", "Accounts Manager"])
	return ideas_for(area, text)
