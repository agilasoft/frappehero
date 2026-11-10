# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from frappehero.dispute_desk.logic import (
	dispute_tab_field_order,
	dispute_tab_fieldnames,
	sales_invoice_dispute_fields,
)
from frappehero.flags import clean_text


def after_install():
	ensure_custom_fields()


def after_migrate():
	ensure_custom_fields()
	remove_retired_doctypes()


def remove_retired_doctypes():
	"""Drop the standalone multi-currency voucher once Payment Entry owns it."""
	for name in ("Hero Multi Currency Payment", "Hero Multi Currency Allocation"):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=1, ignore_permissions=True)


def ensure_custom_fields():
	"""Mark rows Frappe Hero owns, without forking the standard DocTypes."""
	fields = get_custom_fields()
	if not frappe.db.exists("DocType", "Opening Invoice Creation Tool Item"):
		fields.pop("Opening Invoice Creation Tool Item", None)
	if not frappe.db.exists("DocType", "Payment Entry Reference"):
		fields.pop("Payment Entry Reference", None)
	create_custom_fields(fields, ignore_validate=True, update=True)
	ensure_opening_invoice_extension()
	ensure_sales_invoice_dispute_tab()


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
	# The dropdown reads this DocField. A property setter alone stays invisible
	# while the browser is still holding the Sales and Purchase copy.
	frappe.db.set_value(
		"DocField",
		{"parent": "Opening Invoice Creation Tool", "fieldname": "invoice_type"},
		"options",
		INVOICE_TYPE_OPTIONS,
		update_modified=False,
	)
	# The desk stores this DocType in the browser and reuses it while
	# DocType.modified is unchanged. A property setter does not move that
	# timestamp, so Invoice Type stays Sales and Purchase.
	frappe.db.set_value(
		"DocType",
		"Opening Invoice Creation Tool",
		"modified",
		frappe.utils.now(),
	)
	frappe.clear_cache(doctype="Opening Invoice Creation Tool")
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
		frappe.clear_cache(doctype="Opening Invoice Creation Tool Item")


def ensure_sales_invoice_dispute_tab():
	"""Move a saved Sales Invoice field order onto the Dispute tab.

	Customize Form stores the whole field order. While that list still has the
	Dispute section after the customer, Company and the posting dates stay
	inside it, and insert_after is ignored.
	"""
	if not frappe.db.exists("DocType", "Sales Invoice"):
		return
	if not frappe.db.exists("DocType", "Property Setter"):
		return
	rows = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": "Sales Invoice",
			"doctype_or_field": "DocType",
			"property": "field_order",
		},
		fields=["name", "value"],
	)
	if not rows:
		return
	frappe.clear_cache(doctype="Sales Invoice")
	meta = frappe.get_meta("Sales Invoice")
	present = [name for name in dispute_tab_fieldnames() if meta.has_field(name)]
	changed = False
	for row in rows:
		try:
			current = frappe.parse_json(row.value)
		except (TypeError, ValueError):
			continue
		if not isinstance(current, list):
			continue
		cleaned = [clean_text(item) for item in current if clean_text(item)]
		updated = dispute_tab_field_order(cleaned + [name for name in present if name not in cleaned])
		if updated == cleaned:
			continue
		frappe.db.set_value(
			"Property Setter",
			row.name,
			"value",
			json.dumps(updated),
			update_modified=False,
		)
		changed = True
	if changed:
		frappe.clear_cache(doctype="Sales Invoice")


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
			{
				"fieldname": "hero_multi_account",
				"label": "Multiple Accounts",
				"fieldtype": "Check",
				"insert_after": "party",
				"read_only": 1,
				"no_copy": 1,
				"default": "0",
				"description": "Set when the references use more than one receivable or payable account. The payment still submits as a Payment Entry.",
			},
		],
		"Payment Entry Reference": [
			{
				"fieldname": "hero_invoice_currency",
				"label": "Invoice Currency",
				"fieldtype": "Link",
				"options": "Currency",
				"insert_after": "allocated_amount",
				"read_only": 1,
				"no_copy": 1,
				"in_list_view": 1,
				"columns": 2,
			},
			{
				"fieldname": "hero_invoice_amount",
				"label": "Invoice Currency Amount",
				"fieldtype": "Currency",
				"options": "hero_invoice_currency",
				"insert_after": "hero_invoice_currency",
				"read_only": 1,
				"no_copy": 1,
				"in_list_view": 1,
				"columns": 2,
				"description": "Total of the reference in its own currency. Grand Total stays in the party account currency.",
			},
			{
				"fieldname": "hero_allocated_invoice_amount",
				"label": "Allocated (Invoice Currency)",
				"fieldtype": "Currency",
				"options": "hero_invoice_currency",
				"insert_after": "hero_invoice_amount",
				"in_list_view": 1,
				"columns": 2,
				"description": "Amount of this invoice to pay, in the invoice currency. Outstanding is in this currency.",
			},
			{
				"fieldname": "hero_account",
				"label": "Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "hero_allocated_invoice_amount",
				"in_list_view": 1,
				"columns": 2,
				"description": "Receivable or payable account for this invoice. It can differ from the party account on the payment.",
			},
			{
				"fieldname": "hero_account_currency",
				"label": "Account Currency",
				"fieldtype": "Link",
				"options": "Currency",
				"insert_after": "hero_account",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "hero_allocated_account_amount",
				"label": "Allocated (Account Currency)",
				"fieldtype": "Currency",
				"options": "hero_account_currency",
				"insert_after": "hero_account_currency",
				"read_only": 1,
				"no_copy": 1,
				"in_list_view": 1,
				"columns": 2,
				"description": "Calculated from the invoice-currency allocation and the invoice conversion rate.",
			},
			{
				"fieldname": "hero_booked_rate",
				"label": "Booked Rate",
				"fieldtype": "Float",
				"precision": "9",
				"insert_after": "hero_allocated_account_amount",
				"read_only": 1,
				"no_copy": 1,
				"description": "Invoice conversion rate. Company currency for one unit of the invoice currency. This calculates the account-currency allocation.",
			},
			{
				"fieldname": "hero_payment_rate",
				"label": "Payment Rate",
				"fieldtype": "Float",
				"precision": "9",
				"insert_after": "hero_booked_rate",
				"in_list_view": 1,
				"columns": 1,
				"description": "Company currency for one unit of the invoice currency on the posting date. This turns the invoice allocation into the bank amount.",
			},
			{
				"fieldname": "hero_payment_currency",
				"label": "Payment Currency",
				"fieldtype": "Link",
				"options": "Currency",
				"insert_after": "hero_payment_rate",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "hero_bank_amount",
				"label": "Bank Amount",
				"fieldtype": "Currency",
				"options": "hero_payment_currency",
				"insert_after": "hero_payment_currency",
				"read_only": 1,
				"no_copy": 1,
				"in_list_view": 1,
				"columns": 2,
				"description": "Share of the bank amount for this invoice.",
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
