# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Move submitted invoices from one receivable or payable to another.

Pure functions. The desk page calls these, and the tests run without a site.
The destination uses the same currency, so amounts stay as submitted. Receipts
and journals that post the invoice move with it. Nothing here cancels a document.
"""

from decimal import ROUND_HALF_UP, Decimal

from frappehero.flags import clean_text

SALES_INVOICE = "Sales Invoice"
PURCHASE_INVOICE = "Purchase Invoice"
RECEIVABLE = "receivable"
PAYABLE = "payable"
MOVE = "move"
HELD = "held"
SINGLE = "single"
MULTI = "multi"
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


class PartyReclassError(ValueError):
	"""The accounts cannot be used for this reclass."""


def side_choice(value) -> dict:
	"""Receivable moves sales invoices. Payable moves purchase invoices."""
	key = clean_text(value).lower()
	if key not in _SIDES:
		raise PartyReclassError("Choose Receivable or Payable.")
	return {"name": key, **_SIDES[key]}


def check_accounts(company, side, from_account, to_account, accounts) -> str:
	"""Both ledgers must be the same currency and the account type of this side.

	Returns the shared account currency.
	"""
	chosen = side_choice(side)
	company = clean_text(company)
	from_account = clean_text(from_account)
	to_account = clean_text(to_account)
	errors = []
	if not company:
		errors.append("Choose a company.")
	if not from_account:
		errors.append("Choose the account to leave.")
	if not to_account:
		errors.append("Choose the account to use.")
	if from_account and from_account == to_account:
		errors.append("The account to leave and the account to use are the same.")
	currency = _account_error(
		errors, accounts, from_account, company, chosen["account_type"], "The account to leave"
	)
	other = _account_error(
		errors, accounts, to_account, company, chosen["account_type"], "The account to use"
	)
	if currency and other and currency != other:
		errors.append(
			f"The account to use is in {other}, and the account to leave is in {currency}. "
			"A reclass keeps the currency."
		)
	if errors:
		raise PartyReclassError(" ".join(errors))
	return currency


def plan_reclass(company, side, from_account, to_account, invoices, payments, journals) -> dict:
	"""Plan the move. A held voucher keeps its invoices on the current account."""
	chosen = side_choice(side)
	company = clean_text(company)
	from_account = clean_text(from_account)
	to_account = clean_text(to_account)
	invoice_rows = []
	by_name = {}
	for source in invoices or []:
		row = _invoice_row(source, chosen, company, from_account, to_account)
		if row is None:
			context = _context_invoice(source, chosen, company)
			if context and context["name"] not in by_name:
				by_name[context["name"]] = context
			continue
		invoice_rows.append(row)
		by_name[row["name"]] = row

	payment_rows = []
	for source in payments or []:
		row = _payment_row(source, company, by_name, from_account, to_account, chosen["doctype"])
		if row is not None:
			payment_rows.append(row)

	journal_rows = []
	for source in journals or []:
		row = _journal_row(source, company, by_name, from_account, to_account, chosen["doctype"])
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
	return {
		"company": company,
		"side": chosen["name"],
		"doctype": chosen["doctype"],
		"account_field": chosen["account_field"],
		"from_account": from_account,
		"to_account": to_account,
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


def _invoice_row(source, chosen, company, from_account, to_account):
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
	return {
		"name": name,
		"doctype": chosen["doctype"],
		"account_field": chosen["account_field"],
		"party": clean_text(source.get("party")),
		"currency": clean_text(source.get("currency")).upper(),
		"posting_date": clean_text(source.get("posting_date")),
		"outstanding_amount": _show(_money(source.get("outstanding_amount"))),
		"from_account": from_account,
		"to_account": to_account,
		"account_currency": clean_text(source.get("party_account_currency")).upper(),
		"is_return": 1 if int(source.get("is_return") or 0) else 0,
		"return_against": clean_text(source.get("return_against")),
		"action": MOVE,
		"reason": "",
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


def _payment_row(source, company, invoices, from_account, to_account, doctype):
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
	for reference in source.get("references") or []:
		if _allocated(reference) and _invoice_action(reference, invoices, doctype) in (MOVE, HELD):
			touches = True
		built, problem = _reference_row(reference, invoices, doctype, from_account, to_account, party_account)
		if problem and not reason:
			reason = problem
		if built is not None:
			references.append(built)
	if not touches:
		return None
	if not reason and any(row["kind"] == "other" for row in references):
		targets = {row["account"] for row in references if row["kind"] == "invoice" and row.get("account")}
		if len(targets) > 1:
			reason = "This payment allocates another document, so it cannot be split across accounts."
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
	if len(targets) > 1:
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
		rewrite = 0
	else:
		mode = SINGLE
		new_account = to_account if to_account in targets else party_account
		advance_account = ""
		rewrite = 1 if party_account != new_account else 0
		for reference in references:
			if reference["kind"] == "other":
				reference["account"] = new_account
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
		}
	)
	return row


def _reference_row(reference, invoices, doctype, from_account, to_account, party_account):
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
	elif invoice.get("action") == HELD:
		account = from_account
	else:
		account = clean_text(invoice.get("account"))
	return (
		{
			"row_name": row_name,
			"reference_doctype": doctype,
			"reference_name": ref_name,
			"kind": "invoice",
			"qualifying": 1 if invoice.get("action") in (MOVE, HELD) else 0,
			"account": account,
			"allocated_amount": _show(allocated),
		},
		"",
	)


def _journal_row(source, company, invoices, from_account, to_account, doctype):
	source = source or {}
	name = clean_text(source.get("name"))
	if not name or clean_text(source.get("company")) != company:
		return None
	if _status(source.get("docstatus")) != 1:
		return None
	lines = []
	reason = ""
	touches = False
	for line in source.get("lines") or []:
		built, problem, touched = _journal_line(line, invoices, doctype, from_account, to_account)
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
		"voucher_type": clean_text(source.get("voucher_type")),
		"action": HELD if reason else MOVE,
		"reason": reason,
		"debit_total": _show(debit),
		"lines": lines,
		"chain": None,
	}


def _journal_line(line, invoices, doctype, from_account, to_account):
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
	if ref_type != doctype or ref_name not in invoices:
		return built, "", False
	invoice = invoices[ref_name]
	if invoice.get("action") not in (MOVE, HELD):
		return built, "", False
	built["touches"] = 1
	if invoice.get("action") != MOVE:
		return built, "", True
	if account == from_account:
		built["action"] = "move"
		built["account"] = to_account
		return built, "", True
	if account == to_account:
		return built, "", True
	return built, f"This journal posts {ref_name} to {account or 'no account'}, not {from_account}.", True


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
			if line.get("touches") and line["reference_name"] in invoice_names:
				union(("journal", journal["name"]), ("invoice", line["reference_name"]))
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
