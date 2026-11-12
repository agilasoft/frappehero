# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Allocate one Payment Entry across several party accounts and currencies."""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _

from frappehero.finance_desk.multi_currency_payment_logic import (
	MultiCurrencyPaymentError,
	header_account,
	paid_and_received,
	party_side_amount,
	prepare_payment,
	spans_accounts,
)
from frappehero.flags import clean_text, parse_payload

_INVOICE_FIELDS = {
	"Customer": ("Sales Invoice", "customer", "debit_to"),
	"Supplier": ("Purchase Invoice", "supplier", "credit_to"),
}


def apply_to_payment(doc, method=None):
	"""Fill accounts and bank amounts when a Payment Entry uses more than one account.

	A payment whose references stay on the header party account is left to
	ERPNext. Cancel keeps the amounts that were submitted. A submitted payment
	is allocated again only while it is being submitted, because Frappe marks
	it submitted before ``before_validate``.
	"""
	if not _should_allocate(doc):
		return
	_fill_missing_accounts(doc)
	_fill_account_currencies(doc)
	if not _needs_custom_allocation(doc):
		doc.hero_multi_account = 0
		return
	prepare_payment_entry(doc)


def prepare_payment_entry(doc):
	"""Recompute a multi-account Payment Entry and keep the GL rows on flags."""
	if doc.get("payment_type") not in ("Pay", "Receive"):
		frappe.throw(_("Multiple accounts are available on Pay and Receive."))
	if doc.get("party_type") not in _INVOICE_FIELDS:
		frappe.throw(_("Multiple accounts are available for customers and suppliers."))
	_fill_missing_accounts(doc)
	_fill_account_currencies(doc)
	if doc.get("taxes") or _other_deductions(doc):
		frappe.throw(_("Deductions and taxes stay on a payment that uses one account."))
	prepared = _prepare(doc)
	_write(doc, prepared)
	return prepared


def uses_multiple_accounts(doc) -> bool:
	if doc.get("payment_type") not in ("Pay", "Receive"):
		return False
	return spans_accounts(party_account_on(doc), _reference_accounts(doc))


def party_account_on(doc):
	if doc.get("payment_type") == "Receive":
		return clean_text(doc.get("paid_from"))
	if doc.get("payment_type") == "Pay":
		return clean_text(doc.get("paid_to"))
	return ""


def bank_account_on(doc):
	if doc.get("payment_type") == "Receive":
		return clean_text(doc.get("paid_to"))
	if doc.get("payment_type") == "Pay":
		return clean_text(doc.get("paid_from"))
	return ""


@frappe.whitelist()
def outstanding_invoices(
	company=None,
	party_type=None,
	party=None,
	posting_date=None,
	payment_type=None,
	bank_account=None,
	party_account=None,
	payment_exchange_rate=None,
	paid_amount=None,
):
	"""Return every open invoice for the party, each with its own account."""
	_require_payment_read()
	party_type = clean_text(party_type)
	company = clean_text(company)
	party = clean_text(party)
	bank_name = clean_text(bank_account)
	if party_type not in _INVOICE_FIELDS:
		frappe.throw(_("Party type must be Customer or Supplier."))
	if payment_type not in ("Pay", "Receive"):
		frappe.throw(_("Payment Type must be Pay or Receive."))
	if not company or not party or not posting_date or not bank_name:
		frappe.throw(_("Company, party, posting date, and bank account are required."))
	defaults = company_defaults(company)
	bank = bank_ledger(bank_name, company)
	rate = exchange_rate(
		bank.account_currency, defaults.default_currency, posting_date, payment_exchange_rate
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
	sources = []
	for invoice in invoices:
		account = party_ledger(invoice.get(account_field), company, party_type)
		booked_rate, row_rate = _invoice_rates(
			account.account_currency,
			defaults.default_currency,
			invoice.conversion_rate,
			None,
			posting_date,
		)
		sources.append(
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
			}
		)
	chosen_party = header_account(party_account, [row["account"] for row in sources])
	return _as_payment(
		payment_type,
		_result(
			party_type,
			party,
			company,
			payment_type,
			bank,
			defaults,
			posting_date,
			chosen_party,
			sources,
			paid_amount,
			rate,
		),
	)


