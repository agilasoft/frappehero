# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
	ensure_custom_fields()


def after_migrate():
	ensure_custom_fields()


def ensure_custom_fields():
	"""Mark User Permissions that Permission Studio owns, without forking the DocType."""
	create_custom_fields(get_custom_fields(), ignore_validate=True, update=True)


def get_custom_fields():
	return {
		"User Permission": [
			{
				"fieldname": "hero_section",
				"label": "Frappe Hero",
				"fieldtype": "Section Break",
				"insert_after": "hide_descendants",
				"collapsible": 1,
			},
			{
				"fieldname": "hero_managed",
				"label": "Managed by Frappe Hero",
				"fieldtype": "Check",
				"insert_after": "hero_section",
				"read_only": 1,
				"no_copy": 1,
				"default": "0",
				"in_standard_filter": 1,
				"description": "Set by Permission Studio. Edit the permission group to change this row.",
			},
			{
				"fieldname": "hero_permission_group",
				"label": "Permission Group",
				"fieldtype": "Link",
				"options": "Hero Permission Group",
				"insert_after": "hero_managed",
				"read_only": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "hero_source_groups",
				"label": "Source Groups",
				"fieldtype": "Small Text",
				"insert_after": "hero_permission_group",
				"read_only": 1,
				"no_copy": 1,
				"description": "Every permission group that grants this same user, DocType, and value.",
			},
		]
	}
