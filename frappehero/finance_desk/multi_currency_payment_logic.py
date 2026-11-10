# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""One bank amount allocated across accounts and invoice currencies.

Pure functions. The desk document calls these, and the tests run without a site.
Journal Entry posts an invoice row at the invoice conversion rate, so the party
line uses the booked rate and the rate difference is its own line.
"""

from decimal import ROUND_HALF_UP, Decimal

from frappehero.flags import clean_text

CUSTOMER = "Customer"
SUPPLIER = "Supplier"
SALES_INVOICE = "Sales Invoice"
PURCHASE_INVOICE = "Purchase Invoice"
_PARTY_REFERENCE = {
	CUSTOMER: SALES_INVOICE,
	SUPPLIER: PURCHASE_INVOICE,
}


class MultiCurrencyPaymentError(ValueError):
	"""A multi-currency payment cannot be posted as entered."""


def payment_type_for(party_type) -> str:
	"""Customer receipts credit the receivable. Supplier payments debit the payable."""
	party_type = clean_text(party_type)
	if party_type == CUSTOMER:
		return "Receive"
	if party_type == SUPPLIER:
		return "Pay"
	raise MultiCurrencyPaymentError("Party type must be Customer or Supplier.")


def prepare_payment(payment, allocations, precision=2) -> dict:
	"""Build the bank, party, advance, and gain/loss rows for one payment.

	``paid_amount`` may be omitted. The bank amount is then the allocated total.
	A larger paid amount is an advance. A smaller one is rejected. Rates are
	company currency for one unit of the other currency.
	"""
	precision = int(precision)
	party_type = clean_text((payment or {}).get("party_type"))
	payment_type = payment_type_for(party_type)
	party = _required(payment, "party", "Party is required.")
	bank_account = _required(payment, "bank_account", "Bank account is required.")
	company_currency = _required(payment, "company_currency", "Company currency is required.")
	payment_currency = _required(payment, "payment_currency", "Payment currency is required.")
	if payment_currency == company_currency:
		payment_rate = Decimal(1)
	else:
		payment_rate = _rate(payment.get("payment_exchange_rate"), "the bank currency")
	gain_loss_account = clean_text((payment or {}).get("gain_loss_account"))
	cost_center = clean_text((payment or {}).get("cost_center"))

	active = []
	seen = set()
	for source in allocations or []:
		row = _allocation_row(
			source,
			party_type,
			payment_currency,
			company_currency,
			payment_rate,
			precision,
		)
		if row is None:
			continue
		key = (row["reference_doctype"], row["reference_name"])
		if key in seen:
			raise MultiCurrencyPaymentError(
				f"{row['reference_doctype']} {row['reference_name']} is already on this payment."
			)
		seen.add(key)
		active.append(row)
	if not active:
		raise MultiCurrencyPaymentError("Allocate at least one invoice.")

	allocated_amount = _quantize(sum((row["payment_amount_dec"] for row in active), Decimal(0)), precision)
	paid_amount = _paid_amount(payment, allocated_amount, payment_currency, precision)
	unallocated = _quantize(paid_amount - allocated_amount, precision)
	if unallocated < 0:
		raise MultiCurrencyPaymentError(
			f"Paid amount {_show(paid_amount)} {payment_currency} is less than the allocated total "
			f"{_show(allocated_amount)} {payment_currency}."
		)

	advance = _advance(payment, unallocated, payment_currency, payment_rate, company_currency, precision)
	party_base = sum((row["booked_base_dec"] for row in active), Decimal(0))
	advance_base = advance["base_dec"] if advance else Decimal(0)
	bank_base = _quantize(paid_amount * payment_rate, precision)
	gap = _quantize(bank_base - party_base - advance_base, precision)

	party_side = "debit" if payment_type == "Pay" else "credit"
	bank_side = "credit" if payment_type == "Pay" else "debit"
	accounts = [_party_line(row, party_type, party, party_side) for row in active]
	if advance:
		accounts.append(_advance_line(advance, party_type, party, party_side))
	gain_loss = _gain_loss_line(
		gap, payment_type, gain_loss_account, cost_center, company_currency, precision
	)
	if gain_loss:
		accounts.append(gain_loss)
	bank_line = _money_line(
		bank_account,
		paid_amount,
		payment_rate,
		bank_base,
		bank_side,
	)
	bank_line["account_currency"] = payment_currency
	accounts.append(bank_line)
	_require_balance(accounts, precision)

	if payment_type == "Pay":
		exchange_gain_loss = _quantize(-gap, precision)
	else:
		exchange_gain_loss = gap
	currencies = {payment_currency, company_currency}
	currencies.update(row["account_currency"] for row in active)
	if advance:
		currencies.add(advance["account_currency"])

	return {
		"payment_type": payment_type,
		"multi_currency": 0 if currencies == {company_currency} else 1,
		"paid_amount": _show(paid_amount),
		"allocated_amount": _show(allocated_amount),
		"unallocated_amount": _show(unallocated),
		"base_paid_amount": _show(bank_base),
		"exchange_gain_loss": _show(exchange_gain_loss),
		"allocations": [_public_row(row) for row in active],
		"advance": _public_advance(advance),
		"accounts": accounts,
	}


def _allocation_row(source, party_type, payment_currency, company_currency, payment_rate, precision):
	source = source or {}
	allocated = _amount(source.get("allocated_amount"), precision)
	reference_name = clean_text(source.get("reference_name"))
	reference_doctype = clean_text(source.get("reference_doctype"))
	if allocated == 0 and not reference_name and not reference_doctype:
		return None
	expected = _PARTY_REFERENCE[party_type]
	label = f"{reference_doctype or 'Invoice'} {reference_name}".strip()
	if not reference_doctype or not reference_name:
		raise MultiCurrencyPaymentError(f"Each allocated row needs an invoice. {label} does not have one.")
	if reference_doctype != expected:
		kind = "customer receipt" if party_type == CUSTOMER else "supplier payment"
		raise MultiCurrencyPaymentError(
			f"A {kind} allocates {expected}s. {reference_name} is a {reference_doctype}."
		)
	if allocated == 0:
		raise MultiCurrencyPaymentError(
			f"Enter the allocated amount for {reference_doctype} {reference_name}."
		)
	if allocated < 0:
		raise MultiCurrencyPaymentError(
			f"Allocated amount for {reference_doctype} {reference_name} cannot be negative."
		)
	outstanding = _amount(source.get("outstanding_amount"), precision)
	if allocated > outstanding:
		raise MultiCurrencyPaymentError(
			f"Allocated amount for {reference_doctype} {reference_name} cannot be greater than "
			f"outstanding {_show(outstanding)}."
		)
	account = clean_text(source.get("account"))
	if not account:
		raise MultiCurrencyPaymentError(
			f"Each allocated row needs an account. {reference_name} does not have one."
		)
	account_currency = clean_text(source.get("account_currency"))
	invoice_currency = clean_text(source.get("invoice_currency"))
	if not account_currency or not invoice_currency:
		raise MultiCurrencyPaymentError(
			f"{reference_doctype} {reference_name} needs an account currency and an invoice currency."
		)
	if account_currency != invoice_currency:
		raise MultiCurrencyPaymentError(
			f"{reference_doctype} {reference_name} is in {invoice_currency}, but {account} is in "
			f"{account_currency}. The account currency has to match the invoice currency."
		)
	if account_currency == company_currency:
		booked_rate = Decimal(1)
		row_rate = Decimal(1)
	else:
		booked_rate = _rate(source.get("booked_rate"), f"the booked rate on {reference_name}")
		row_rate = _rate(source.get("payment_rate"), f"the payment rate on {reference_name}")
	booked_base = _quantize(allocated * booked_rate, precision)
	payment_base = _quantize(allocated * row_rate, precision)
	if account_currency == payment_currency:
		bank_amount = allocated
	else:
		bank_amount = _quantize(payment_base / payment_rate, precision)
	return {
		"account": account,
		"account_currency": account_currency,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"invoice_currency": invoice_currency,
		"outstanding_amount": outstanding,
		"allocated_amount": allocated,
		"booked_rate": booked_rate,
		"payment_rate": row_rate,
		"booked_base_dec": booked_base,
		"payment_base_dec": payment_base,
		"payment_amount_dec": bank_amount,
	}


def _paid_amount(payment, allocated_amount, payment_currency, precision):
	raw = (payment or {}).get("paid_amount")
	if raw is None or raw is False or (isinstance(raw, str) and not raw.strip()):
		if allocated_amount <= 0:
			raise MultiCurrencyPaymentError(f"Enter the paid amount in {payment_currency}.")
		return allocated_amount
	paid = _amount(raw, precision)
	if paid <= 0:
		raise MultiCurrencyPaymentError(f"Enter the paid amount in {payment_currency}.")
	return paid


def _advance(payment, unallocated, payment_currency, payment_rate, company_currency, precision):
	if unallocated == 0:
		return None
	account = clean_text((payment or {}).get("advance_account"))
	if not account:
		raise MultiCurrencyPaymentError(
			f"Paid amount is {_show(unallocated)} {payment_currency} above the allocated total. "
			"Choose an advance account."
		)
	currency = clean_text((payment or {}).get("advance_account_currency"))
	if not currency:
		raise MultiCurrencyPaymentError("Advance account currency is required.")
	if currency == payment_currency:
		amount = unallocated
		rate = Decimal(1) if currency == company_currency else payment_rate
	elif currency == company_currency:
		amount = _quantize(unallocated * payment_rate, precision)
		rate = Decimal(1)
	else:
		rate = _rate((payment or {}).get("advance_exchange_rate"), "the advance account")
		amount = _quantize((unallocated * payment_rate) / rate, precision)
	if amount <= 0:
		raise MultiCurrencyPaymentError(f"The unallocated amount is too small to post on {account}.")
	base = _quantize(amount * rate, precision)
	return {
		"account": account,
		"account_currency": currency,
		"amount_dec": amount,
		"rate_dec": rate,
		"base_dec": base,
	}


def _gain_loss_line(gap, payment_type, account, cost_center, company_currency, precision):
	gap = _quantize(gap, precision)
	if gap == 0:
		return None
	if not account or not cost_center:
		raise MultiCurrencyPaymentError(
			"Set the exchange gain/loss account and cost center on the company before posting a rate difference."
		)
	if payment_type == "Pay":
		side = "debit" if gap > 0 else "credit"
	else:
		side = "credit" if gap > 0 else "debit"
	line = _money_line(account, abs(gap), Decimal(1), abs(gap), side)
	line["cost_center"] = cost_center
	line["account_currency"] = company_currency
	return line


def _party_line(row, party_type, party, side):
	line = _money_line(
		row["account"],
		row["allocated_amount"],
		row["booked_rate"],
		row["booked_base_dec"],
		side,
	)
	line.update(
		{
			"party_type": party_type,
			"party": party,
			"reference_type": row["reference_doctype"],
			"reference_name": row["reference_name"],
			"account_currency": row["account_currency"],
		}
	)
	return line


def _advance_line(advance, party_type, party, side):
	line = _money_line(
		advance["account"],
		advance["amount_dec"],
		advance["rate_dec"],
		advance["base_dec"],
		side,
	)
	line.update(
		{
			"party_type": party_type,
			"party": party,
			"is_advance": "Yes",
			"account_currency": advance["account_currency"],
		}
	)
	return line


def _money_line(account, amount, rate, base, side):
	amount = _show(amount)
	base = _show(base)
	rate = _show(rate)
	return {
		"account": account,
		"party_type": "",
		"party": "",
		"account_currency": "",
		"exchange_rate": rate,
		"debit_in_account_currency": amount if side == "debit" else 0.0,
		"credit_in_account_currency": amount if side == "credit" else 0.0,
		"debit": base if side == "debit" else 0.0,
		"credit": base if side == "credit" else 0.0,
		"reference_type": "",
		"reference_name": "",
		"is_advance": "No",
		"cost_center": "",
	}


def _public_row(row):
	return {
		"account": row["account"],
		"account_currency": row["account_currency"],
		"reference_doctype": row["reference_doctype"],
		"reference_name": row["reference_name"],
		"invoice_currency": row["invoice_currency"],
		"outstanding_amount": _show(row["outstanding_amount"]),
		"allocated_amount": _show(row["allocated_amount"]),
		"booked_rate": _show(row["booked_rate"]),
		"payment_rate": _show(row["payment_rate"]),
		"booked_base": _show(row["booked_base_dec"]),
		"payment_base": _show(row["payment_base_dec"]),
		"payment_amount": _show(row["payment_amount_dec"]),
	}


def _public_advance(advance):
	if not advance:
		return None
	return {
		"account": advance["account"],
		"account_currency": advance["account_currency"],
		"amount": _show(advance["amount_dec"]),
		"exchange_rate": _show(advance["rate_dec"]),
		"base": _show(advance["base_dec"]),
	}


def _require_balance(accounts, precision):
	debit = sum((_decimal(row["debit"]) for row in accounts), Decimal(0))
	credit = sum((_decimal(row["credit"]) for row in accounts), Decimal(0))
	if _quantize(debit - credit, precision) != 0:
		raise MultiCurrencyPaymentError("The journal does not balance.")


def _required(payment, key, message):
	value = clean_text((payment or {}).get(key))
	if not value:
		raise MultiCurrencyPaymentError(message)
	return value


def _rate(value, label):
	try:
		number = _decimal(value)
	except MultiCurrencyPaymentError:
		number = Decimal(0)
	if number <= 0:
		raise MultiCurrencyPaymentError(f"Exchange rate for {label} has to be greater than zero.")
	return number


def _amount(value, precision):
	return _quantize(_decimal(value), precision)


def _decimal(value):
	if isinstance(value, Decimal):
		return value
	if value is None or value is False or value == "":
		return Decimal(0)
	try:
		return Decimal(str(value).strip())
	except Exception:
		raise MultiCurrencyPaymentError("Enter amounts and rates as numbers.") from None


def _quantize(value, precision):
	quant = Decimal(1).scaleb(-precision)
	return _decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _show(value):
	number = _decimal(value)
	text = format(number, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return float(text) if text else 0.0


def spans_accounts(party_account, accounts) -> bool:
	"""True when the references are not all on the single party account."""
	names = {clean_text(account) for account in accounts or [] if clean_text(account)}
	if len(names) > 1:
		return True
	party_account = clean_text(party_account)
	return bool(names and party_account and names != {party_account})


def header_account(party_account, accounts):
	"""Keep the party account when one of the rows uses it, otherwise the first row."""
	party_account = clean_text(party_account)
	ordered = [clean_text(account) for account in accounts or [] if clean_text(account)]
	if party_account and party_account in ordered:
		return party_account
	return ordered[0] if ordered else party_account


def party_side_amount(account, allocations, advance=None) -> float:
	"""Invoice-currency total posted to one party account, including its advance."""
	account = clean_text(account)
	total = Decimal(0)
	for row in allocations or []:
		if clean_text((row or {}).get("account")) == account:
			total += _decimal((row or {}).get("allocated_amount"))
	if advance and clean_text(advance.get("account")) == account:
		total += _decimal(advance.get("amount"))
	return _show(total)


def paid_and_received(payment_type, bank_amount, bank_currency, party_currency, party_amount):
	"""Map the bank amount onto Paid Amount and Received Amount.

	Those two fields are the same number when the bank and the header party
	account share a currency, because Payment Entry rejects a received amount
	above the paid amount in that case. Otherwise the bank field keeps the
	bank amount and the party field keeps that account's own total.
	"""
	bank_amount = _show(_decimal(bank_amount))
	party_amount = _show(_decimal(party_amount))
	if clean_text(bank_currency) == clean_text(party_currency):
		return bank_amount, bank_amount
	if clean_text(payment_type) == "Pay":
		return bank_amount, party_amount
	return party_amount, bank_amount