@frappe.whitelist()
def preview(payment=None):
	"""Recompute a Payment Entry that allocates more than one account."""
	_require_payment_read()
	parsed = parse_payload(payment, {})
	if not isinstance(parsed, dict):
		frappe.throw(_("The payment could not be read."))
	parsed["doctype"] = "Payment Entry"
	for row in parsed.get("references") or []:
		if isinstance(row, dict):
			row.setdefault("doctype", "Payment Entry Reference")
			row.setdefault("parentfield", "references")
			row.setdefault("parenttype", "Payment Entry")
	doc = frappe.get_doc(parsed)
	apply_to_payment(doc)
	return _summary(doc)


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


def bank_ledger(name, company):
	row = ledger(name, company)
	if row.account_type not in ("Bank", "Cash"):
		frappe.throw(_("{0} is not a bank or cash account.").format(row.name))
	return row


def party_ledger(name, company, party_type):
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


def _prepare(doc):
	defaults = company_defaults(doc.company)
	bank = bank_ledger(bank_account_on(doc), doc.company)
	bank_rate = _bank_rate(doc, bank.account_currency, defaults.default_currency)
	sources = []
	for row in doc.get("references") or []:
		source = _source_from_row(doc, row, defaults)
		if source is not None:
			sources.append(source)
	if not sources:
		frappe.throw(_("Allocate at least one invoice."))
	chosen = header_account(party_account_on(doc), [row["account"] for row in sources])
	bank_paid = doc.get("paid_amount") if doc.payment_type == "Pay" else doc.get("received_amount")
	advance_account = clean_text(getattr(doc.flags, "hero_repair_advance_account", ""))
	return _result(
		doc.party_type,
		doc.party,
		doc.company,
		doc.payment_type,
		bank,
		defaults,
		doc.posting_date,
		chosen,
		sources,
		bank_paid,
		bank_rate,
		doc.get("cost_center"),
		advance_account,
	)


def _result(
	party_type,
	party,
	company,
	payment_type,
	bank,
	defaults,
	posting_date,
	party_account_name,
	sources,
	bank_paid,
	bank_rate,
	cost_center=None,
	advance_account_name=None,
):
	account = party_ledger(party_account_name, company, party_type)
	party_rate = 1
	if account.account_currency != defaults.default_currency:
		party_rate = exchange_rate(account.account_currency, defaults.default_currency, posting_date)
	advance_ledger = account
	advance_rate = party_rate
	advance_name = clean_text(advance_account_name)
	if advance_name and advance_name != account.name:
		advance_ledger = party_ledger(advance_name, company, party_type)
		advance_rate = 1
		if advance_ledger.account_currency != defaults.default_currency:
			advance_rate = exchange_rate(
				advance_ledger.account_currency, defaults.default_currency, posting_date
			)
	paid = None if bank_paid in (None, "", 0) else bank_paid
	try:
		prepared = prepare_payment(
			{
				"party_type": party_type,
				"party": party,
				"company_currency": defaults.default_currency,
				"payment_currency": bank.account_currency,
				"payment_exchange_rate": bank_rate,
				"paid_amount": paid,
				"bank_account": bank.name,
				"advance_account": advance_ledger.name,
				"advance_account_currency": advance_ledger.account_currency,
				"advance_exchange_rate": advance_rate,
				"gain_loss_account": defaults.get("exchange_gain_loss_account"),
				"cost_center": cost_center or defaults.get("cost_center"),
			},
			sources,
		)
	except MultiCurrencyPaymentError as exc:
		frappe.throw(str(exc))
	portion = party_side_amount(account.name, prepared["allocations"], prepared["advance"])
	if portion <= 0:
		frappe.throw(_("Choose a party account that one of the invoices uses."))
	paid_amount, received_amount = paid_and_received(
		payment_type,
		prepared["paid_amount"],
		bank.account_currency,
		account.account_currency,
		portion,
	)
	prepared.update(
		{
			"party_account": account.name,
			"party_account_currency": account.account_currency,
			"party_exchange_rate": party_rate,
			"bank_account": bank.name,
			"bank_currency": bank.account_currency,
			"bank_exchange_rate": 1 if bank.account_currency == defaults.default_currency else bank_rate,
			"paid_amount": paid_amount,
			"received_amount": received_amount,
			"multi_account": _custom_allocation(account.name, prepared),
		}
	)
	return prepared


