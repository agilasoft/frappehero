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


# Opening Invoice summary rows. A credit note is an opening Sales Invoice with
# is_return set. A debit note is an opening Purchase Invoice with is_return set.
# The desk summary renders these labels in this order.
OPENING_SUMMARY_ROWS = (
	{"label": "Sales Invoice", "doctype": "Sales Invoice", "is_return": 0},
	{"label": "Credit Note", "doctype": "Sales Invoice", "is_return": 1},
	{"label": "Purchase Invoice", "doctype": "Purchase Invoice", "is_return": 0},
	{"label": "Debit Note", "doctype": "Purchase Invoice", "is_return": 1},
)


def summary_label(doctype, is_return) -> str:
	"""Sales Invoice, Credit Note, Purchase Invoice, or Debit Note."""
	flag = 1 if _is_return(is_return) else 0
	for row in OPENING_SUMMARY_ROWS:
		if row["doctype"] == doctype and row["is_return"] == flag:
			return row["label"]
	return doctype


def fold_opening_summary(company_currency, rows_by_doctype) -> tuple:
	"""Split opening invoice totals so notes are not folded into invoices.

	`rows_by_doctype` maps Sales Invoice and Purchase Invoice to company rows
	that include is_return, total_invoices, and outstanding_amount. Outstanding
	keeps its sign: a credit balance stays negative.
	"""
	summary = {}
	for doctype, rows in (rows_by_doctype or {}).items():
		for row in rows or []:
			company = _row_value(row, "company")
			if not company:
				continue
			label = summary_label(doctype, _row_value(row, "is_return"))
			company_summary = summary.setdefault(company, {"currency": (company_currency or {}).get(company)})
			bucket = company_summary.setdefault(label, {"total_invoices": 0, "outstanding_amount": 0.0})
			bucket["total_invoices"] += int(_number(_row_value(row, "total_invoices")))
			bucket["outstanding_amount"] += _number(_row_value(row, "outstanding_amount"))

	max_count = {}
	for company_summary in summary.values():
		for label, bucket in list(company_summary.items()):
			if label == "currency":
				continue
			if not bucket["total_invoices"]:
				company_summary.pop(label, None)
				continue
			due = bucket["outstanding_amount"]
			if not due:
				continue
			current = max_count.setdefault(label, {"max_paid": 0.0, "max_due": due})
			if due > current["max_due"]:
				current["max_due"] = due

	summary = {
		company: values for company, values in summary.items() if any(key != "currency" for key in values)
	}
	return summary, max_count


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

	Sales and Purchase invoices are returned as they are. The input mapping is
	left unchanged. A credit or debit note is a copy of the same mapping class:
	ERPNext's importer reads invoice_number and doctype as attributes, and a
	plain dict copy drops that access.
	"""
	if not invoice or not kind or not kind.get("is_return"):
		return invoice
	items = []
	for item in invoice.get("items") or []:
		rewritten = _copy_mapping(item)
		qty, rate = return_line(rewritten.get("qty"), rewritten.get("rate"))
		rewritten["qty"] = qty
		rewritten["rate"] = rate
		title = retitle(rewritten.get("item_name"), kind["item_name"])
		rewritten["item_name"] = title
		rewritten["description"] = retitle(rewritten.get("description"), kind["item_name"])
		items.append(rewritten)
	stamped = _copy_mapping(invoice)
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


def _copy_mapping(value):
	"""Copy a mapping without dropping attribute access on dict subclasses."""
	if isinstance(value, dict):
		return type(value)(value)
	return dict(value)


def _is_return(value) -> bool:
	return value is True or str(value).strip() == "1"


def _row_value(row, key):
	if isinstance(row, dict):
		return row.get(key)
	return getattr(row, key, None)


def _number(value) -> float:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return 0.0
	if not math.isfinite(number):
		return 0.0
	return number
