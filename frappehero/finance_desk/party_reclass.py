# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Move submitted invoices onto another receivable or payable without cancelling them.

The account is written onto the submitted invoice, onto the receipts and
journals that post it, and then each voucher's ledger is rebuilt. Amounts,
outstanding balances, and bank amounts stay as they are.
"""

import frappe
from frappe import _
from frappe.utils import flt

from frappehero.finance_desk.party_reclass_logic import (
	MOVE,
	MULTI,
	SINGLE,
	PartyReclassError,
	check_accounts,
	plan_reclass,
	selection_matches,
	side_choice,
)
from frappehero.flags import clean_text, parse_payload

_INVOICE_FIELDS = [
	"name",
	"company",
	"docstatus",
	"currency",
	"outstanding_amount",
	"party_account_currency",
	"posting_date",
	"is_return",
	"return_against",
]
_PAYMENT_FIELDS = [
	"name",
	"company",
	"docstatus",
	"payment_type",
	"party",
	"paid_from",
	"paid_to",
	"paid_from_account_currency",
	"paid_to_account_currency",
	"paid_amount",
	"received_amount",
	"unallocated_amount",
	"posting_date",
]


def preview_reclass(company, side, from_account, to_account) -> dict:
	company, side_name, from_account, to_account, currency = _checked(company, side, from_account, to_account)
	plan = _plan(company, side_name, from_account, to_account)
	blocked = _block_reason(company, plan)
	needs_multi = any(row["mode"] == MULTI and row["action"] == MOVE for row in plan["payments"])
	return {
		"company": company,
		"side": side_name,
		"doctype": plan["doctype"],
		"account_currency": currency,
		"from_account": from_account,
		"to_account": to_account,
		"blocked": blocked,
		"invoices": plan["invoices"],
		"payments": plan["payments"],
		"journals": plan["journals"],
		"chains": plan["chains"],
		"signature": plan["signature"],
		"counts": plan["counts"],
		"multi_ready": _multi_ready() or not needs_multi,
	}


def apply_reclass(company, side, from_account, to_account, expected) -> dict:
	company, side_name, from_account, to_account, currency = _checked(company, side, from_account, to_account)
	plan = _plan(company, side_name, from_account, to_account)
	blocked = _block_reason(company, plan)
	if blocked:
		frappe.throw(blocked, title=_("Books are closed"))
	expected = parse_payload(expected, {})
	if not selection_matches(expected, plan):
		frappe.throw(_("Preview this selection again before applying it."), title=_("Preview again"))
	if any(row["mode"] == MULTI and row["action"] == MOVE for row in plan["payments"]) and not _multi_ready():
		frappe.throw(
			_("Migrate Frappe Hero before reclassing a payment that uses more than one account."),
			title=_("Migrate first"),
		)
	results = []
	for index, chain in enumerate(plan["chains"]):
		savepoint = f"party_reclass_{index}"
		frappe.db.savepoint(savepoint)
		try:
			_apply_chain(plan, chain, currency)
			mismatch = _mismatch(plan, chain)
			if mismatch:
				_rollback(savepoint)
				results.append(_chain_result(chain, "rolled_back", mismatch))
				continue
			frappe.db.commit()
			results.append(_chain_result(chain, "applied", ""))
		except Exception as exc:
			_rollback(savepoint)
			frappe.log_error(title="Party reclass", message=frappe.get_traceback())
			results.append(
				_chain_result(chain, "rolled_back", clean_text(exc) or _("This chain could not be rebuilt."))
			)
	return {
		"applied_invoices": sum(len(row["invoices"]) for row in results if row["status"] == "applied"),
		"applied_payments": sum(len(row["payments"]) for row in results if row["status"] == "applied"),
		"applied_journals": sum(len(row["journals"]) for row in results if row["status"] == "applied"),
		"chains": results,
	}


def _plan(company, side_name, from_account, to_account):
	chosen = side_choice(side_name)
	invoices = _load_invoices(company, chosen, from_account)
	names = [row["name"] for row in invoices]
	payments = _load_payments(company, chosen["doctype"], names)
	known = set(names)
	extra = []
	for payment in payments:
		for reference in payment.get("references") or []:
			ref_name = clean_text(reference.get("reference_name"))
			if clean_text(reference.get("reference_doctype")) == chosen["doctype"] and ref_name not in known:
				extra.append(ref_name)
				known.add(ref_name)
	if extra:
		invoices.extend(_load_named_invoices(chosen, extra))
	journals = _load_journals(company, chosen["doctype"], [row["name"] for row in invoices])
	return plan_reclass(company, side_name, from_account, to_account, invoices, payments, journals)


def _checked(company, side, from_account, to_account):
	company = clean_text(company)
	from_account = clean_text(from_account)
	to_account = clean_text(to_account)
	try:
		chosen = side_choice(side)
	except PartyReclassError as exc:
		frappe.throw(str(exc), title=_("Check the accounts"))
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Choose a company."))
	accounts = _account_map([from_account, to_account])
	try:
		currency = check_accounts(company, chosen["name"], from_account, to_account, accounts)
	except PartyReclassError as exc:
		frappe.throw(str(exc), title=_("Check the accounts"))
	return company, chosen["name"], from_account, to_account, currency


def _account_map(names):
	names = [name for name in names if name]
	if not names:
		return {}
	rows = frappe.get_all(
		"Account",
		filters={"name": ["in", names]},
		fields=["name", "company", "account_type", "account_currency", "is_group"],
		limit_page_length=0,
	)
	return {row.name: row for row in rows}


def _load_invoices(company, chosen, from_account):
	party_field = chosen["party_type"].lower()
	rows = frappe.get_all(
		chosen["doctype"],
		filters={"company": company, "docstatus": 1, chosen["account_field"]: from_account},
		fields=[*_INVOICE_FIELDS, chosen["account_field"], party_field],
		limit_page_length=0,
	)
	return [_shaped_invoice(row, chosen) for row in rows]


def _load_named_invoices(chosen, names):
	if not names:
		return []
	party_field = chosen["party_type"].lower()
	rows = frappe.get_all(
		chosen["doctype"],
		filters={"name": ["in", names]},
		fields=[*_INVOICE_FIELDS, chosen["account_field"], party_field],
		limit_page_length=0,
	)
	return [_shaped_invoice(row, chosen) for row in rows]


def _shaped_invoice(row, chosen):
	payload = dict(row)
	payload["doctype"] = chosen["doctype"]
	payload["account"] = row.get(chosen["account_field"])
	payload["party"] = row.get(chosen["party_type"].lower())
	return payload


def _load_payments(company, doctype, invoice_names):
	if not invoice_names:
		return []
	reference_fields = ["name", "parent", "reference_doctype", "reference_name", "allocated_amount"]
	meta = frappe.get_meta("Payment Entry Reference")
	if meta.has_field("account"):
		reference_fields.append("account")
	links = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"parenttype": "Payment Entry",
			"reference_doctype": doctype,
			"reference_name": ["in", invoice_names],
		},
		fields=["parent"],
		limit_page_length=0,
	)
	parents = sorted({row.parent for row in links if row.parent})
	if not parents:
		return []
	headers = frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", parents], "company": company, "docstatus": 1},
		fields=_PAYMENT_FIELDS,
		limit_page_length=0,
	)
	if not headers:
		return []
	names = [row.name for row in headers]
	references = frappe.get_all(
		"Payment Entry Reference",
		filters={"parenttype": "Payment Entry", "parent": ["in", names]},
		fields=[*reference_fields, "parent"],
		limit_page_length=0,
	)
	taxes = set()
	if frappe.db.table_exists("Advance Taxes and Charges"):
		taxes = set(
			frappe.get_all(
				"Advance Taxes and Charges",
				filters={"parenttype": "Payment Entry", "parent": ["in", names]},
				pluck="parent",
			)
		)
	deductions = set()
	if frappe.db.table_exists("Payment Entry Deduction"):
		for row in frappe.get_all(
			"Payment Entry Deduction",
			filters={"parent": ["in", names]},
			fields=["parent", "is_exchange_gain_loss"],
			limit_page_length=0,
		):
			if not row.is_exchange_gain_loss:
				deductions.add(row.parent)
	grouped = {}
	for reference in references:
		payload = dict(reference)
		payload["row_name"] = reference.name
		grouped.setdefault(reference.parent, []).append(payload)
	payments = []
	for header in headers:
		payment = dict(header)
		payment["references"] = grouped.get(header.name, [])
		payment["has_taxes"] = 1 if header.name in taxes else 0
		payment["has_deductions"] = 1 if header.name in deductions else 0
		payments.append(payment)
	return payments


def _load_journals(company, doctype, invoice_names):
	if not invoice_names or not frappe.db.table_exists("Journal Entry Account"):
		return []
	links = frappe.get_all(
		"Journal Entry Account",
		filters={
			"parenttype": "Journal Entry",
			"reference_type": doctype,
			"reference_name": ["in", invoice_names],
		},
		fields=["parent"],
		limit_page_length=0,
	)
	parents = sorted({row.parent for row in links if row.parent})
	if not parents:
		return []
	headers = frappe.get_all(
		"Journal Entry",
		filters={"name": ["in", parents], "company": company, "docstatus": 1},
		fields=["name", "company", "docstatus", "posting_date", "voucher_type"],
		limit_page_length=0,
	)
	if not headers:
		return []
	names = [row.name for row in headers]
	lines = frappe.get_all(
		"Journal Entry Account",
		filters={"parenttype": "Journal Entry", "parent": ["in", names]},
		fields=["name", "parent", "account", "reference_type", "reference_name", "debit", "credit"],
		limit_page_length=0,
	)
	grouped = {}
	for line in lines:
		payload = dict(line)
		payload["row_name"] = line.name
		grouped.setdefault(line.parent, []).append(payload)
	journals = []
	for header in headers:
		journal = dict(header)
		journal["lines"] = grouped.get(header.name, [])
		journals.append(journal)
	return journals


def _block_reason(company, plan) -> str:
	dates = []
	for key in ("invoices", "payments", "journals"):
		for row in plan[key]:
			if row["action"] == MOVE and row.get("posting_date"):
				dates.append(str(row["posting_date"]))
	if not dates:
		return ""
	messages = []
	if frappe.db.exists("DocType", "Period Closing Voucher"):
		latest = frappe.get_all(
			"Period Closing Voucher",
			filters={"company": company, "docstatus": 1},
			fields=["name", "period_end_date"],
			order_by="period_end_date desc",
			limit=1,
		)
		if (
			latest
			and latest[0].period_end_date
			and any(date <= str(latest[0].period_end_date) for date in dates)
		):
			messages.append(
				_(
					"Period Closing Voucher {0} closes the books through {1}. Cancel that voucher before this reclass, then create it again."
				).format(latest[0].name, latest[0].period_end_date)
			)
	if frappe.db.exists("DocType", "Accounts Settings") and frappe.get_meta("Accounts Settings").has_field(
		"acc_frozen_upto"
	):
		frozen = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
		if frozen and any(date <= str(frozen) for date in dates):
			messages.append(_("Accounts are frozen through {0}.").format(frozen))
	return " ".join(messages)


def _apply_chain(plan, chain, currency):
	invoices = [row for row in plan["invoices"] if row["name"] in set(chain["invoices"])]
	payments = [row for row in plan["payments"] if row["name"] in set(chain["payments"])]
	journals = [row for row in plan["journals"] if row["name"] in set(chain["journals"])]
	for invoice in _invoice_order(invoices):
		frappe.db.set_value(
			invoice["doctype"],
			invoice["name"],
			{invoice["account_field"]: invoice["to_account"], "party_account_currency": currency},
			update_modified=True,
		)
	for payment in payments:
		_write_payment(payment, currency)
	for journal in journals:
		_write_journal(journal)
	for invoice in _invoice_order(invoices):
		_rebuild(invoice["doctype"], invoice["name"], from_repost=True)
	for payment in payments:
		_rebuild_payment(payment)
	for journal in journals:
		_rebuild("Journal Entry", journal["name"], from_repost=False)


def _write_payment(payment, currency):
	values = {}
	if payment.get("rewrite_party") and payment.get("party_account_field"):
		values[payment["party_account_field"]] = payment["party_account"]
		if payment.get("party_currency_field"):
			values[payment["party_currency_field"]] = currency
	if frappe.get_meta("Payment Entry").has_field("hero_multi_account"):
		values["hero_multi_account"] = 1 if payment["mode"] == MULTI else 0
	if values:
		frappe.db.set_value("Payment Entry", payment["name"], values, update_modified=True)
	for reference in payment["references"]:
		_write_reference(reference)
	if payment["mode"] == SINGLE and payment.get("party_account"):
		_align_single_references(payment["name"], payment["party_account"])


def _write_reference(reference):
	if not reference.get("row_name") or not reference.get("account"):
		return
	meta = frappe.get_meta("Payment Entry Reference")
	values = {}
	if meta.has_field("account"):
		values["account"] = reference["account"]
	if meta.has_field("hero_account"):
		values["hero_account"] = reference["account"]
	if values:
		frappe.db.set_value("Payment Entry Reference", reference["row_name"], values, update_modified=True)


def _align_single_references(payment_name, account):
	"""A one-account receipt posts every row to the party account, including rows with no allocation."""
	meta = frappe.get_meta("Payment Entry Reference")
	values = {}
	if meta.has_field("account"):
		values["account"] = account
	if meta.has_field("hero_account"):
		values["hero_account"] = account
	if not values:
		return
	names = frappe.get_all(
		"Payment Entry Reference",
		filters={"parenttype": "Payment Entry", "parent": payment_name},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Payment Entry Reference", name, values, update_modified=True)


def _write_journal(journal):
	for line in journal["lines"]:
		if line["action"] != "move" or not line.get("row_name"):
			continue
		frappe.db.set_value(
			"Journal Entry Account",
			line["row_name"],
			{"account": line["account"]},
			update_modified=True,
		)


def _rebuild(doctype, name, from_repost):
	_clear_ledger(doctype, name)
	doc = frappe.get_doc(doctype, name)
	doc.flags.ignore_permissions = True
	if from_repost:
		doc.make_gl_entries(from_repost=True)
	else:
		doc.make_gl_entries()


def _rebuild_payment(payment):
	_clear_ledger("Payment Entry", payment["name"])
	doc = frappe.get_doc("Payment Entry", payment["name"])
	doc.flags.ignore_permissions = True
	if payment["mode"] == MULTI and payment.get("advance_account"):
		doc.flags.hero_repair_advance_account = payment["advance_account"]
	doc.make_gl_entries()


def _clear_ledger(voucher_type, voucher_no):
	frappe.db.delete("GL Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no})
	if frappe.db.table_exists("Payment Ledger Entry"):
		frappe.db.delete("Payment Ledger Entry", {"voucher_type": voucher_type, "voucher_no": voucher_no})


def _invoice_order(invoices):
	names = {row["name"] for row in invoices}
	originals = [row for row in invoices if row.get("return_against") not in names]
	notes = [row for row in invoices if row.get("return_against") in names]
	return originals + notes


def _mismatch(plan, chain) -> str:
	invoices = {row["name"]: row for row in plan["invoices"]}
	payments = {row["name"]: row for row in plan["payments"]}
	journals = {row["name"]: row for row in plan["journals"]}
	for name in chain["invoices"]:
		invoice = invoices[name]
		current = flt(frappe.db.get_value(invoice["doctype"], name, "outstanding_amount"))
		expected = flt(invoice["outstanding_amount"])
		if abs(current - expected) > 0.01:
			return _("Outstanding on {0} would change from {1} to {2}.").format(name, expected, current)
	for name in chain["payments"]:
		current = _bank_amount(name)
		expected = flt(payments[name]["bank_amount"])
		if abs(current - expected) > 0.01:
			return _("Bank amount on {0} would change from {1} to {2}.").format(name, expected, current)
	for name in chain["journals"]:
		current = _journal_debit(name)
		expected = flt(journals[name]["debit_total"])
		if abs(current - expected) > 0.01:
			return _("Journal {0} debit total would change from {1} to {2}.").format(name, expected, current)
	return ""


def _bank_amount(name) -> float:
	row = frappe.db.get_value(
		"Payment Entry", name, ["payment_type", "paid_amount", "received_amount"], as_dict=True
	)
	if not row:
		return 0
	if row.payment_type == "Pay":
		return flt(row.paid_amount)
	return flt(row.received_amount)


def _journal_debit(name) -> float:
	total = 0
	for debit in frappe.get_all("Journal Entry Account", filters={"parent": name}, pluck="debit"):
		total += flt(debit)
	return total


def _multi_ready() -> bool:
	if not frappe.db.exists("DocType", "Payment Entry Reference"):
		return False
	reference_meta = frappe.get_meta("Payment Entry Reference")
	payment_meta = frappe.get_meta("Payment Entry")
	return reference_meta.has_field("hero_account") and payment_meta.has_field("hero_multi_account")


def _chain_result(chain, status, reason):
	return {
		"invoices": list(chain["invoices"]),
		"payments": list(chain["payments"]),
		"journals": list(chain["journals"]),
		"status": status,
		"reason": reason,
	}


def _rollback(savepoint):
	frappe.db.rollback(save_point=savepoint)