def _write(doc, prepared):
	if doc.payment_type == "Pay":
		doc.paid_from = prepared["bank_account"]
		doc.paid_to = prepared["party_account"]
		doc.paid_from_account_currency = prepared["bank_currency"]
		doc.paid_to_account_currency = prepared["party_account_currency"]
		doc.source_exchange_rate = prepared["bank_exchange_rate"]
		doc.target_exchange_rate = prepared["party_exchange_rate"]
	else:
		doc.paid_to = prepared["bank_account"]
		doc.paid_from = prepared["party_account"]
		doc.paid_to_account_currency = prepared["bank_currency"]
		doc.paid_from_account_currency = prepared["party_account_currency"]
		doc.target_exchange_rate = prepared["bank_exchange_rate"]
		doc.source_exchange_rate = prepared["party_exchange_rate"]
	doc.paid_amount = prepared["paid_amount"]
	doc.received_amount = prepared["received_amount"]
	doc.base_paid_amount = prepared["base_paid_amount"]
	doc.base_received_amount = prepared["base_paid_amount"]
	doc.paid_amount_after_tax = prepared["paid_amount"]
	doc.received_amount_after_tax = prepared["received_amount"]
	doc.base_paid_amount_after_tax = prepared["base_paid_amount"]
	doc.base_received_amount_after_tax = prepared["base_paid_amount"]
	doc.difference_amount = 0
	header = prepared["party_account"]
	doc.total_allocated_amount = sum(
		row["allocated_amount"] for row in prepared["allocations"] if row["account"] == header
	)
	doc.base_total_allocated_amount = sum(
		row["booked_base"] for row in prepared["allocations"] if row["account"] == header
	)
	advance = prepared.get("advance") or {}
	doc.unallocated_amount = advance.get("amount") or 0 if advance.get("account") == header else 0
	doc.hero_multi_account = prepared["multi_account"]
	doc.deductions = [row for row in doc.get("deductions") or [] if not row.get("is_exchange_gain_loss")]
	found = {(row["reference_doctype"], row["reference_name"]): row for row in prepared["allocations"]}
	for row in doc.get("references") or []:
		computed = found.get(
			(clean_text(row.get("reference_doctype")), clean_text(row.get("reference_name")))
		)
		if not computed:
			continue
		row.hero_account = computed["account"]
		row.hero_account_currency = computed["account_currency"]
		row.reference_doctype = computed["reference_doctype"]
		row.reference_name = computed["reference_name"]
		row.hero_invoice_currency = computed["invoice_currency"]
		row.outstanding_amount = computed["outstanding_amount"]
		row.hero_allocated_invoice_amount = computed["allocated_invoice_amount"]
		row.hero_allocated_account_amount = computed["allocated_amount"]
		row.allocated_amount = computed["allocated_amount"]
		row.hero_booked_rate = computed["invoice_booked_rate"]
		row.hero_payment_rate = computed["payment_rate"]
		row.hero_payment_currency = prepared["bank_currency"]
		row.hero_bank_amount = computed["payment_amount"]
		row.exchange_rate = computed["booked_rate"]
		row.exchange_gain_loss = 0
	doc.flags.hero_payment = prepared


def _summary(doc):
	prepared = getattr(doc.flags, "hero_payment", None) or {}
	return {
		"payment_type": doc.payment_type,
		"paid_from": doc.paid_from,
		"paid_to": doc.paid_to,
		"paid_from_account_currency": doc.get("paid_from_account_currency"),
		"paid_to_account_currency": doc.get("paid_to_account_currency"),
		"paid_amount": doc.paid_amount,
		"received_amount": doc.received_amount,
		"source_exchange_rate": doc.source_exchange_rate,
		"target_exchange_rate": doc.target_exchange_rate,
		"base_paid_amount": doc.base_paid_amount,
		"base_received_amount": doc.base_received_amount,
		"difference_amount": doc.difference_amount,
		"unallocated_amount": doc.unallocated_amount,
		"hero_multi_account": doc.hero_multi_account,
		"exchange_gain_loss": prepared.get("exchange_gain_loss", 0),
		"references": [
			{
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"hero_account": row.hero_account,
				"hero_account_currency": row.hero_account_currency,
				"hero_invoice_currency": row.hero_invoice_currency,
				"outstanding_amount": row.outstanding_amount,
				"hero_allocated_invoice_amount": row.hero_allocated_invoice_amount,
				"hero_allocated_account_amount": row.hero_allocated_account_amount,
				"allocated_amount": row.allocated_amount,
				"hero_booked_rate": row.hero_booked_rate,
				"hero_payment_rate": row.hero_payment_rate,
				"hero_payment_currency": row.hero_payment_currency,
				"hero_bank_amount": row.hero_bank_amount,
			}
			for row in doc.get("references") or []
		],
	}


