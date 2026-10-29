# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from frappehero.dispute_desk.logic import sales_invoice_dispute_fields


def after_install():
	ensure_custom_fields()


def after_migrate():
	ensure_custom_fields()


def ensure_custom_fields():
	"""Mark rows Frappe Hero owns, without forking the standard DocTypes."""
	fields = get_custom_fields()
	if not frappe.db.exists("DocType", "Opening Invoice Creation Tool Item"):
		fields.pop("Opening Invoice Creation Tool Item", None)
	create_custom_fields(fields, ignore_validate=True, update=True)
	ensure_opening_invoice_extension()


def ensure_opening_invoice_extension():
	"""Add Credit Note and Debit Note to the Opening Invoice Creation Tool."""
	if not frappe.db.exists("DocType", "Opening Invoice Creation Tool"):
		return
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	from frappehero.finance_desk.opening_invoice_logic import INVOICE_TYPE_OPTIONS

	make_property_setter(
		"Opening Invoice Creation Tool",
		"invoice_type",
		"options",
		INVOICE_TYPE_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)
	if not frappe.db.exists("DocType", "Opening Invoice Creation Tool Item"):
		return
	if frappe.get_meta("Opening Invoice Creation Tool Item").has_field("supplier_invoice_date"):
		make_property_setter(
			"Opening Invoice Creation Tool Item",
			"supplier_invoice_date",
			"depends_on",
			'eval: parent.invoice_type == "Purchase" || parent.invoice_type == "Debit Note"',
			"Data",
			validate_fields_for_doctype=False,
		)


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
		],
		"Sales Invoice": sales_invoice_dispute_fields(),
		"Currency Exchange": [
			{
				"fieldname": "hero_bsp_section",
				"label": "Frappe Hero",
				"fieldtype": "Section Break",
				"insert_after": "for_selling",
				"collapsible": 1,
			},
			{
				"fieldname": "hero_bsp",
				"label": "BSP Rate",
				"fieldtype": "Check",
				"insert_after": "hero_bsp_section",
				"read_only": 1,
				"no_copy": 1,
				"default": "0",
				"in_standard_filter": 1,
				"description": "Set by Frappe Hero from the BSP reference bulletin. A rate entered by hand is left in place.",
			},
		],
		"Mode of Payment": [
			{
				"fieldname": "hero_uses_cheque_leaf",
				"label": "Uses Cheque Leaf",
				"fieldtype": "Check",
				"insert_after": "type",
				"default": "0",
				"description": "Pay entries with this mode take a cheque number from the bank account's Cheque Leaf. A mode named cheque or check does this without the tick.",
			},
		],
		"Payment Entry": [
			{
				"fieldname": "hero_cheque_section",
				"label": "Cheque Leaf",
				"fieldtype": "Section Break",
				"insert_after": "reference_date",
				"collapsible": 1,
				"depends_on": "eval:doc.payment_type=='Pay'",
			},
			{
				"fieldname": "hero_cheque_leaf",
				"label": "Cheque Leaf",
				"fieldtype": "Link",
				"options": "Hero Cheque Leaf",
				"insert_after": "hero_cheque_section",
				"depends_on": "eval:doc.payment_type=='Pay'",
				"in_standard_filter": 1,
				"description": "The set of cheque numbers for this company bank account.",
			},
			{
				"fieldname": "hero_cheque_number",
				"label": "Cheque Number",
				"fieldtype": "Data",
				"insert_after": "hero_cheque_leaf",
				"depends_on": "eval:doc.payment_type=='Pay'",
				"no_copy": 1,
				"in_standard_filter": 1,
				"description": "A number from the Cheque Leaf. Saved onto Cheque/Reference No.",
			},
			{
				"fieldname": "hero_cheque_column",
				"fieldtype": "Column Break",
				"insert_after": "hero_cheque_number",
				"depends_on": "eval:doc.payment_type=='Pay'",
			},
			{
				"fieldname": "hero_cheque_state",
				"label": "Cheque State",
				"fieldtype": "Data",
				"insert_after": "hero_cheque_column",
				"read_only": 1,
				"no_copy": 1,
				"depends_on": "eval:doc.payment_type=='Pay'",
			},
		],
		"Opening Invoice Creation Tool Item": [
			{
				"fieldname": "hero_against_invoice",
				"label": "Against Invoice",
				"fieldtype": "Data",
				"insert_after": "invoice_number",
				"in_list_view": 1,
				"depends_on": 'eval: parent.invoice_type == "Credit Note" || parent.invoice_type == "Debit Note"',
				"description": "The sales invoice this credit note reduces, or the purchase invoice this debit note reduces. Leave this blank for a note that stands on its own. A submitted invoice in this company is linked. Any other number is stored on the note.",
			},
		],
		"DocShare": [
			{
				"fieldname": "hero_expires_on",
				"label": "Expires On",
				"fieldtype": "Date",
				"insert_after": "read",
				"in_standard_filter": 1,
				"description": "Share Desk deletes this share after the date.",
			},
			{
				"fieldname": "hero_permission_group",
				"label": "Permission Group",
				"fieldtype": "Link",
				"options": "Hero Permission Group",
				"insert_after": "hero_expires_on",
				"read_only": 1,
				"no_copy": 1,
			},
		],
	}
