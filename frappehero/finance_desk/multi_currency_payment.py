# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Load invoices, rates, and the journal for a multi-currency payment."""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _

from frappehero.finance_desk.multi_currency_payment_logic import (
	MultiCurrencyPaymentError,
	payment_type_for,
	prepare_payment,
)
from frappehero.flags import clean_text, parse_payload

_INVOICE_FIELDS = {
	"Customer": ("Sales Invoice", "customer", "debit_to"),
	"Supplier": ("Purchase Invoice", "supplier", "credit_to"),
}


def calculate(doc):
	"""Refresh invoice amounts and write the balanced totals back onto the payment."""
	party_type = clean_text(doc.party_type)
	if party_type not in _INVOICE_FIELDS:
		frappe.throw(_("Party type must be Customer or Supplier."))
	party = clean_text(doc.party)
	company = clean_text(doc.company)
	if not company:
		frappe.throw(_("Company is required."))
	if not party:
		frappe.throw(_("Party is required."))
	if not doc.posting_date:
		frappe.throw(_("Posting date is required."))
	defaults = company_defaults(company)
	doc.company_currency = defaults.default_currency
	doc.party_type = party_type
	doc.party = party
	doc.payment_type = payment_type_for(party_type)
	bank = bank_account(doc.bank_account, company)
	doc.payment_currency = bank.account_currency
	doc.payment_exchange_rate = exchange_rate(
		doc.payment_currency,
		doc.company_currency,
		doc.posting_date,
		doc.payment_exchange_rate,
	)
	advance_currency, advance_rate = _advance_rate(doc, company, party_type)
	sources = []
	for row in doc.get("allocations") or []:
		source = _source_from_row(doc, row, defaults)
		if source is not None:
			sources.append(source)
	try:
		prepared = prepare_payment(
			_payment_args(doc, bank.name, defaults, advance_currency, advance_rate), sources
		)
	except MultiCurrencyPaymentError as exc:
		frappe.throw(str(exc))
	_apply(doc, prepared)
	return prepared


def post_journal(doc, prepared):
	"""Insert and submit the Bank Entry, then store its name on the payment."""
	if doc.journal_entry:
		return doc.journal_entry
	if not clean_text(doc.reference_no) or not doc.reference_date:
		frappe.throw(_("Reference No and Reference Date are required."))
	journal = frappe.get_doc(_journal_payload(doc, prepared))
	journal.flags.ignore_permissions = True
	journal.insert(ignore_permissions=True)
	journal.flags.ignore_permissions = True
	journal.submit()
	doc.db_set("journal_entry", journal.name)
	return journal.name


def cancel_journal(doc):
	"""Cancel the Bank Entry that this payment submitted."""
	name = clean_text(doc.journal_entry)
	if not name or not frappe.db.exists("Journal Entry", name):
		return
	journal = frappe.get_doc("Journal Entry", name)
	if int(journal.docstatus or 0) != 1:
		return
	previous = frappe.flags.ignore_links
	frappe.flags.ignore_links = True
	try:
		journal.flags.ignore_permissions = True
		journal.flags.ignore_links = True
		journal.cancel()
	finally:
		frappe.flags.ignore_links = previous


