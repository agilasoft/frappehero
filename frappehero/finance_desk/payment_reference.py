# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Show the referenced document's currency on Payment Entry references."""

import frappe
from frappe import _

from frappehero.finance_desk.payment_reference_logic import (
	columns_for_references,
	should_write_invoice_currency,
	source_from_document,
	source_from_dunning,
	source_from_journal,
)
from frappehero.flags import clean_text, parse_payload

_DOCUMENT_TYPES = (
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
	"Expense Claim",
)


def set_invoice_currency(doc, method=None):
	"""Copy the reference currency and its own total onto the payment.

	A draft save and the submit that follows it both write the columns. Frappe
	marks the payment submitted before ``before_validate``. A payment that is
	already submitted is left as it was saved. Grand Total, Outstanding, and
	Allocated stay in the party account currency.
	"""
	if not should_write_invoice_currency(doc.docstatus, getattr(doc, "_action", None)) or not _ready():
		return
	references = doc.get("references") or []
	rows = _rows(references)
	columns = columns_for_references(rows, _sources(doc.get("party_type"), doc.get("party"), rows))
	for reference, column in zip(references, columns, strict=True):
		reference.hero_invoice_currency = column["hero_invoice_currency"]
		reference.hero_invoice_amount = column["hero_invoice_amount"]


@frappe.whitelist()
def invoice_currency_for_references(references=None, party_type=None, party=None):
	"""Return Invoice Currency and Invoice Currency Amount for each reference row."""
	if not frappe.has_permission("Payment Entry", ptype="read"):
		frappe.throw(_("Not permitted to read payment references."), frappe.PermissionError)
	rows = _rows(parse_payload(references, []))
	return columns_for_references(rows, _sources(party_type, party, rows))


def _rows(references):
	if isinstance(references, str):
		references = parse_payload(references, [])
	if isinstance(references, dict):
		references = [references]
	rows = []
	for reference in references or []:
		if not hasattr(reference, "get"):
			rows.append({"reference_doctype": "", "reference_name": ""})
			continue
		rows.append(
			{
				"reference_doctype": clean_text(reference.get("reference_doctype")),
				"reference_name": clean_text(reference.get("reference_name")),
			}
		)
	return rows


def _sources(party_type, party, rows):
	grouped = {}
	for row in rows:
		if row["reference_doctype"] and row["reference_name"]:
			grouped.setdefault(row["reference_doctype"], set()).add(row["reference_name"])
	sources = {}
	for doctype, names in grouped.items():
		for name, source in _sources_for(doctype, names, party_type, party).items():
			sources[(doctype, name)] = source
	return sources


def _sources_for(doctype, names, party_type, party):
	names = [name for name in names if name]
	if not names or not frappe.db.exists("DocType", doctype):
		return {}
	if doctype in _DOCUMENT_TYPES:
		return _document_sources(doctype, names)
	if doctype == "Journal Entry":
		return _journal_sources(names, party_type, party)
	if doctype == "Dunning":
		return _dunning_sources(names)
	return {}


def _document_sources(doctype, names):
	meta = frappe.get_meta(doctype)
	if not meta.has_field("currency"):
		return {}
	fields = ["name", "currency"]
	if meta.has_field("rounded_total"):
		fields.append("rounded_total")
	if meta.has_field("grand_total"):
		fields.append("grand_total")
	found = {}
	for row in _fetch(doctype, names, fields):
		found[row.name] = source_from_document(row)
	return found


def _dunning_sources(names):
	meta = frappe.get_meta("Dunning")
	has_currency = meta.has_field("currency")
	fields = ["name"]
	if has_currency:
		fields.append("currency")
	if meta.has_field("grand_total"):
		fields.append("grand_total")
	if meta.has_field("dunning_amount"):
		fields.append("dunning_amount")
	found = {}
	for row in _fetch("Dunning", names, fields):
		found[row.name] = source_from_dunning(row, has_currency)
	return found


def _journal_sources(names, party_type, party):
	if not frappe.db.exists("DocType", "Journal Entry Account"):
		return {}
	lines = frappe.db.get_all(
		"Journal Entry Account",
		filters={"parent": ["in", names], "parenttype": "Journal Entry"},
		fields=[
			"parent",
			"party_type",
			"party",
			"account_currency",
			"debit_in_account_currency",
			"credit_in_account_currency",
		],
		limit_page_length=0,
	)
	grouped = {name: [] for name in names}
	for line in lines:
		grouped.setdefault(line.parent, []).append(line)
	return {name: source_from_journal(grouped.get(name) or [], party_type, party) for name in names}


def _fetch(doctype, names, fields):
	return frappe.db.get_all(
		doctype,
		filters={"name": ["in", names]},
		fields=fields,
		limit_page_length=0,
	)


def _ready():
	if not frappe.db.exists("DocType", "Payment Entry Reference"):
		return False
	meta = frappe.get_meta("Payment Entry Reference")
	return meta.has_field("hero_invoice_currency") and meta.has_field("hero_invoice_amount")
