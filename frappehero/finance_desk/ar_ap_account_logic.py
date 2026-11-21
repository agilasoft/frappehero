# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Change the receivable or payable GL account on submitted invoices.

Pure functions. The desk page calls these, and the tests run without a site.
The new account can use another currency. A change is between the invoice
currency and the company currency, and the company-currency amount stays as
submitted. Receipts and journals that post the invoice change with it. An
exchange gain or loss journal changes the line on the current account, and
the gain or loss account stays. A receipt that still posts to the current
account changes too. Nothing here cancels a document.
"""

from decimal import ROUND_HALF_UP, Decimal

from frappehero.flags import clean_text

SALES_INVOICE = "Sales Invoice"
PURCHASE_INVOICE = "Purchase Invoice"
RECEIVABLE = "receivable"
PAYABLE = "payable"
MOVE = "move"
HELD = "held"
STAY = "stay"
SINGLE = "single"
MULTI = "multi"
PAYMENT_ENTRY = "Payment Entry"
EXCHANGE_GAIN_OR_LOSS = "Exchange Gain Or Loss"
EXCHANGE_RATE_REVALUATION = "Exchange Rate Revaluation"
EXCHANGE_VOUCHERS = {EXCHANGE_GAIN_OR_LOSS, EXCHANGE_RATE_REVALUATION}
_SIDES = {
	RECEIVABLE: {
		"doctype": SALES_INVOICE,
		"account_type": "Receivable",
		"account_field": "debit_to",
		"party_type": "Customer",
	},
	PAYABLE: {
		"doctype": PURCHASE_INVOICE,
		"account_type": "Payable",
		"account_field": "credit_to",
		"party_type": "Supplier",
	},
}


class ArApAccountError(ValueError):
	"""These GL accounts cannot be used for this change."""


def side_choice(value) -> dict:
	"""Receivable moves sales invoices. Payable moves purchase invoices."""
	key = clean_text(value).lower()
	if key not in _SIDES:
		raise ArApAccountError("Choose Receivable or Payable.")
	return {"name": key, **_SIDES[key]}


def check_accounts(company, side, from_account, to_account, accounts) -> dict:
	"""Both ledgers must be the account type of this side.

	Returns the currency of each account. They can differ.
	"""
	chosen = side_choice(side)
	company = clean_text(company)
	from_account = clean_text(from_account)
	to_account = clean_text(to_account)
	errors = []
	if not company:
		errors.append("Choose a company.")
	if not from_account:
		errors.append("Choose the current GL account.")
	if not to_account:
		errors.append("Choose the new GL account.")
	if from_account and from_account == to_account:
		errors.append("The current GL account and the new GL account are the same.")
	currency = _account_error(
		errors, accounts, from_account, company, chosen["account_type"], "The current GL account"
	)
	other = _account_error(
		errors, accounts, to_account, company, chosen["account_type"], "The new GL account"
	)
	if errors:
		raise ArApAccountError(" ".join(errors))
	return {"from_currency": currency, "to_currency": other}


def plan_accounts(
	company,
	side,
	from_account,
	to_account,
	invoices,
	payments,
	journals,
	company_currency="",
	from_currency="",
	to_currency="",
) -> dict:
	"""Plan the move. A held voucher keeps its invoices on the current account."""
	chosen = side_choice(side)
	company = clean_text(company)
	from_account = clean_text(from_account)
	to_account = clean_text(to_account)
	company_currency = clean_text(company_currency).upper()
	from_currency = clean_text(from_currency).upper()
	to_currency = clean_text(to_currency).upper()
	invoice_rows = []
	by_name = {}
	for source in invoices or []:
		row = _invoice_row(
			source, chosen, company, from_account, to_account, company_currency, from_currency, to_currency
		)
		if row is None:
			context = _context_invoice(source, chosen, company)
			if context and context["name"] not in by_name:
				by_name[context["name"]] = context
			continue
		invoice_rows.append(row)
		by_name[row["name"]] = row

	payment_rows = []
	for source in payments or []:
		row = _payment_row(
			source,
			company,
			by_name,
			from_account,
			to_account,
			chosen["doctype"],
			company_currency,
			from_currency,
			to_currency,
		)
		if row is not None:
			payment_rows.append(row)

	journal_rows = []
	for source in journals or []:
		row = _journal_row(
			source,
			company,
			by_name,
			from_account,
			to_account,
			chosen["doctype"],
			company_currency,
			from_currency,
			to_currency,
		)
		if row is not None:
			journal_rows.append(row)

	_hold_connected(invoice_rows, payment_rows, journal_rows)
	moving_invoices = [row for row in invoice_rows if row["action"] == MOVE]
	moving_payments = [row for row in payment_rows if row["action"] == MOVE]
	moving_journals = [row for row in journal_rows if row["action"] == MOVE]
	chains = _chains(moving_invoices, moving_payments, moving_journals)
	chain_of = {}
	for index, chain in enumerate(chains):
		for name in chain["invoices"]:
			chain_of[("invoice", name)] = index
		for name in chain["payments"]:
			chain_of[("payment", name)] = index
		for name in chain["journals"]:
			chain_of[("journal", name)] = index
	for row in invoice_rows:
		row["chain"] = chain_of.get(("invoice", row["name"]))
	for row in payment_rows:
		row["chain"] = chain_of.get(("payment", row["name"]))
	for row in journal_rows:
		row["chain"] = chain_of.get(("journal", row["name"]))
	_mark_exchange_journals(payment_rows, journal_rows, chosen["doctype"])
	return {
		"company": company,
		"side": chosen["name"],
		"doctype": chosen["doctype"],
		"account_field": chosen["account_field"],
		"from_account": from_account,
		"to_account": to_account,
		"company_currency": company_currency,
		"from_currency": from_currency,
		"to_currency": to_currency,
		"invoices": invoice_rows,
		"payments": payment_rows,
		"journals": journal_rows,
		"chains": chains,
		"signature": {
			"invoices": sorted(row["name"] for row in moving_invoices),
			"payments": sorted(row["name"] for row in moving_payments),
			"journals": sorted(row["name"] for row in moving_journals),
		},
		"counts": {
			"move_invoices": len(moving_invoices),
			"stay_invoices": sum(1 for row in invoice_rows if row["action"] == STAY),
			"held_invoices": sum(1 for row in invoice_rows if row["action"] == HELD),
			"move_payments": len(moving_payments),
			"held_payments": sum(1 for row in payment_rows if row["action"] == HELD),
			"move_journals": len(moving_journals),
			"held_journals": sum(1 for row in journal_rows if row["action"] == HELD),
		},
	}


def selection_matches(expected, plan) -> bool:
	"""True when Apply is still looking at the same invoices, payments, and journals."""
	expected = expected or {}
	signature = (plan or {}).get("signature") or {}
	return (
		_names(expected.get("invoices")) == list(signature.get("invoices") or [])
		and _names(expected.get("payments")) == list(signature.get("payments") or [])
		and _names(expected.get("journals")) == list(signature.get("journals") or [])
	)


def _account_error(errors, accounts, name, company, account_type, label) -> str:
	if not name:
		return ""
	row = (accounts or {}).get(name) or {}
	if not row:
		errors.append(f"{label} {name} was not found.")
		return ""
	if clean_text(row.get("company")) != company:
		errors.append(f"{label} {name} belongs to another company.")
	if int(row.get("is_group") or 0):
		errors.append(f"{label} {name} is a group account.")
	actual_type = clean_text(row.get("account_type"))
	if actual_type != account_type:
		errors.append(f"{label} {name} is not a {account_type.lower()}.")
	return clean_text(row.get("account_currency")).upper()


def _invoice_row(
	source, chosen, company, from_account, to_account, company_currency, from_currency, to_currency
):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if clean_text(source.get("doctype") or chosen["doctype"]) != chosen["doctype"]:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	if clean_text(source.get("account")) != from_account:
		return None
	invoice_currency = clean_text(source.get("currency")).upper()
	previous = clean_text(source.get("party_account_currency")).upper()
	action = MOVE
	destination = to_account
	account_currency = to_currency or previous
	reason = ""
	if from_currency and to_currency and from_currency != to_currency:
		if _currency_change_allowed(invoice_currency, from_currency, to_currency, company_currency):
			account_currency = to_currency
		else:
			action = STAY
			destination = from_account
			account_currency = previous or from_currency
			shown = invoice_currency or "no currency"
			reason = (
				f"{name} is in {shown}. The accounts are in {from_currency} and {to_currency}. "
				"A currency change stays between the invoice currency and the company currency."
			)
	return {
		"name": name,
		"doctype": chosen["doctype"],
		"account_field": chosen["account_field"],
		"party": clean_text(source.get("party")),
		"currency": invoice_currency,
		"posting_date": clean_text(source.get("posting_date")),
		"outstanding_amount": _show(_money(source.get("outstanding_amount"))),
		"conversion_rate": _show(_money(source.get("conversion_rate"), 9)),
		"from_account": from_account,
		"to_account": destination,
		"account": destination if action == MOVE else from_account,
		"account_currency": account_currency,
		"previous_account_currency": previous,
		"is_return": 1 if int(source.get("is_return") or 0) else 0,
		"return_against": clean_text(source.get("return_against")),
		"action": action,
		"reason": reason,
		"chain": None,
	}


def _context_invoice(source, chosen, company):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if clean_text(source.get("doctype") or chosen["doctype"]) != chosen["doctype"]:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	account = clean_text(source.get("account"))
	if not account:
		return None
	return {
		"name": name,
		"doctype": chosen["doctype"],
		"account": account,
		"action": "",
	}


def _payment_row(
	source,
	company,
	invoices,
	from_account,
	to_account,
	doctype,
	company_currency,
	from_currency,
	to_currency,
):
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
	party_account, party_currency, party_field, currency_field = _party_fields(source, payment_type)
	bank_account, bank_amount = _bank(source, payment_type)
	posts_current = party_account == from_account
	for reference in source.get("references") or []:
		if _allocated(reference) and _invoice_action(reference, invoices, doctype) in (MOVE, HELD):
			touches = True
		built, problem = _reference_row(
			reference,
			invoices,
			doctype,
			from_account,
			to_account,
			party_account,
			party_currency or from_currency,
			company_currency,
		)
		if problem and not reason:
			reason = problem
		if built is not None:
			references.append(built)
	if posts_current:
		touches = True
	if not touches:
		return None
	currency_change = any(row.get("restate") for row in references)
	if (
		not reason
		and posts_current
		and from_currency
		and to_currency
		and from_currency != to_currency
		and not currency_change
	):
		reason = (
			f"This receipt posts to {from_account} in {from_currency}. Its invoice is not moving, "
			f"so the currency cannot change to {to_currency}."
		)
	if not reason and any(row["kind"] == "other" for row in references):
		targets = {row["account"] for row in references if row["kind"] == "invoice" and row.get("account")}
		if len(targets) > 1:
			reason = "This payment allocates another document, so it cannot be split across accounts."
		elif currency_change:
			reason = "This payment allocates another document, so its currency cannot change."
	if reason:
		return _held_payment(
			source, name, payment_type, references, reason, bank_account, bank_amount, party_field
		)

	targets = {row["account"] for row in references if row["kind"] == "invoice" and row.get("account")}
	unallocated = _money(source.get("unallocated_amount"))
	if party_account not in {from_account, to_account}:
		return _held_payment(
			source,
			name,
			payment_type,
			references,
			f"This payment posts to {party_account or 'no account'}, not {from_account}.",
			bank_account,
			bank_amount,
			party_field,
		)
	if len(targets) > 1 or (unallocated > 0 and currency_change):
		if source.get("has_taxes") or source.get("has_deductions"):
			return _held_payment(
				source,
				name,
				payment_type,
				references,
				"This payment has taxes or deductions, so it cannot use more than one account.",
				bank_account,
				bank_amount,
				party_field,
			)
		mode = MULTI
		new_account = to_account if to_account in targets else sorted(targets)[0]
		advance_account = party_account if unallocated > 0 and party_account != new_account else ""
		if currency_change and unallocated > 0:
			advance_account = party_account
		rewrite = 0
		header = {}
	else:
		mode = SINGLE
		if currency_change and (source.get("has_taxes") or source.get("has_deductions")):
			return _held_payment(
				source,
				name,
				payment_type,
				references,
				"Changing the account currency on a payment with taxes or deductions would change the tax.",
				bank_account,
				bank_amount,
				party_field,
			)
		new_account = to_account if posts_current or to_account in targets else party_account
		advance_account = ""
		rewrite = 1 if party_account != new_account else 0
		for reference in references:
			if reference["kind"] == "other":
				reference["account"] = new_account
			elif (
				posts_current
				and reference["kind"] == "invoice"
				and not reference.get("restate")
				and reference.get("account") != new_account
			):
				reference["account"] = new_account
		header = {}
		if currency_change:
			header = _currency_header(source, payment_type, references, company_currency)
	row = _payment_shell(source, name, payment_type, references, MOVE, "")
	row.update(
		{
			"mode": mode,
			"bank_account": bank_account,
			"bank_amount": _show(bank_amount),
			"unallocated_amount": _show(unallocated),
			"advance_account": advance_account,
			"party_account": new_account,
			"party_account_currency": party_currency,
			"party_account_field": party_field,
			"party_currency_field": currency_field,
			"rewrite_party": rewrite,
			"restate": 1 if currency_change else 0,
			"party_amount": 0,
			"party_exchange_rate": 1,
			"base_party_amount": 0,
			"party_amount_field": "",
			"party_rate_field": "",
			"previous_party_currency": party_currency,
		}
	)
	row.update(header)
	return row


def _reference_row(
	reference, invoices, doctype, from_account, to_account, party_account, source_currency, company_currency
):
	reference = reference or {}
	allocated = _allocated(reference)
	ref_doctype = clean_text(reference.get("reference_doctype")) or doctype
	ref_name = clean_text(reference.get("reference_name"))
	if not ref_name and allocated == 0:
		return None, ""
	if allocated < 0:
		return None, f"Allocated amount for {ref_name or 'a row'} cannot be negative."
	row_name = clean_text(reference.get("row_name") or reference.get("name"))
	if ref_doctype != doctype:
		if allocated == 0:
			return None, ""
		return (
			{
				"row_name": row_name,
				"reference_doctype": ref_doctype,
				"reference_name": ref_name,
				"kind": "other",
				"qualifying": 0,
				"account": party_account,
				"allocated_amount": _show(allocated),
			},
			"",
		)
	invoice = invoices.get(ref_name)
	if invoice is None:
		if allocated == 0:
			return None, ""
		return None, f"{doctype} {ref_name} is not available for this payment."
	if allocated == 0:
		return None, ""
	if invoice.get("action") == MOVE:
		account = to_account
	elif invoice.get("action") in (HELD, STAY):
		account = from_account
	else:
		account = clean_text(invoice.get("account"))
	destination = clean_text(invoice.get("account_currency")).upper()
	if invoice.get("action") == MOVE and source_currency and destination and source_currency != destination:
		return (
			_restated_reference(
				reference, invoice, allocated, company_currency, source_currency, doctype, row_name
			),
			"",
		)
	return (
		{
			"row_name": row_name,
			"reference_doctype": doctype,
			"reference_name": ref_name,
			"kind": "invoice",
			"qualifying": 1 if invoice.get("action") in (MOVE, HELD) else 0,
			"account": account,
			"account_currency": destination,
			"allocated_amount": _show(allocated),
			"restate": 0,
		},
		"",
	)


def _journal_row(
	source, company, invoices, from_account, to_account, doctype, company_currency, from_currency, to_currency
):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	lines = []
	reason = ""
	touches = False
	voucher_type = clean_text(source.get("voucher_type"))
	for line in source.get("lines") or []:
		built, problem, touched = _journal_line(
			line,
			invoices,
			doctype,
			from_account,
			to_account,
			company_currency,
			from_currency,
			to_currency,
			voucher_type,
		)
		if touched:
			touches = True
		if problem and not reason:
			reason = problem
		if built is not None:
			lines.append(built)
	if not touches:
		return None
	debit = _money(sum((_money(line.get("debit")) for line in source.get("lines") or []), Decimal(0)))
	return {
		"name": name,
		"posting_date": clean_text(source.get("posting_date")),
		"voucher_type": voucher_type,
		"action": HELD if reason else MOVE,
		"reason": reason,
		"debit_total": _show(debit),
		"lines": lines,
		"chain": None,
	}


def _journal_line(
	line,
	invoices,
	doctype,
	from_account,
	to_account,
	company_currency,
	from_currency,
	to_currency,
	voucher_type="",
):
	line = line or {}
	ref_name = clean_text(line.get("reference_name"))
	ref_type = clean_text(line.get("reference_type"))
	account = clean_text(line.get("account"))
	built = {
		"row_name": clean_text(line.get("row_name") or line.get("name")),
		"account": account,
		"reference_type": ref_type,
		"reference_name": ref_name,
		"action": "keep",
		"touches": 0,
	}
	invoice = invoices.get(ref_name) if ref_type == doctype else None
	if voucher_type in EXCHANGE_VOUCHERS and account == from_account:
		if invoice and invoice.get("action") == STAY:
			built["touches"] = 1
			return (
				built,
				f"{ref_name} stays in its currency, so this exchange journal stays on {from_account}.",
				True,
			)
		return _move_exchange_line(built, line, to_account, from_currency, to_currency, company_currency)
	if voucher_type in EXCHANGE_VOUCHERS:
		if invoice and invoice.get("action") in (MOVE, HELD):
			built["touches"] = 1
			return built, "", True
		return built, "", False
	if invoice is None or invoice.get("action") not in (MOVE, HELD):
		return built, "", False
	built["touches"] = 1
	if invoice.get("action") != MOVE:
		return built, "", True
	if account == from_account:
		built["action"] = "move"
		built["account"] = to_account
		if from_currency and to_currency and from_currency != to_currency:
			problem = _restate_journal_line(built, line, invoice, to_currency, company_currency)
			if problem:
				built["action"] = "keep"
				built["account"] = account
				return built, problem, True
		return built, "", True
	if account == to_account:
		return built, "", True
	return built, f"This journal posts {ref_name} to {account or 'no account'}, not {from_account}.", True


def _move_exchange_line(built, line, to_account, from_currency, to_currency, company_currency):
	"""Move the receivable or payable line. The gain or loss line stays and does not hold."""
	built["action"] = "move"
	built["account"] = to_account
	built["touches"] = 1
	if from_currency and to_currency and from_currency != to_currency:
		problem = _restate_exchange_line(built, line, to_currency, company_currency)
		if problem:
			built["action"] = "keep"
			built["account"] = clean_text(line.get("account"))
			return built, problem, True
	return built, "", True


def _restate_exchange_line(built, line, to_currency, company_currency):
	"""Keep the company amount. A zero account-currency amount stays zero on a foreign account."""
	debit = _money(line.get("debit"))
	credit = _money(line.get("credit"))
	account_debit = _money(line.get("debit_in_account_currency"))
	account_credit = _money(line.get("credit_in_account_currency"))
	rate = _money(line.get("exchange_rate"), 9)
	built["restate"] = 1
	built["account_currency"] = to_currency
	if not account_debit and not account_credit:
		if to_currency == company_currency:
			built["exchange_rate"] = 1
			built["debit_in_account_currency"] = _show(debit)
			built["credit_in_account_currency"] = _show(credit)
			return ""
		built["exchange_rate"] = _show(rate)
		built["debit_in_account_currency"] = 0
		built["credit_in_account_currency"] = 0
		return ""
	if to_currency == company_currency:
		built["exchange_rate"] = 1
		built["debit_in_account_currency"] = _show(debit)
		built["credit_in_account_currency"] = _show(credit)
		return ""
	if not rate and (debit or credit):
		return "This exchange journal has no exchange rate, so its currency cannot change."
	built["exchange_rate"] = _show(rate)
	built["debit_in_account_currency"] = _show(account_debit)
	built["credit_in_account_currency"] = _show(account_credit)
	return ""


def _held_payment(source, name, payment_type, references, reason, bank_account, bank_amount, party_field):
	row = _payment_shell(source, name, payment_type, references, HELD, reason)
	row.update(
		{
			"mode": "",
			"bank_account": bank_account,
			"bank_amount": _show(bank_amount),
			"unallocated_amount": _show(_money(source.get("unallocated_amount"))),
			"advance_account": "",
			"party_account": "",
			"party_account_currency": "",
			"party_account_field": party_field,
			"party_currency_field": "",
			"rewrite_party": 0,
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


def _hold_connected(invoices, payments, journals):
	"""A held voucher holds the invoices it posts, and the other vouchers on those invoices."""
	by_invoice = {row["name"]: row for row in invoices}
	changed = True
	while changed:
		changed = False
		for payment in payments:
			names = _payment_invoice_names(payment, by_invoice)
			changed = _spread(payment, names, by_invoice, "payment") or changed
		for journal in journals:
			names = [
				line["reference_name"]
				for line in journal["lines"]
				if line.get("touches") and line["reference_name"] in by_invoice
			]
			changed = _spread(journal, names, by_invoice, "journal") or changed
		changed = _hold_exchange_pairs(payments, journals) or changed
	for payment in payments:
		if payment["action"] == HELD:
			for reference in payment["references"]:
				reference["qualifying"] = 0
	for journal in journals:
		if journal["action"] == HELD:
			for line in journal["lines"]:
				if line["action"] == "move":
					line["action"] = "keep"


def _spread(voucher, names, by_invoice, kind) -> bool:
	changed = False
	if voucher["action"] == HELD:
		for invoice_name in names:
			invoice = by_invoice[invoice_name]
			if invoice["action"] == STAY:
				continue
			if invoice["action"] != HELD:
				invoice["action"] = HELD
				invoice["to_account"] = invoice["from_account"]
				invoice["reason"] = f"Held by {voucher['name']}: {voucher['reason']}"
				changed = True
		return changed
	for invoice_name in names:
		invoice = by_invoice[invoice_name]
		if invoice["action"] == HELD:
			voucher["action"] = HELD
			voucher["mode"] = ""
			voucher["reason"] = f"Held because {invoice_name} stays on the current account."
			if kind == "payment":
				voucher["rewrite_party"] = 0
			return True
	return False


def _payment_invoice_names(payment, by_invoice):
	names = []
	for reference in payment["references"]:
		if reference.get("kind") == "invoice" and reference["reference_name"] in by_invoice:
			names.append(reference["reference_name"])
	return names


def _chains(invoices, payments, journals):
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
	payment_names = {row["name"] for row in payments}
	for row in invoices:
		find(("invoice", row["name"]))
		against = row.get("return_against")
		if against in invoice_names:
			union(("invoice", row["name"]), ("invoice", against))
	for payment in payments:
		find(("payment", payment["name"]))
		for reference in payment["references"]:
			if (
				reference.get("qualifying")
				and reference.get("kind") == "invoice"
				and reference["reference_name"] in invoice_names
			):
				union(("payment", payment["name"]), ("invoice", reference["reference_name"]))
	for journal in journals:
		find(("journal", journal["name"]))
		for line in journal["lines"]:
			reference_name = line.get("reference_name")
			if line.get("reference_type") == PAYMENT_ENTRY and reference_name in payment_names:
				union(("journal", journal["name"]), ("payment", reference_name))
			elif line.get("touches") and reference_name in invoice_names:
				union(("journal", journal["name"]), ("invoice", reference_name))
	groups = {}
	for node in list(parent):
		root = find(node)
		bucket = groups.setdefault(root, {"invoices": [], "payments": [], "journals": []})
		kind, node_name = node
		bucket[{"invoice": "invoices", "payment": "payments", "journal": "journals"}[kind]].append(node_name)
	chains = []
	for bucket in groups.values():
		bucket["invoices"] = sorted(set(bucket["invoices"]))
		bucket["payments"] = sorted(set(bucket["payments"]))
		bucket["journals"] = sorted(set(bucket["journals"]))
		if bucket["invoices"] or bucket["payments"] or bucket["journals"]:
			chains.append(bucket)
	chains.sort(key=lambda row: (row["invoices"][:1], row["payments"][:1], row["journals"][:1]))
	return chains


def _hold_exchange_pairs(payments, journals) -> bool:
	"""An exchange journal and the receipt it posts stay together when one of them is held."""
	changed = False
	by_payment = {row["name"]: row for row in payments}
	for journal in journals:
		if clean_text(journal.get("voucher_type")) not in EXCHANGE_VOUCHERS:
			continue
		names = [
			line["reference_name"]
			for line in journal["lines"]
			if line.get("reference_type") == PAYMENT_ENTRY and line.get("reference_name") in by_payment
		]
		if journal["action"] == HELD:
			for name in names:
				payment = by_payment[name]
				if payment["action"] != HELD:
					payment["action"] = HELD
					payment["mode"] = ""
					payment["rewrite_party"] = 0
					payment["reason"] = f"Held by {journal['name']}: {journal['reason']}"
					changed = True
			continue
		for name in names:
			payment = by_payment[name]
			if payment["action"] == HELD:
				journal["action"] = HELD
				journal["reason"] = f"Held because {name} stays on the current account."
				changed = True
				break
	return changed


def _mark_exchange_journals(payments, journals, doctype):
	"""Keep the existing exchange journal. Rebuilding the receipt must not book a second one."""
	by_payment = {row["name"]: row for row in payments}
	for journal in journals:
		if journal["action"] != MOVE or clean_text(journal.get("voucher_type")) not in EXCHANGE_VOUCHERS:
			continue
		payment_names = set()
		invoice_names = set()
		for line in journal["lines"]:
			if line.get("reference_type") == PAYMENT_ENTRY and line.get("reference_name"):
				payment_names.add(line["reference_name"])
			elif line.get("reference_type") == doctype and line.get("reference_name"):
				invoice_names.add(line["reference_name"])
		if not payment_names:
			for payment in payments:
				if payment["action"] != MOVE:
					continue
				if any(
					row.get("kind") == "invoice" and row.get("reference_name") in invoice_names
					for row in payment["references"]
				):
					payment_names.add(payment["name"])
		for name in payment_names:
			payment = by_payment.get(name)
			if payment and payment["action"] == MOVE:
				payment["keep_exchange_journal"] = 1


def _currency_change_allowed(invoice_currency, from_currency, to_currency, company_currency) -> bool:
	"""A currency change is the invoice currency on one side and the company currency on the other."""
	if not invoice_currency or not company_currency:
		return False
	allowed = {invoice_currency, company_currency}
	return from_currency in allowed and to_currency in allowed


def _restated_reference(reference, invoice, allocated, company_currency, source_currency, doctype, row_name):
	invoice_currency = clean_text(invoice.get("currency")).upper()
	invoice_amount = _invoice_allocation(reference, invoice, allocated, company_currency, source_currency)
	account_currency = clean_text(invoice.get("account_currency")).upper()
	account_amount = _account_amount(
		invoice_amount,
		invoice_currency,
		account_currency,
		invoice.get("conversion_rate"),
		company_currency,
	)
	payment_rate = _company_rate(
		allocated,
		invoice_amount,
		invoice_currency,
		source_currency,
		reference.get("exchange_rate"),
		invoice.get("conversion_rate"),
		company_currency,
	)
	return {
		"row_name": row_name,
		"reference_doctype": doctype,
		"reference_name": invoice["name"],
		"kind": "invoice",
		"qualifying": 1,
		"account": invoice["to_account"],
		"account_currency": account_currency,
		"invoice_currency": invoice_currency,
		"invoice_amount": _show(invoice_amount),
		"allocated_amount": _show(account_amount),
		"exchange_rate": _show(payment_rate),
		"payment_rate": _show(payment_rate),
		"restate": 1,
	}


def _currency_header(source, payment_type, references, company_currency):
	"""One exchange rate keeps the company-currency party amount equal to the submitted base."""
	currency = references[0]["account_currency"]
	party_amount = _money(
		sum(
			(_money(row["allocated_amount"]) for row in references if row.get("kind") == "invoice"),
			Decimal(0),
		)
	)
	base = _party_base(source, payment_type)
	if not base:
		base = _money(
			sum(
				(
					_money(row.get("invoice_amount"))
					* (
						_money(row.get("payment_rate") or row.get("exchange_rate"), 9)
						if row.get("invoice_currency") != company_currency
						else Decimal(1)
					)
					for row in references
					if row.get("restate")
				),
				Decimal(0),
			)
		)
	if currency == company_currency or not party_amount:
		rate = Decimal(1)
	else:
		rate = _money(base / party_amount, 9) or Decimal(1)
	shown = _show(rate)
	for row in references:
		if row.get("restate"):
			row["exchange_rate"] = shown
			row["payment_rate"] = shown
	amount_field, rate_field = _amount_fields(payment_type)
	return {
		"party_account_currency": currency,
		"party_amount": _show(party_amount),
		"party_exchange_rate": shown,
		"base_party_amount": _show(base if currency != company_currency else party_amount),
		"party_amount_field": amount_field,
		"party_rate_field": rate_field,
		"restate": 1,
	}


def _restate_journal_line(built, line, invoice, to_currency, company_currency):
	debit = _money(line.get("debit"))
	credit = _money(line.get("credit"))
	if to_currency == company_currency:
		rate = Decimal(1)
	else:
		rate = _money(invoice.get("conversion_rate"), 9)
		if not rate:
			return f"{invoice['name']} has no conversion rate, so the journal amount cannot change currency."
	built["restate"] = 1
	built["account_currency"] = to_currency
	built["exchange_rate"] = _show(rate)
	built["debit_in_account_currency"] = _show(_money(debit / rate))
	built["credit_in_account_currency"] = _show(_money(credit / rate))
	return ""


def _invoice_allocation(reference, invoice, allocated, company_currency, source_currency):
	hero = _stored_allocation(reference.get("hero_allocated_invoice_amount"))
	if hero is not None:
		return hero
	invoice_currency = clean_text(invoice.get("currency")).upper()
	account_currency = clean_text(source_currency).upper()
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


def _company_rate(
	allocated,
	invoice_amount,
	invoice_currency,
	source_currency,
	exchange_rate,
	conversion_rate,
	company_currency,
):
	"""Company currency for one unit of the invoice currency.

	A company-currency account stores the allocation in company currency, so the
	rate is that amount divided by the invoice amount. A foreign account already
	stores the invoice amount, and dividing it by itself would book 1.
	"""
	if not invoice_currency or invoice_currency == company_currency or not invoice_amount:
		return Decimal(1)
	if source_currency == company_currency:
		return _money(allocated / invoice_amount, 9) or Decimal(1)
	booked = _money(exchange_rate, 9)
	conversion = _money(conversion_rate, 9)
	if booked and booked != 1:
		return booked
	return conversion or booked or Decimal(1)


def _stored_allocation(value):
	if value in (None, "", False):
		return None
	if isinstance(value, str) and not value.strip():
		return None
	amount = _money(value)
	if amount == 0:
		return None
	return amount


def _account_amount(invoice_amount, invoice_currency, account_currency, conversion_rate, company_currency):
	if account_currency == invoice_currency:
		return invoice_amount
	if account_currency == company_currency:
		rate = (
			Decimal(1) if invoice_currency == company_currency else _money(conversion_rate, 9) or Decimal(1)
		)
		return _money(invoice_amount * rate)
	return invoice_amount


def _amount_fields(payment_type):
	if payment_type == "Pay":
		return "received_amount", "target_exchange_rate"
	return "paid_amount", "source_exchange_rate"


def _party_base(source, payment_type):
	if payment_type == "Pay":
		return _money(source.get("base_received_amount"))
	return _money(source.get("base_paid_amount"))


def _party_fields(source, payment_type):
	if payment_type == "Pay":
		return (
			clean_text(source.get("paid_to")),
			clean_text(source.get("paid_to_account_currency")).upper(),
			"paid_to",
			"paid_to_account_currency",
		)
	return (
		clean_text(source.get("paid_from")),
		clean_text(source.get("paid_from_account_currency")).upper(),
		"paid_from",
		"paid_from_account_currency",
	)


def _bank(source, payment_type):
	if payment_type == "Pay":
		return clean_text(source.get("paid_from")), _money(source.get("paid_amount"))
	return clean_text(source.get("paid_to")), _money(source.get("received_amount"))


def _invoice_action(reference, invoices, doctype):
	if clean_text((reference or {}).get("reference_doctype") or doctype) != doctype:
		return ""
	invoice = invoices.get(clean_text((reference or {}).get("reference_name")))
	return invoice.get("action") if invoice else ""


def _allocated(reference) -> Decimal:
	return _money((reference or {}).get("allocated_amount"))


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
