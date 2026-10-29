# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Credit notes and debit notes for the Opening Invoice Creation Tool.

ERPNext's tool uploads Sales and Purchase opening invoices. A credit note is a
return Sales Invoice. A debit note is a return Purchase Invoice. The rules
here are pure so they can be tested without a site.
"""

import math

from frappehero.flags import clean_text

SALES = "Sales"
PURCHASE = "Purchase"
CREDIT_NOTE = "Credit Note"
DEBIT_NOTE = "Debit Note"

INVOICE_TYPE_OPTIONS = "\n".join((SALES, PURCHASE, CREDIT_NOTE, DEBIT_NOTE))
GENERIC_ITEM = "opening invoice item"

_KINDS = {
	SALES: {
		"label": SALES,
		"base_type": SALES,
		"doctype": "Sales Invoice",
		"party_type": "Customer",
		"item_name": "Opening Invoice Item",
		"is_return": 0,
	},
	PURCHASE: {
		"label": PURCHASE,
		"base_type": PURCHASE,
		"doctype": "Purchase Invoice",
		"party_type": "Supplier",
		"item_name": "Opening Invoice Item",
		"is_return": 0,
	},
	CREDIT_NOTE: {
		"label": CREDIT_NOTE,
		"base_type": SALES,
		"doctype": "Sales Invoice",
		"party_type": "Customer",
		"item_name": "Opening Credit Note",
		"is_return": 1,
	},
	DEBIT_NOTE: {
		"label": DEBIT_NOTE,
		"base_type": PURCHASE,
		"doctype": "Purchase Invoice",
		"party_type": "Supplier",
		"item_name": "Opening Debit Note",
		"is_return": 1,
	},
}
_BY_NAME = {name.casefold(): kind for name, kind in _KINDS.items()}


class OpeningInvoiceError(ValueError):
	"""The invoice type cannot be turned into an opening invoice."""


def invoice_kind(invoice_type) -> dict:
	"""Sales, Purchase, Credit Note, or Debit Note. The match ignores case."""
	text = clean_text(invoice_type)
	kind = _BY_NAME.get(text.casefold())
	if not kind:
		raise OpeningInvoiceError(
			f"{text or 'Invoice Type'} is not Sales, Purchase, Credit Note, or Debit Note."
		)
	return dict(kind)


def is_note(invoice_type) -> bool:
	"""True when this upload creates a credit note or a debit note."""
	try:
		return bool(invoice_kind(invoice_type)["is_return"])
	except OpeningInvoiceError:
		return False


def return_line(qty, rate) -> tuple[float, float]:
	"""Negative quantity and a positive rate, for the absolute line amount.

	The uploaded amount may already be negative. A credit note and a debit
	note still reduce the party balance, so the quantity is stored negative
	and the rate stays positive. ERPNext rejects the other way around.
	"""
	quantity = abs(_number(qty))
	price = abs(_number(rate))
	if quantity == 0:
		quantity = 1.0
	return -quantity, price


def retitle(current, replacement) -> str:
	"""Use the note title when the row still has the generic opening item."""
	text = clean_text(current)
	folded = text.casefold()
	if not text or folded == GENERIC_ITEM:
		return replacement
	prefix = "Opening Invoice Item"
	if folded.startswith(GENERIC_ITEM + " "):
		return replacement + text[len(prefix) :]
	return text


def against_can_link(name, company, invoice_company, docstatus) -> bool:
	"""A submitted invoice in the same company can be Return Against.

	A blank company on the existing invoice does not block the link. A draft
	or cancelled invoice stays unlinked and the number is kept as text.
	"""
	if not clean_text(name):
		return False
	try:
		status = int(docstatus)
	except (TypeError, ValueError):
		return False
	if status != 1:
		return False
	expected = clean_text(company)
	actual = clean_text(invoice_company)
	if expected and actual and expected != actual:
		return False
	return True


def apply_note(invoice, kind, against, linked) -> dict:
	"""Turn an opening invoice dict into a credit note or a debit note.

	Sales and Purchase invoices are returned as they are. The input dict is
	left unchanged.
	"""
	if not invoice or not kind or not kind.get("is_return"):
		return invoice
	items = []
	for item in invoice.get("items") or []:
		rewritten = _clone(item)
		qty, rate = return_line(rewritten.get("qty"), rewritten.get("rate"))
		rewritten["qty"] = qty
		rewritten["rate"] = rate
		title = retitle(rewritten.get("item_name"), kind["item_name"])
		rewritten["item_name"] = title
		rewritten["description"] = retitle(rewritten.get("description"), kind["item_name"])
		items.append(rewritten)
	# Keep frappe._dict. dict() drops attribute access, and the importer reads
	# invoice.invoice_number before it builds the document.
	stamped = _clone(invoice)
	stamped["items"] = items
	stamped["doctype"] = kind["doctype"]
	stamped["is_return"] = 1
	reference = clean_text(against)
	if reference and linked:
		stamped["return_against"] = reference
		stamped["update_outstanding_for_self"] = 0
		return stamped
	stamped["update_outstanding_for_self"] = 1
	if reference:
		note = f"Against invoice {reference}"
		remarks = clean_text(stamped.get("remarks"))
		stamped["remarks"] = f"{remarks} {note}".strip() if remarks else note
	return stamped


def _clone(mapping):
	"""Copy a mapping and keep its type.

	``dict(value)`` and ``dict.copy`` both return a plain dict. ERPNext's
	opening-invoice importer then fails on ``invoice.invoice_number``.
	"""
	kind = type(mapping)
	if kind is dict:
		return dict(mapping)
	try:
		return kind(mapping)
	except (TypeError, ValueError):
		return dict(mapping)


def _number(value) -> float:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return 0.0
	if not math.isfinite(number):
		return 0.0
	return number