def _fill_missing_accounts(doc):
	if doc.get("party_type") not in _INVOICE_FIELDS:
		return
	expected = _INVOICE_FIELDS[doc.party_type][0]
	for row in doc.get("references") or []:
		if clean_text(row.get("hero_account")) or not clean_text(row.get("reference_name")):
			continue
		if clean_text(row.get("reference_doctype")) not in ("", expected):
			continue
		if not frappe.db.exists(expected, row.reference_name):
			continue
		account_field = _INVOICE_FIELDS[doc.party_type][2]
		row.hero_account = frappe.db.get_value(expected, row.reference_name, account_field)


def _fill_account_currencies(doc):
	for row in doc.get("references") or []:
		account = clean_text(row.get("hero_account"))
		if not account or clean_text(row.get("hero_account_currency")):
			continue
		if frappe.db.exists("Account", account):
			row.hero_account_currency = frappe.db.get_value("Account", account, "account_currency")


def _needs_custom_allocation(doc) -> bool:
	if uses_multiple_accounts(doc):
		return True
	for row in doc.get("references") or []:
		invoice_currency = clean_text(row.get("hero_invoice_currency"))
		account_currency = clean_text(row.get("hero_account_currency"))
		if not invoice_currency or not account_currency or invoice_currency == account_currency:
			continue
		if (
			row.get("reference_name")
			or row.get("hero_allocated_invoice_amount")
			or row.get("allocated_amount")
		):
			return True
	return False


def _custom_allocation(party_account, prepared) -> int:
	rows = prepared["allocations"]
	if spans_accounts(party_account, [row["account"] for row in rows]):
		return 1
	if any(row["invoice_currency"] != row["account_currency"] for row in rows):
		return 1
	return 0


def _source_from_row(doc, row, defaults):
	reference_name = clean_text(row.get("reference_name"))
	reference_doctype = clean_text(row.get("reference_doctype"))
	allocated = row.get("allocated_amount")
	if not reference_name and not reference_doctype and not allocated:
		return None
	expected = _INVOICE_FIELDS[doc.party_type][0]
	if reference_doctype and reference_doctype != expected:
		return {
			"account": clean_text(row.get("hero_account")),
			"account_currency": clean_text(row.get("hero_account_currency")),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"invoice_currency": clean_text(row.get("hero_invoice_currency")),
			"outstanding_amount": row.get("outstanding_amount"),
			"allocated_amount": allocated,
			"booked_rate": row.get("hero_booked_rate"),
			"payment_rate": row.get("hero_payment_rate"),
		}
	invoice = _load_invoice(expected, reference_name, doc.company, doc.party)
	chosen = clean_text(row.get("hero_account"))
	if chosen and chosen != invoice["account"]:
		frappe.throw(
			_("{0} {1} is on {2}, not {3}.").format(expected, reference_name, invoice["account"], chosen)
		)
	account = party_ledger(invoice["account"], doc.company, doc.party_type)
	booked_rate, row_rate = _invoice_rates(
		invoice["currency"],
		defaults.default_currency,
		invoice["conversion_rate"],
		row.get("hero_payment_rate"),
		doc.posting_date,
	)
	invoice_allocated = row.get("hero_allocated_invoice_amount")
	if invoice_allocated in (None, ""):
		invoice_allocated = allocated
	account_exchange_rate = None
	if account.account_currency not in (invoice["currency"], defaults.default_currency):
		account_exchange_rate = exchange_rate(
			account.account_currency, defaults.default_currency, doc.posting_date
		)
	return _keep_saved_allocation(
		doc,
		{
			"account": account.name,
			"account_currency": account.account_currency,
			"reference_doctype": expected,
			"reference_name": invoice["name"],
			"invoice_currency": invoice["currency"],
			"outstanding_amount": invoice["outstanding_amount"],
			"allocated_invoice_amount": invoice_allocated,
			"allocated_amount": allocated,
			"booked_rate": booked_rate,
			"payment_rate": row_rate,
			"account_exchange_rate": account_exchange_rate,
		},
	)


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


def _bank_rate(doc, bank_currency, company_currency):
	if bank_currency == company_currency:
		return 1
	chosen = doc.get("source_exchange_rate") if doc.payment_type == "Pay" else doc.get("target_exchange_rate")
	return exchange_rate(bank_currency, company_currency, doc.posting_date, chosen)


