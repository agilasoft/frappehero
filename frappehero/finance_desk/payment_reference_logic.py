# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Invoice currency columns for Payment Entry references.

Pure functions. The desk and Payment Entry call these, and the tests run
without a site.
"""

from frappehero.flags import clean_text

# A supplier or employee balance is a credit. Everyone else used here is a debit.
_CREDIT_BALANCE = {"Supplier", "Employee"}


def source_from_document(row):
	"""Invoice, order, or expense claim row that has a currency of its own.

	``rounded_total`` is preferred later, when it is set. A zero rounded total
	falls through to the grand total.
	"""
	if not row:
		return None
	currency = clean_text(row.get("currency"))
	if not currency:
		return None
	source = {"currency": currency, "grand_total": row.get("grand_total")}
	if "rounded_total" in row:
		source["rounded_total"] = row.get("rounded_total")
	return source


def source_from_dunning(row, has_currency_field):
	"""Dunning contributes a currency only when that field exists on the document.

	The amount is the grand total. A zero grand total uses the dunning amount.
	"""
	if not has_currency_field or not row:
		return None
	currency = clean_text(row.get("currency"))
	if not currency:
		return None
	if _optional_number(row.get("grand_total")):
		return {"currency": currency, "grand_total": row.get("grand_total")}
	return {"currency": currency, "amount": row.get("dunning_amount")}


def source_from_journal(lines, party_type, party):
	"""Sum the party lines of one journal entry into a single currency and amount.

	Lines for a different party are left out. Customer amounts are debit minus
	credit. Supplier and employee amounts are credit minus debit, so the usual
	bill stays positive and a note reduces it. Two currencies on the matching
	lines leave the columns blank rather than adding different units.
	"""
	party_type = clean_text(party_type)
	party = clean_text(party)
	if not party_type or not party:
		return None
	matched = [
		line
		for line in lines or []
		if clean_text(line.get("party_type")) == party_type and clean_text(line.get("party")) == party
	]
	if not matched:
		return None
	currencies = {clean_text(line.get("account_currency")) for line in matched}
	currencies.discard("")
	if len(currencies) != 1:
		return None
	total = sum(journal_line_amount(line, party_type) for line in matched)
	return {"currency": currencies.pop(), "amount": total}


def journal_line_amount(line, party_type) -> float:
	"""Account-currency amount of one party line, signed for that party type."""
	debit = _number(line.get("debit_in_account_currency"))
	credit = _number(line.get("credit_in_account_currency"))
	if clean_text(party_type) in _CREDIT_BALANCE:
		return credit - debit
	return debit - credit


def invoice_amount(source) -> float:
	"""Rounded total when it is set, otherwise the grand total, otherwise ``amount``.

	Zero does not count as set. A negative return does.
	"""
	if not source:
		return 0.0
	for fieldname in ("rounded_total", "grand_total", "amount"):
		number = _optional_number(source.get(fieldname))
		if number:
			return number
	return 0.0


def should_write_invoice_currency(docstatus, action) -> bool:
	"""True for a draft save, and for the submit that follows it.

	Frappe sets docstatus to submitted before ``before_validate``. A payment
	that is already submitted (``update_after_submit``) is not rewritten.
	"""
	try:
		status = int(docstatus or 0)
	except (TypeError, ValueError):
		return False
	action = clean_text(action) or None
	if status == 0:
		return action in (None, "save", "submit")
	return status == 1 and action == "submit"


def columns_for_references(references, sources):
	"""One Invoice Currency pair per reference, in the same order.

	``sources`` is keyed by ``(reference_doctype, reference_name)``. A missing
	source, a blank row, or a source with no currency yields an empty currency
	and ``0``.
	"""
	sources = sources or {}
	columns = []
	for reference in references or []:
		doctype = clean_text((reference or {}).get("reference_doctype"))
		name = clean_text((reference or {}).get("reference_name"))
		source = sources.get((doctype, name)) if doctype and name else None
		currency = clean_text((source or {}).get("currency"))
		if not currency:
			columns.append({"hero_invoice_currency": "", "hero_invoice_amount": 0.0})
			continue
		columns.append(
			{
				"hero_invoice_currency": currency,
				"hero_invoice_amount": invoice_amount(source),
			}
		)
	return columns


def _optional_number(value):
	if value is None or value is False or value == "":
		return None
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _number(value) -> float:
	return _optional_number(value) or 0.0