@frappe.whitelist()
def outstanding_invoices(
	company=None,
	party_type=None,
	party=None,
	posting_date=None,
	bank_account=None,
	payment_exchange_rate=None,
):
	"""Return open invoices for the party across every receivable or payable account."""
	_require_read()
	party_type = clean_text(party_type)
	company = clean_text(company)
	party = clean_text(party)
	bank_name = clean_text(bank_account)
	if party_type not in _INVOICE_FIELDS:
		frappe.throw(_("Party type must be Customer or Supplier."))
	if not company or not party or not posting_date or not bank_name:
		frappe.throw(_("Company, party, posting date, and bank account are required."))
	defaults = company_defaults(company)
	bank = bank_account(bank_name, company)
	rate = exchange_rate(
		bank.account_currency,
		defaults.default_currency,
		posting_date,
		payment_exchange_rate,
	)
	doctype, party_field, account_field = _INVOICE_FIELDS[party_type]
	invoices = frappe.get_all(
		doctype,
		filters={
			"company": company,
			"docstatus": 1,
			party_field: party,
			"outstanding_amount": [">", 0],
		},
		fields=["name", "currency", "conversion_rate", "outstanding_amount", account_field, "posting_date"],
		order_by="posting_date asc, name asc",
		limit_page_length=0,
	)
	if not invoices:
		frappe.throw(_("There are no outstanding invoices for {0}.").format(party))
	rows = []
	for invoice in invoices:
		account = party_account(invoice.get(account_field), company, party_type)
		booked_rate, row_rate = _invoice_rates(
			account.account_currency,
			defaults.default_currency,
			invoice.conversion_rate,
			None,
			posting_date,
		)
		rows.append(
			{
				"account": account.name,
				"account_currency": account.account_currency,
				"reference_doctype": doctype,
				"reference_name": invoice.name,
				"invoice_currency": invoice.currency,
				"outstanding_amount": invoice.outstanding_amount,
				"allocated_amount": invoice.outstanding_amount,
				"booked_rate": booked_rate,
				"payment_rate": row_rate,
				"payment_currency": bank.account_currency,
			}
		)
	try:
		prepared = prepare_payment(
			{
				"party_type": party_type,
				"party": party,
				"company_currency": defaults.default_currency,
				"payment_currency": bank.account_currency,
				"payment_exchange_rate": rate,
				"paid_amount": None,
				"bank_account": bank.name,
				"gain_loss_account": defaults.get("exchange_gain_loss_account"),
				"cost_center": defaults.get("cost_center"),
			},
			rows,
		)
	except MultiCurrencyPaymentError as exc:
		frappe.throw(str(exc))
	for row, computed in zip(rows, prepared["allocations"], strict=True):
		row.update(
			{
				"outstanding_amount": computed["outstanding_amount"],
				"allocated_amount": computed["allocated_amount"],
				"booked_rate": computed["booked_rate"],
				"payment_rate": computed["payment_rate"],
				"payment_amount": computed["payment_amount"],
			}
		)
	return {
		"payment_type": prepared["payment_type"],
		"company_currency": defaults.default_currency,
		"payment_currency": bank.account_currency,
		"payment_exchange_rate": rate,
		"paid_amount": prepared["paid_amount"],
		"allocated_amount": prepared["allocated_amount"],
		"unallocated_amount": prepared["unallocated_amount"],
		"base_paid_amount": prepared["base_paid_amount"],
		"exchange_gain_loss": prepared["exchange_gain_loss"],
		"multi_currency": prepared["multi_currency"],
		"allocations": rows,
	}


@frappe.whitelist()
def preview(payment=None):
	"""Recompute totals for an unsaved payment without writing it."""
	_require_read()
	parsed = parse_payload(payment, {})
	if not isinstance(parsed, dict):
		frappe.throw(_("The payment could not be read."))
	parsed["doctype"] = "Hero Multi Currency Payment"
	doc = frappe.get_doc(parsed)
	prepared = calculate(doc)
	return _summary(doc, prepared)


def company_defaults(company):
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist.").format(company))
	meta = frappe.get_meta("Company")
	fields = ["default_currency"]
	if meta.has_field("exchange_gain_loss_account"):
		fields.append("exchange_gain_loss_account")
	if meta.has_field("cost_center"):
		fields.append("cost_center")
	row = frappe.db.get_value("Company", company, fields, as_dict=True) or {}
	if not row.get("default_currency"):
		frappe.throw(_("Company {0} needs a default currency.").format(company))
	return row


def bank_account(name, company):
	row = ledger(name, company)
	if row.account_type not in ("Bank", "Cash"):
		frappe.throw(_("{0} is not a bank or cash account.").format(row.name))
	return row


def party_account(name, company, party_type):
	row = ledger(name, company)
	expected = "Receivable" if party_type == "Customer" else "Payable"
	if row.account_type != expected:
		frappe.throw(_("{0} is not a {1} account.").format(row.name, expected.lower()))
	return row