def _reference_accounts(doc):
	names = []
	for row in doc.get("references") or []:
		if not row.get("allocated_amount") and not row.get("reference_name"):
			continue
		names.append(clean_text(row.get("hero_account")))
	return names


def _other_deductions(doc):
	return any(not row.get("is_exchange_gain_loss") for row in doc.get("deductions") or [])


def _should_allocate(doc) -> bool:
	try:
		status = int(getattr(doc, "docstatus", 0) or 0)
	except (TypeError, ValueError):
		return False
	if status == 2:
		return False
	if status == 1 and clean_text(getattr(doc, "_action", None)) != "submit":
		return False
	if doc.get("payment_type") not in ("Pay", "Receive"):
		return False
	return _fields_ready()


def _keep_saved_allocation(doc, source):
	"""Let a submitted payment rebuild after its invoices already show this allocation.

	Submit still checks the live outstanding. A later repost sees that outstanding
	already reduced by this payment, so the saved allocation is the ceiling.
	"""
	try:
		status = int(getattr(doc, "docstatus", 0) or 0)
	except (TypeError, ValueError):
		return source
	if status == 0 or clean_text(getattr(doc, "_action", None)) == "submit":
		return source
	raw_allocated = source.get("allocated_invoice_amount")
	if raw_allocated in (None, ""):
		raw_allocated = source.get("allocated_amount")
	try:
		allocated = float(raw_allocated or 0)
		outstanding = float(source.get("outstanding_amount") or 0)
	except (TypeError, ValueError):
		return source
	if outstanding < allocated:
		source["outstanding_amount"] = raw_allocated
	return source


def _as_payment(payment_type, prepared):
	if payment_type == "Pay":
		paid_from = prepared["bank_account"]
		paid_to = prepared["party_account"]
		paid_from_currency = prepared["bank_currency"]
		paid_to_currency = prepared["party_account_currency"]
		source_rate = prepared["bank_exchange_rate"]
		target_rate = prepared["party_exchange_rate"]
	else:
		paid_from = prepared["party_account"]
		paid_to = prepared["bank_account"]
		paid_from_currency = prepared["party_account_currency"]
		paid_to_currency = prepared["bank_currency"]
		source_rate = prepared["party_exchange_rate"]
		target_rate = prepared["bank_exchange_rate"]
	advance = prepared.get("advance") or {}
	bank_currency = prepared["bank_currency"]
	return {
		"paid_from": paid_from,
		"paid_to": paid_to,
		"paid_from_account_currency": paid_from_currency,
		"paid_to_account_currency": paid_to_currency,
		"source_exchange_rate": source_rate,
		"target_exchange_rate": target_rate,
		"paid_amount": prepared["paid_amount"],
		"received_amount": prepared["received_amount"],
		"base_paid_amount": prepared["base_paid_amount"],
		"base_received_amount": prepared["base_paid_amount"],
		"difference_amount": 0,
		"unallocated_amount": advance.get("amount") or 0,
		"hero_multi_account": prepared["multi_account"],
		"exchange_gain_loss": prepared["exchange_gain_loss"],
		"references": [
			{
				"reference_doctype": row["reference_doctype"],
				"reference_name": row["reference_name"],
				"hero_account": row["account"],
				"hero_account_currency": row["account_currency"],
				"hero_invoice_currency": row["invoice_currency"],
				"outstanding_amount": row["outstanding_amount"],
				"hero_allocated_invoice_amount": row["allocated_invoice_amount"],
				"hero_allocated_account_amount": row["allocated_amount"],
				"allocated_amount": row["allocated_amount"],
				"hero_booked_rate": row["invoice_booked_rate"],
				"hero_payment_rate": row["payment_rate"],
				"hero_payment_currency": bank_currency,
				"hero_bank_amount": row["payment_amount"],
				"exchange_rate": row["booked_rate"],
				"exchange_gain_loss": 0,
			}
			for row in prepared["allocations"]
		],
	}


def _fields_ready():
	if not frappe.db.exists("DocType", "Payment Entry Reference"):
		return False
	reference_meta = frappe.get_meta("Payment Entry Reference")
	payment_meta = frappe.get_meta("Payment Entry")
	return (
		reference_meta.has_field("hero_account")
		and reference_meta.has_field("hero_allocated_invoice_amount")
		and payment_meta.has_field("hero_multi_account")
	)


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


def _require_payment_read():
	if not frappe.has_permission("Payment Entry", ptype="read"):
		frappe.throw(_("Not permitted to read payments."), frappe.PermissionError)
