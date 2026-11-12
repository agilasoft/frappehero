# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Choose the receivable for invoices that were posted to the wrong account.

Pure functions. The desk page calls these, and the tests run without a site.
USD invoices go to the USD receivable. Every other currency goes to the
company-currency receivable. A receipt keeps its bank amount. Nothing here
cancels a document.
"""

from decimal import ROUND_HALF_UP, Decimal

from frappehero.flags import clean_text

USD = "USD"
SALES_INVOICE = "Sales Invoice"
MOVE = "move"
HELD = "held"
SINGLE = "single"
MULTI = "multi"


class ReceivableRepairError(ValueError):
	"""The accounts cannot be used for this repair."""


def account_for_currency(currency, usd_account, other_account) -> str:
	"""USD uses the USD receivable. Every other currency uses the other one."""
	if clean_text(currency).upper() == USD:
		return clean_text(usd_account)
	return clean_text(other_account)


def party_account_choice(party_type, currencies, usd_account, other_account) -> str:
	"""One party account per customer. Mixed currencies stay on the company receivable.

	A customer group has no single currency, so it uses the company receivable.
	A customer whose open invoices are all USD uses the USD receivable.
	"""
	other_account = clean_text(other_account)
	if clean_text(party_type) != "Customer":
		return other_account
	codes = {clean_text(currency).upper() for currency in currencies or [] if clean_text(currency)}
	if codes == {USD}:
		return clean_text(usd_account)
	return other_account


def check_accounts(company, company_currency, wrong_account, usd_account, other_account, accounts) -> None:
	"""The two destinations must be receivable ledgers in this company."""
	company = clean_text(company)
	company_currency = clean_text(company_currency).upper()
	wrong_account = clean_text(wrong_account)
	usd_account = clean_text(usd_account)
	other_account = clean_text(other_account)
	errors = []
	if not company:
		errors.append("Choose a company.")
	if not company_currency:
		errors.append("The company needs a default currency.")
	if not wrong_account:
		errors.append("Choose the receivable to leave.")
	if not usd_account:
		errors.append("Choose the USD receivable.")
	if not other_account:
		errors.append("Choose the receivable for other currencies.")
	if wrong_account and wrong_account in {usd_account, other_account}:
		errors.append("The receivable to leave is also a receivable to use.")
	if usd_account and usd_account == other_account:
		errors.append("The USD receivable and the other receivable are the same account.")
	_account_error(errors, accounts, wrong_account, company, "The receivable to leave", None)
	_account_error(errors, accounts, usd_account, company, "The USD receivable", USD)
	_account_error(errors, accounts, other_account, company, "The other receivable", company_currency)
	if errors:
		raise ReceivableRepairError(" ".join(errors))


def plan_repair(
	company,
	wrong_account,
	usd_account,
	other_account,
	company_currency,
	invoices,
	payments,
) -> dict:
	"""Plan the move. Held receipts keep their invoices on the current account.

	Cancelled documents are omitted. A receipt that does not allocate one of
	these invoices is omitted, so an advance with no invoice stays where it is.
	"""
	company = clean_text(company)
	wrong_account = clean_text(wrong_account)
	usd_account = clean_text(usd_account)
	other_account = clean_text(other_account)
	company_currency = clean_text(company_currency).upper()
	invoice_rows = []
	by_name = {}
	for source in invoices or []:
		row = _invoice_row(source, company, wrong_account, usd_account, other_account, company_currency)
		if row is None:
			context = _context_invoice(source, company)
			if context and context["name"] not in by_name:
				by_name[context["name"]] = context
			continue
		invoice_rows.append(row)
		by_name[row["name"]] = row

	payment_rows = []
	for source in payments or []:
		row = _payment_row(source, company, by_name, company_currency, wrong_account)
		if row is not None:
			payment_rows.append(row)

	_hold_connected(invoice_rows, payment_rows)
	moving_invoices = [row for row in invoice_rows if row["action"] == MOVE]
	moving_payments = [row for row in payment_rows if row["action"] == MOVE]
	chains = _chains(moving_invoices, moving_payments)
	chain_of = {}
	for index, chain in enumerate(chains):
		for name in chain["invoices"]:
			chain_of[("invoice", name)] = index
		for name in chain["payments"]:
			chain_of[("payment", name)] = index
	for row in invoice_rows:
		row["chain"] = chain_of.get(("invoice", row["name"]))
	for row in payment_rows:
		row["chain"] = chain_of.get(("payment", row["name"]))

	return {
		"company": company,
		"wrong_account": wrong_account,
		"usd_account": usd_account,
		"other_account": other_account,
		"company_currency": company_currency,
		"invoices": invoice_rows,
		"payments": payment_rows,
		"chains": chains,
		"signature": {
			"invoices": sorted(row["name"] for row in moving_invoices),
			"payments": sorted(row["name"] for row in moving_payments),
		},
		"counts": {
			"move_invoices": len(moving_invoices),
			"held_invoices": sum(1 for row in invoice_rows if row["action"] == HELD),
			"move_payments": len(moving_payments),
			"held_payments": sum(1 for row in payment_rows if row["action"] == HELD),
		},
	}


def selection_matches(expected, plan) -> bool:
	"""True when Apply is still looking at the same invoices and receipts."""
	expected = expected or {}
	signature = (plan or {}).get("signature") or {}
	return _names(expected.get("invoices")) == list(signature.get("invoices") or []) and _names(
		expected.get("payments")
	) == list(signature.get("payments") or [])


def _account_error(errors, accounts, name, company, label, currency):
	if not name:
		return
	row = (accounts or {}).get(name) or {}
	if not row:
		errors.append(f"{label} {name} was not found.")
		return
	if clean_text(row.get("company")) != company:
		errors.append(f"{label} {name} belongs to another company.")
	if int(row.get("is_group") or 0):
		errors.append(f"{label} {name} is a group account.")
	if currency is None:
		return
	if clean_text(row.get("account_type")) != "Receivable":
		errors.append(f"{label} {name} is not a receivable.")
	actual = clean_text(row.get("account_currency")).upper()
	if actual != currency:
		errors.append(f"{label} {name} is in {actual or 'no currency'}, not {currency}.")


def _invoice_row(source, company, wrong_account, usd_account, other_account, company_currency):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	if clean_text(source.get("debit_to")) != wrong_account:
		return None
	currency = clean_text(source.get("currency")).upper()
	if not currency:
		return {
			"name": name,
			"customer": clean_text(source.get("customer")),
			"currency": "",
			"posting_date": clean_text(source.get("posting_date")),
			"outstanding_amount": _show(_money(source.get("outstanding_amount"))),
			"conversion_rate": _show(_money(source.get("conversion_rate"), 9)),
			"party_account_currency": clean_text(source.get("party_account_currency")).upper(),
			"is_return": 1 if int(source.get("is_return") or 0) else 0,
			"return_against": clean_text(source.get("return_against")),
			"from_account": wrong_account,
			"to_account": wrong_account,
			"account_currency": clean_text(source.get("party_account_currency")).upper(),
			"debit_to": wrong_account,
			"action": HELD,
			"reason": f"{name} has no currency.",
			"chain": None,
		}
	target = account_for_currency(currency, usd_account, other_account)
	return {
		"name": name,
		"customer": clean_text(source.get("customer")),
		"currency": currency,
		"posting_date": clean_text(source.get("posting_date")),
		"outstanding_amount": _show(_money(source.get("outstanding_amount"))),
		"conversion_rate": _show(_money(source.get("conversion_rate"), 9)),
		"party_account_currency": clean_text(source.get("party_account_currency")).upper(),
		"is_return": 1 if int(source.get("is_return") or 0) else 0,
		"return_against": clean_text(source.get("return_against")),
		"from_account": wrong_account,
		"to_account": target,
		"account_currency": USD if currency == USD else company_currency,
		"debit_to": wrong_account,
		"action": MOVE,
		"reason": "",
		"chain": None,
	}


def _context_invoice(source, company):
	"""An invoice a receipt also allocates, already on some other receivable."""
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	debit_to = clean_text(source.get("debit_to"))
	if not debit_to:
		return None
	return {
		"name": name,
		"currency": clean_text(source.get("currency")).upper(),
		"conversion_rate": _show(_money(source.get("conversion_rate"), 9)),
		"party_account_currency": clean_text(source.get("party_account_currency")).upper(),
		"debit_to": debit_to,
		"action": "",
	}


def _payment_row(source, company, invoices, company_currency, wrong_account):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	payment_type = clean_text(source.get("payment_type"))
	references = []
	reason = ""
	touches = False
	if payment_type not in ("Receive", "Pay"):
		reason = "Payment type must be Receive or Pay."
	for reference in source.get("references") or []:
		if _touches_repair(reference, invoices):
			touches = True
		built, problem = _reference_row(reference, invoices, company_currency)
		if problem and not reason:
			reason = problem
		if built is not None:
			references.append(built)
	if not touches:
		return None
	if reason:
		return _held_payment(source, name, payment_type, references, reason)

	accounts = {row["account"] for row in references if row.get("account")}
	unallocated = _money(source.get("unallocated_amount"))
	party_account, party_currency, _party_field = _party_fields(source, payment_type)
	advance_stays = unallocated > 0 and (
		not party_account or party_account not in accounts or len(accounts) != 1
	)
	if len(accounts) > 1 or advance_stays:
		mode = MULTI
		advance_account = party_account or wrong_account if unallocated > 0 else ""
		if source.get("has_taxes") or source.get("has_deductions"):
			return _held_payment(
				source,
				name,
				payment_type,
				references,
				"This receipt has taxes or deductions, so it cannot use more than one receivable.",
			)
	else:
		mode = SINGLE
		advance_account = ""
		target_currency = next((row["account_currency"] for row in references), party_currency)
		if target_currency != party_currency and (source.get("has_taxes") or source.get("has_deductions")):
			return _held_payment(
				source,
				name,
				payment_type,
				references,
				"Changing the receivable currency on a receipt with taxes or deductions would change the tax.",
			)

	if mode == SINGLE:
		header = _single_header(
			source, payment_type, references, company_currency, unallocated, party_currency
		)
	else:
		header = _multi_header(references, party_currency)
	row = _payment_shell(source, name, payment_type, references, MOVE, "")
	bank_account, bank_amount = _bank(source, payment_type)
	row.update(
		{
			"mode": mode,
			"bank_account": bank_account,
			"bank_amount": _show(bank_amount),
			"unallocated_amount": _show(unallocated),
			"advance_account": advance_account,
			"previous_party_currency": party_currency,
		}
	)
	row.update(header)
	return row


def _touches_repair(reference, invoices) -> bool:
	invoice = invoices.get(clean_text((reference or {}).get("reference_name")))
	return bool(invoice and invoice.get("action") in (MOVE, HELD))


def _reference_row(reference, invoices, company_currency):
	reference = reference or {}
	allocated = _money(reference.get("allocated_amount"))
	doctype = clean_text(reference.get("reference_doctype")) or SALES_INVOICE
	name = clean_text(reference.get("reference_name"))
	if not name and allocated == 0:
		return None, ""
	if allocated < 0:
		return None, f"Allocated amount for {name or 'a row'} cannot be negative."
	if doctype != SALES_INVOICE:
		if allocated == 0:
			return None, ""
		return None, "This receipt allocates a document that is not a sales invoice."
	invoice = invoices.get(name)
	if invoice is None:
		if allocated == 0:
			return None, ""
		return None, f"Sales Invoice {name} is not available for this receipt."
	if allocated == 0:
		return None, ""
	return _described_reference(reference, invoice, allocated, company_currency), ""


def _described_reference(reference, invoice, allocated, company_currency):
	in_repair = invoice.get("action") in (MOVE, HELD)
	invoice_currency = clean_text(invoice.get("currency")).upper()
	invoice_amount = _invoice_allocation(reference, invoice, allocated, company_currency)
	if invoice.get("action") == MOVE:
		account = invoice["to_account"]
		account_currency = invoice["account_currency"]
		account_amount = _account_amount(
			invoice_amount,
			invoice_currency,
			account_currency,
			invoice.get("conversion_rate"),
			company_currency,
		)
	elif invoice.get("action") == HELD:
		account = invoice["from_account"]
		account_currency = invoice["account_currency"]
		account_amount = allocated
	else:
		account = clean_text(invoice.get("debit_to"))
		account_currency = clean_text(invoice.get("party_account_currency")).upper()
		account_amount = allocated
	conversion = _money(invoice.get("conversion_rate"), 9)
	exchange = conversion if invoice_currency and invoice_currency != company_currency else Decimal(1)
	return {
		"row_name": clean_text(reference.get("row_name") or reference.get("name")),
		"reference_doctype": SALES_INVOICE,
		"reference_name": invoice["name"],
		"qualifying": 1 if in_repair else 0,
		"account": account,
		"account_currency": account_currency,
		"invoice_currency": invoice_currency,
		"invoice_amount": _show(invoice_amount),
		"allocated_amount": _show(account_amount),
		"exchange_rate": _show(exchange if exchange else Decimal(1)),
	}


def _invoice_allocation(reference, invoice, allocated, company_currency):
	hero = reference.get("hero_allocated_invoice_amount")
	if hero not in (None, ""):
		return _money(hero)
	invoice_currency = clean_text(invoice.get("currency")).upper()
	account_currency = clean_text(
		reference.get("account_currency")
		or invoice.get("party_account_currency")
		or invoice.get("account_currency")
	).upper()
	if account_currency and account_currency == invoice_currency:
		return allocated
	conversion = _money(invoice.get("conversion_rate"), 9)
	exchange = _money(reference.get("exchange_rate"), 9)
	if account_currency == company_currency and invoice_currency and invoice_currency != company_currency:
		rate = conversion or exchange
	else:
		rate = exchange or conversion
	if rate:
		return _money(allocated / rate)
	return allocated


def _account_amount(invoice_amount, invoice_currency, account_currency, conversion_rate, company_currency):
	if account_currency == invoice_currency:
		return invoice_amount
	if account_currency == company_currency:
		rate = (
			Decimal(1) if invoice_currency == company_currency else _money(conversion_rate, 9) or Decimal(1)
		)
		return _money(invoice_amount * rate)
	return invoice_amount


def _single_header(source, payment_type, references, company_currency, unallocated, party_currency):
	account = references[0]["account"]
	currency = references[0]["account_currency"]
	party_amount = _money(sum((_money(row["allocated_amount"]) for row in references), Decimal(0)))
	if unallocated > 0 and party_currency == currency:
		party_amount = _money(party_amount + unallocated)
	base = _party_base(source, payment_type)
	if not base:
		base = _money(
			sum(
				(
					_money(row["invoice_amount"])
					* (
						_money(row["exchange_rate"], 9)
						if row["invoice_currency"] != company_currency
						else Decimal(1)
					)
					for row in references
				),
				Decimal(0),
			)
		)
		if unallocated > 0 and party_currency == company_currency:
			base = _money(base + unallocated)
	if currency == company_currency or not party_amount:
		rate = Decimal(1)
	else:
		rate = _money(base / party_amount, 9)
	amount_field, rate_field = _amount_fields(payment_type)
	_, _, party_field = _party_fields(source, payment_type)
	return {
		"party_account": account,
		"party_account_currency": currency,
		"party_amount": _show(party_amount),
		"party_exchange_rate": _show(rate),
		"base_party_amount": _show(base if currency != company_currency else party_amount),
		"party_account_field": party_field,
		"party_currency_field": _currency_field(payment_type),
		"party_amount_field": amount_field,
		"party_rate_field": rate_field,
	}


def _multi_header(references, party_currency):
	return {
		"party_account": references[0]["account"] if references else "",
		"party_account_currency": references[0]["account_currency"] if references else party_currency,
		"party_amount": 0,
		"party_exchange_rate": 1,
		"base_party_amount": 0,
		"party_account_field": "",
		"party_currency_field": "",
		"party_amount_field": "",
		"party_rate_field": "",
	}


def _held_payment(source, name, payment_type, references, reason):
	bank_account, bank_amount = _bank(source, payment_type)
	_, _, party_field = _party_fields(source, payment_type)
	row = _payment_shell(source, name, payment_type, references, HELD, reason)
	row.update(
		{
			"mode": "",
			"bank_account": bank_account,
			"bank_amount": _show(bank_amount),
			"advance_account": "",
			"party_account": "",
			"party_account_currency": "",
			"party_amount": 0,
			"party_exchange_rate": 1,
			"base_party_amount": 0,
			"party_account_field": party_field,
			"party_currency_field": "",
			"party_amount_field": "",
			"party_rate_field": "",
		}
	)
	return row


def _payment_shell(source, name, payment_type, references, action, reason):
	return {
		"name": name,
		"party": clean_text(source.get("party")),
		"posting_date": clean_text(source.get("posting_date")),
		"payment_type": payment_type,
		"action": action,
		"reason": reason,
		"references": references,
		"chain": None,
	}


def _hold_connected(invoices, payments):
	"""A held receipt holds every invoice it allocates, and the receipts on those invoices."""
	by_invoice = {row["name"]: row for row in invoices}
	changed = True
	while changed:
		changed = False
		for payment in payments:
			names = []
			for reference in payment["references"]:
				if reference["reference_name"] in by_invoice:
					names.append(reference["reference_name"])
			if payment["action"] == HELD:
				for invoice_name in names:
					invoice = by_invoice[invoice_name]
					if invoice["action"] != HELD:
						invoice["action"] = HELD
						invoice["to_account"] = invoice["from_account"]
						invoice["reason"] = f"Held by {payment['name']}: {payment['reason']}"
						changed = True
				continue
			for invoice_name in names:
				invoice = by_invoice[invoice_name]
				if invoice["action"] == HELD:
					payment["action"] = HELD
					payment["mode"] = ""
					payment["reason"] = f"Held because {invoice_name} stays on the current receivable."
					changed = True
					break
	for payment in payments:
		if payment["action"] == HELD:
			for reference in payment["references"]:
				reference["qualifying"] = 0


def _chains(invoices, payments):
	parent = {}

	def find(node):
		parent.setdefault(node, node)
		while parent[node] != node:
			parent[node] = parent[parent[node]]
			node = parent[node]
		return node

	def union(left, right):
		root_left, root_right = find(left), find(right)
		if root_left != root_right:
			parent[root_right] = root_left

	invoice_names = {row["name"] for row in invoices}
	for row in invoices:
		find(("invoice", row["name"]))
		against = row.get("return_against")
		if against in invoice_names:
			union(("invoice", row["name"]), ("invoice", against))
	for payment in payments:
		find(("payment", payment["name"]))
		for reference in payment["references"]:
			if reference.get("qualifying") and reference["reference_name"] in invoice_names:
				union(("payment", payment["name"]), ("invoice", reference["reference_name"]))

	groups = {}
	for node in list(parent):
		root = find(node)
		bucket = groups.setdefault(root, {"invoices": [], "payments": []})
		kind, name = node
		bucket["invoices" if kind == "invoice" else "payments"].append(name)
	chains = []
	for bucket in groups.values():
		bucket["invoices"] = sorted(set(bucket["invoices"]))
		bucket["payments"] = sorted(set(bucket["payments"]))
		if bucket["invoices"] or bucket["payments"]:
			chains.append(bucket)
	chains.sort(key=lambda row: (row["invoices"][:1], row["payments"][:1]))
	return chains


def _party_fields(source, payment_type):
	if payment_type == "Pay":
		return (
			clean_text(source.get("paid_to")),
			clean_text(source.get("paid_to_account_currency")).upper(),
			"paid_to",
		)
	return (
		clean_text(source.get("paid_from")),
		clean_text(source.get("paid_from_account_currency")).upper(),
		"paid_from",
	)


def _amount_fields(payment_type):
	if payment_type == "Pay":
		return "received_amount", "target_exchange_rate"
	return "paid_amount", "source_exchange_rate"


def _currency_field(payment_type):
	if payment_type == "Pay":
		return "paid_to_account_currency"
	return "paid_from_account_currency"


def _bank(source, payment_type):
	if payment_type == "Pay":
		return clean_text(source.get("paid_from")), _money(source.get("paid_amount"))
	return clean_text(source.get("paid_to")), _money(source.get("received_amount"))


def _party_base(source, payment_type):
	if payment_type == "Pay":
		return _money(source.get("base_received_amount"))
	return _money(source.get("base_paid_amount"))


def _status(value) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _names(value):
	if isinstance(value, str) or value is None:
		return []
	return sorted({clean_text(name) for name in value if clean_text(name)})


def _money(value, places=2) -> Decimal:
	try:
		number = Decimal(str(value if value not in (None, "") else 0))
	except Exception:
		return Decimal(0)
	if not number.is_finite():
		return Decimal(0)
	quant = Decimal(1).scaleb(-places)
	return number.quantize(quant, rounding=ROUND_HALF_UP)


def _show(number) -> float:
	return float(number)