def ledger(name, company):
	name = clean_text(name)
	if not name:
		frappe.throw(_("Account is required."))
	if not frappe.db.exists("DocType", "Account"):
		frappe.throw(_("Account is not available."))
	row = frappe.db.get_value(
		"Account",
		name,
		["name", "company", "account_currency", "is_group", "account_type"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Account {0} does not exist.").format(name))
	if row.is_group:
		frappe.throw(_("{0} is a group account.").format(row.name))
	if row.company != company:
		frappe.throw(_("{0} belongs to {1}, not {2}.").format(row.name, row.company, company))
	if not row.account_currency:
		frappe.throw(_("{0} has no currency.").format(row.name))
	return row


def exchange_rate(from_currency, to_currency, posting_date, chosen=None):
	"""Use a rate the user entered, otherwise Currency Exchange for that date.

	The latest rate on or before the posting date counts. The inverse pair is
	used when only that direction is stored.
	"""
	from_currency = clean_text(from_currency)
	to_currency = clean_text(to_currency)
	if not from_currency or not to_currency:
		frappe.throw(_("Exchange rate needs both currencies."))
	if from_currency == to_currency:
		return 1
	chosen_rate = _positive(chosen)
	if chosen_rate:
		return chosen_rate
	found = _stored_rate(from_currency, to_currency, posting_date)
	if found:
		return found
	inverse = _stored_rate(to_currency, from_currency, posting_date)
	if inverse:
		quant = Decimal(1).scaleb(-9)
		return float((Decimal(1) / Decimal(str(inverse))).quantize(quant, rounding=ROUND_HALF_UP))
	frappe.throw(
		_("No exchange rate from {0} to {1} on {2}.").format(from_currency, to_currency, posting_date)
	)


def _payment_args(doc, bank_name, defaults, advance_currency, advance_rate):
	paid = doc.paid_amount
	if paid in (None, "", 0):
		paid = None
	return {
		"party_type": doc.party_type,
		"party": doc.party,
		"company_currency": doc.company_currency,
		"payment_currency": doc.payment_currency,
		"payment_exchange_rate": doc.payment_exchange_rate,
		"paid_amount": paid,
		"bank_account": bank_name,
		"advance_account": clean_text(doc.advance_account),
		"advance_account_currency": advance_currency,
		"advance_exchange_rate": advance_rate,
		"gain_loss_account": defaults.get("exchange_gain_loss_account"),
		"cost_center": defaults.get("cost_center"),
	}


def _advance_rate(doc, company, party_type):
	account_name = clean_text(doc.advance_account)
	if not account_name:
		doc.advance_amount = 0
		return "", None
	account = party_account(account_name, company, party_type)
	doc.advance_currency = account.account_currency
	if account.account_currency == doc.company_currency:
		doc.advance_exchange_rate = 1
	elif account.account_currency == doc.payment_currency:
		doc.advance_exchange_rate = doc.payment_exchange_rate
	else:
		doc.advance_exchange_rate = exchange_rate(
			account.account_currency,
			doc.company_currency,
			doc.posting_date,
			doc.advance_exchange_rate,
		)
	return account.account_currency, doc.advance_exchange_rate


def _source_from_row(doc, row, defaults):
	reference_name = clean_text(row.get("reference_name"))
	reference_doctype = clean_text(row.get("reference_doctype"))
	allocated = row.get("allocated_amount")
	if not reference_name and not reference_doctype and not allocated:
		return None
	expected = _INVOICE_FIELDS[doc.party_type][0]
	if reference_doctype and reference_doctype != expected:
		return {
			"account": clean_text(row.get("account")),
			"account_currency": clean_text(row.get("account_currency")),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"invoice_currency": clean_text(row.get("invoice_currency")),
			"outstanding_amount": row.get("outstanding_amount"),
			"allocated_amount": allocated,
			"booked_rate": row.get("booked_rate"),
			"payment_rate": row.get("payment_rate"),
		}
	invoice = _load_invoice(expected, reference_name, doc.company, doc.party)
	account_name = invoice["account"]
	chosen = clean_text(row.get("account"))
	if chosen and chosen != account_name:
		frappe.throw(_("{0} {1} is on {2}, not {3}.").format(expected, reference_name, account_name, chosen))
	account = party_account(account_name, doc.company, doc.party_type)
	booked_rate, row_rate = _invoice_rates(
		account.account_currency,
		defaults.default_currency,
		invoice["conversion_rate"],
		row.get("payment_rate"),
		doc.posting_date,
	)
	return {
		"account": account.name,
		"account_currency": account.account_currency,
		"reference_doctype": expected,
		"reference_name": invoice["name"],
		"invoice_currency": invoice["currency"],
		"outstanding_amount": invoice["outstanding_amount"],
		"allocated_amount": allocated,
		"booked_rate": booked_rate,
		"payment_rate": row_rate,
	}


def _invoice_rates(account_currency, company_currency, conversion_rate, payment_rate, posting_date):
	if account_currency == company_currency:
		return 1, 1
	booked = conversion_rate or 0
	row_rate = payment_rate if _positive(payment_rate) else None
	if not row_rate:
		row_rate = exchange_rate(account_currency, company_currency, posting_date)
	return booked, row_rate


def _load_invoice(doctype, name, company, party):
	name = clean_text(name)
	if not name:
		frappe.throw(_("Each allocated row needs an invoice."))
	party_field, account_field = next(
		(fields[1], fields[2]) for fields in _INVOICE_FIELDS.values() if fields[0] == doctype
	)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} does not exist.").format(doctype, name))
	row = frappe.db.get_value(
		doctype,
		name,
		[
			"name",
			"company",
			"docstatus",
			"currency",
			"conversion_rate",
			"outstanding_amount",
			party_field,
			account_field,
		],
		as_dict=True,
	)
	if row.company != company:
		frappe.throw(_("{0} {1} belongs to {2}, not {3}.").format(doctype, name, row.company, company))
	if int(row.docstatus or 0) != 1:
		frappe.throw(_("{0} {1} is not submitted.").format(doctype, name))
	if clean_text(row.get(party_field)) != party:
		frappe.throw(_("{0} {1} is not for {2}.").format(doctype, name, party))
	if not row.get(account_field):
		frappe.throw(_("{0} {1} has no account.").format(doctype, name))
	if not row.currency:
		frappe.throw(_("{0} {1} has no currency.").format(doctype, name))
	return {
		"name": row.name,
		"currency": row.currency,
		"conversion_rate": row.conversion_rate,
		"outstanding_amount": row.outstanding_amount,
		"account": row.get(account_field),
	}


def _apply(doc, prepared):
	doc.payment_type = prepared["payment_type"]
	doc.paid_amount = prepared["paid_amount"]
	doc.allocated_amount = prepared["allocated_amount"]
	doc.unallocated_amount = prepared["unallocated_amount"]
	doc.base_paid_amount = prepared["base_paid_amount"]
	doc.exchange_gain_loss = prepared["exchange_gain_loss"]
	doc.multi_currency = prepared["multi_currency"]
	found = {(row["reference_doctype"], row["reference_name"]): row for row in prepared["allocations"]}
	expected = _INVOICE_FIELDS[doc.party_type][0]
	for row in doc.get("allocations") or []:
		key = (clean_text(row.get("reference_doctype")) or expected, clean_text(row.get("reference_name")))
		computed = found.get(key)
		if not computed:
			row.payment_amount = 0
			row.payment_currency = doc.payment_currency
			continue
		row.account = computed["account"]
		row.account_currency = computed["account_currency"]
		row.reference_doctype = computed["reference_doctype"]
		row.reference_name = computed["reference_name"]
		row.invoice_currency = computed["invoice_currency"]
		row.outstanding_amount = computed["outstanding_amount"]
		row.allocated_amount = computed["allocated_amount"]
		row.booked_rate = computed["booked_rate"]
		row.payment_rate = computed["payment_rate"]
		row.payment_currency = doc.payment_currency
		row.payment_amount = computed["payment_amount"]
	advance = prepared["advance"]
	if advance:
		doc.advance_account = advance["account"]
		doc.advance_currency = advance["account_currency"]
		doc.advance_exchange_rate = advance["exchange_rate"]
		doc.advance_amount = advance["amount"]
	else:
		doc.advance_amount = 0
	doc.flags.hero_payment = prepared


def _summary(doc, prepared):
	summary = {
		"payment_type": doc.payment_type,
		"payment_currency": doc.payment_currency,
		"company_currency": doc.company_currency,
		"payment_exchange_rate": doc.payment_exchange_rate,
		"paid_amount": doc.paid_amount,
		"allocated_amount": doc.allocated_amount,
		"unallocated_amount": doc.unallocated_amount,
		"base_paid_amount": doc.base_paid_amount,
		"exchange_gain_loss": doc.exchange_gain_loss,
		"multi_currency": doc.multi_currency,
		"advance_currency": doc.advance_currency,
		"advance_exchange_rate": doc.advance_exchange_rate,
		"advance_amount": doc.advance_amount,
		"allocations": [
			{
				"account": row.account,
				"account_currency": row.account_currency,
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"invoice_currency": row.invoice_currency,
				"outstanding_amount": row.outstanding_amount,
				"allocated_amount": row.allocated_amount,
				"booked_rate": row.booked_rate,
				"payment_rate": row.payment_rate,
				"payment_currency": row.payment_currency,
				"payment_amount": row.payment_amount,
			}
			for row in doc.get("allocations") or []
		],
	}
	summary["exchange_gain_loss"] = prepared["exchange_gain_loss"]
	return summary


def _journal_payload(doc, prepared):
	accounts = []
	for row in prepared["accounts"]:
		entry = {
			"account": row["account"],
			"exchange_rate": row["exchange_rate"],
			"debit_in_account_currency": row["debit_in_account_currency"],
			"credit_in_account_currency": row["credit_in_account_currency"],
			"debit": row["debit"],
			"credit": row["credit"],
		}
		if row.get("party"):
			entry["party_type"] = row["party_type"]
			entry["party"] = row["party"]
		if row.get("reference_name"):
			entry["reference_type"] = row["reference_type"]
			entry["reference_name"] = row["reference_name"]
		if row.get("is_advance") == "Yes":
			entry["is_advance"] = "Yes"
		if row.get("cost_center"):
			entry["cost_center"] = row["cost_center"]
		accounts.append(entry)
	return {
		"doctype": "Journal Entry",
		"voucher_type": "Bank Entry",
		"company": doc.company,
		"posting_date": doc.posting_date,
		"cheque_no": clean_text(doc.reference_no),
		"cheque_date": doc.reference_date,
		"user_remark": _("Frappe Hero Multi Currency Payment: {0}").format(doc.name),
		"multi_currency": prepared["multi_currency"],
		"accounts": accounts,
	}


def _stored_rate(from_currency, to_currency, posting_date):
	if not frappe.db.exists("DocType", "Currency Exchange"):
		return None
	exact = frappe.db.get_value(
		"Currency Exchange",
		{"from_currency": from_currency, "to_currency": to_currency, "date": posting_date},
		"exchange_rate",
	)
	if exact:
		return float(exact)
	rows = frappe.db.get_all(
		"Currency Exchange",
		filters={
			"from_currency": from_currency,
			"to_currency": to_currency,
			"date": ["<=", posting_date],
		},
		fields=["exchange_rate"],
		order_by="date desc",
		limit=1,
	)
	if rows and rows[0].exchange_rate:
		return float(rows[0].exchange_rate)
	return None


def _positive(value):
	if value is None or value is False or value == "":
		return None
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if number > 0 else None


def _require_read():
	if not frappe.has_permission("Hero Multi Currency Payment", ptype="read"):
		frappe.throw(_("Not permitted to read multi-currency payments."), frappe.PermissionError)
