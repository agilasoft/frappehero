# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Move submitted sales invoices off the wrong receivable without cancelling them.

The receivable is written onto the submitted document, then that voucher's
General Ledger and Payment Ledger are rebuilt from the document. Invoice
names, posting dates, and receipt names stay as they are.
"""

import frappe
from frappe import _
from frappe.utils import flt

from frappehero.finance_desk.receivable_repair_logic import (
	MOVE,
	MULTI,
	ReceivableRepairError,
	check_accounts,
	outstanding_matches,
	party_account_choice,
	plan_repair,
	selection_matches,
)
from frappehero.flags import clean_text, parse_payload

_INVOICE_FIELDS = [
	"name",
	"company",
	"docstatus",
	"currency",
	"debit_to",
	"outstanding_amount",
	"conversion_rate",
	"party_account_currency",
	"customer",
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
	"party_type",
	"paid_from",
	"paid_to",
	"paid_from_account_currency",
	"paid_to_account_currency",
	"paid_amount",
	"received_amount",
	"base_paid_amount",
	"base_received_amount",
	"source_exchange_rate",
	"target_exchange_rate",
	"unallocated_amount",
	"posting_date",
]
_HEADER_FIELDS = [
	"paid_from",
	"paid_to",
	"paid_from_account_currency",
	"paid_to_account_currency",
	"source_exchange_rate",
	"target_exchange_rate",
	"paid_amount",
	"received_amount",
	"base_paid_amount",
	"base_received_amount",
	"paid_amount_after_tax",
	"received_amount_after_tax",
	"base_paid_amount_after_tax",
	"base_received_amount_after_tax",
	"difference_amount",
	"total_allocated_amount",
	"base_total_allocated_amount",
	"unallocated_amount",
	"hero_multi_account",
]
_REFERENCE_FIELDS = [
	"allocated_amount",
	"exchange_rate",
	"exchange_gain_loss",
	"outstanding_amount",
	"hero_account",
	"hero_account_currency",
	"hero_invoice_currency",
	"hero_allocated_invoice_amount",
	"hero_allocated_account_amount",
	"hero_booked_rate",
	"hero_payment_rate",
	"hero_payment_currency",
	"hero_bank_amount",
]


def preview_repair(company, wrong_account, usd_account, other_account) -> dict:
	company, wrong_account, usd_account, other_account, company_currency, _accounts = _checked(
		company, wrong_account, usd_account, other_account
	)
	plan = _plan(company, wrong_account, usd_account, other_account, company_currency)
	blocked = _block_reason(company, plan)
	return {
		"company": company,
		"company_currency": company_currency,
		"wrong_account": wrong_account,
		"usd_account": usd_account,
		"other_account": other_account,
		"blocked": blocked,
		"invoices": plan["invoices"],
		"payments": plan["payments"],
		"chains": plan["chains"],
		"signature": plan["signature"],
		"counts": plan["counts"],
		"defaults": _default_plan(company, wrong_account, usd_account, other_account),
		"multi_ready": _multi_ready()
		or not any(row["mode"] == MULTI and row["action"] == MOVE for row in plan["payments"]),
	}


def apply_repair(company, wrong_account, usd_account, other_account, expected) -> dict:
	company, wrong_account, usd_account, other_account, company_currency, _accounts = _checked(
		company, wrong_account, usd_account, other_account
	)
	plan = _plan(company, wrong_account, usd_account, other_account, company_currency)
	blocked = _block_reason(company, plan)
	if blocked:
		frappe.throw(blocked, title=_("Books are closed"))
	expected = parse_payload(expected, {})
	if not selection_matches(expected, plan):
		frappe.throw(_("Preview this selection again before applying it."), title=_("Preview again"))
	if any(row["mode"] == MULTI and row["action"] == MOVE for row in plan["payments"]) and not _multi_ready():
		frappe.throw(
			_("Migrate Frappe Hero before repairing a receipt that uses more than one receivable."),
			title=_("Migrate first"),
		)
	results = []
	for index, chain in enumerate(plan["chains"]):
		savepoint = f"receivable_repair_{index}"
		frappe.db.savepoint(savepoint)
		try:
			_apply_chain(plan, chain)
			mismatch = _mismatch(plan, chain)
			if mismatch:
				_rollback(savepoint)
				results.append(_chain_result(chain, "rolled_back", mismatch))
				continue
			frappe.db.commit()
			results.append(_chain_result(chain, "applied", ""))
		except Exception as exc:
			_rollback(savepoint)
			frappe.log_error(title="Receivable repair", message=frappe.get_traceback())
			results.append(
				_chain_result(chain, "rolled_back", clean_text(exc) or _("This chain could not be rebuilt."))
			)
	return {
		"applied_invoices": sum(len(row["invoices"]) for row in results if row["status"] == "applied"),
		"applied_payments": sum(len(row["payments"]) for row in results if row["status"] == "applied"),
		"chains": results,
	}


def preview_defaults(company, wrong_account, usd_account, other_account) -> dict:
	company, wrong_account, usd_account, other_account, _currency, _accounts = _checked(
		company, wrong_account, usd_account, other_account
	)
	return _default_plan(company, wrong_account, usd_account, other_account)


def apply_defaults(company, wrong_account, usd_account, other_account) -> dict:
	company, wrong_account, usd_account, other_account, _currency, _accounts = _checked(
		company, wrong_account, usd_account, other_account
	)
	plan = _default_plan(company, wrong_account, usd_account, other_account)
	frappe.db.set_value(
		"Company", company, "default_receivable_account", plan["company_default"], update_modified=True
	)
	for row in plan["parties"]:
		frappe.db.set_value("Party Account", row["row"], "account", row["account"], update_modified=True)
	return plan


def _plan(company, wrong_account, usd_account, other_account, company_currency):
	invoices = _load_invoices(company, wrong_account)
	payments = _load_payments(company, [row["name"] for row in invoices])
	known = {row["name"] for row in invoices}
	extra_names = []
	for payment in payments:
		for reference in payment.get("references") or []:
			if (
				reference.get("reference_doctype") == "Sales Invoice"
				and reference.get("reference_name") not in known
			):
				extra_names.append(reference["reference_name"])
				known.add(reference["reference_name"])
	if extra_names:
		invoices.extend(_load_named_invoices(extra_names))
	return plan_repair(
		company,
		wrong_account,
		usd_account,
		other_account,
		company_currency,
		invoices,
		payments,
	)


def _checked(company, wrong_account, usd_account, other_account):
	company = clean_text(company)
	wrong_account = clean_text(wrong_account)
	usd_account = clean_text(usd_account)
	other_account = clean_text(other_account)
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Choose a company."))
	company_currency = clean_text(frappe.db.get_value("Company", company, "default_currency"))
	accounts = _account_map([wrong_account, usd_account, other_account])
	try:
		check_accounts(company, company_currency, wrong_account, usd_account, other_account, accounts)
	except ReceivableRepairError as exc:
		frappe.throw(str(exc), title=_("Check the accounts"))
	return company, wrong_account, usd_account, other_account, company_currency, accounts


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


def _load_invoices(company, wrong_account):
	return frappe.get_all(
		"Sales Invoice",
		filters={"company": company, "docstatus": 1, "debit_to": wrong_account},
		fields=_INVOICE_FIELDS,
		limit_page_length=0,
	)


def _load_named_invoices(names):
	if not names:
		return []
	return frappe.get_all(
		"Sales Invoice",
		filters={"name": ["in", names]},
		fields=_INVOICE_FIELDS,
		limit_page_length=0,
	)


def _load_payments(company, invoice_names):
	if not invoice_names:
		return []
	reference_fields = [
		"name",
		"parent",
		"reference_doctype",
		"reference_name",
		"allocated_amount",
		"exchange_rate",
	]
	meta = frappe.get_meta("Payment Entry Reference")
	for field in ("hero_allocated_invoice_amount", "hero_account", "hero_invoice_currency"):
		if meta.has_field(field):
			reference_fields.append(field)
	links = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"parenttype": "Payment Entry",
			"reference_doctype": "Sales Invoice",
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


def _default_plan(company, wrong_account, usd_account, other_account):
	rows = []
	if frappe.db.table_exists("Party Account"):
		rows = frappe.get_all(
			"Party Account",
			filters={
				"company": company,
				"account": wrong_account,
				"parenttype": ["in", ["Customer", "Customer Group"]],
			},
			fields=["name", "parent", "parenttype"],
			limit_page_length=0,
		)
	customers = [row.parent for row in rows if row.parenttype == "Customer"]
	currencies = {}
	if customers:
		for invoice in frappe.get_all(
			"Sales Invoice",
			filters={
				"company": company,
				"docstatus": 1,
				"customer": ["in", customers],
				"outstanding_amount": ["!=", 0],
			},
			fields=["customer", "currency"],
			limit_page_length=0,
		):
			currencies.setdefault(invoice.customer, []).append(invoice.currency)
	parties = []
	for row in rows:
		parties.append(
			{
				"row": row.name,
				"party_type": row.parenttype,
				"party": row.parent,
				"current": wrong_account,
				"account": party_account_choice(
					row.parenttype, currencies.get(row.parent, []), usd_account, other_account
				),
			}
		)
	parties.sort(key=lambda row: (row["party_type"], row["party"]))
	return {"company_default": other_account, "parties": parties}


def _block_reason(company, plan) -> str:
	dates = []
	for row in plan["invoices"]:
		if row["action"] == MOVE and row.get("posting_date"):
			dates.append(str(row["posting_date"]))
	for row in plan["payments"]:
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
					"Period Closing Voucher {0} closes the books through {1}. Cancel that voucher before this repair, then create it again."
				).format(latest[0].name, latest[0].period_end_date)
			)
	if frappe.db.exists("DocType", "Accounts Settings") and frappe.get_meta("Accounts Settings").has_field(
		"acc_frozen_upto"
	):
		frozen = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
		if frozen and any(date <= str(frozen) for date in dates):
			messages.append(_("Accounts are frozen through {0}.").format(frozen))
	return " ".join(messages)


def _apply_chain(plan, chain):
	invoices = [row for row in plan["invoices"] if row["name"] in set(chain["invoices"])]
	payments = [row for row in plan["payments"] if row["name"] in set(chain["payments"])]
	for invoice in _invoice_order(invoices):
		frappe.db.set_value(
			"Sales Invoice",
			invoice["name"],
			{"debit_to": invoice["to_account"], "party_account_currency": invoice["account_currency"]},
			update_modified=True,
		)
	for payment in payments:
		_write_payment(payment)
	for invoice in _invoice_order(invoices):
		_rebuild_invoice(invoice["name"])
	for payment in payments:
		_rebuild_payment(payment)


def _write_payment(payment):
	if payment["mode"] == MULTI:
		_write_multi_payment(payment)
		return
	if payment.get("keep_amounts"):
		_write_same_currency_payment(payment)
		return
	allocated_total = flt(payment["party_amount"]) - flt(payment.get("unallocated_amount"))
	values = {
		payment["party_account_field"]: payment["party_account"],
		payment["party_currency_field"]: payment["party_account_currency"],
		payment["party_amount_field"]: payment["party_amount"],
		payment["party_rate_field"]: payment["party_exchange_rate"],
		"total_allocated_amount": allocated_total,
		"base_total_allocated_amount": payment["base_party_amount"],
		"unallocated_amount": payment.get("unallocated_amount") or 0,
	}
	if payment["payment_type"] == "Pay":
		values["base_received_amount"] = payment["base_party_amount"]
	else:
		values["base_paid_amount"] = payment["base_party_amount"]
	if payment.get("previous_party_currency") != payment.get("party_account_currency"):
		if payment["payment_type"] == "Pay":
			values["received_amount_after_tax"] = payment["party_amount"]
			values["base_received_amount_after_tax"] = payment["base_party_amount"]
		else:
			values["paid_amount_after_tax"] = payment["party_amount"]
			values["base_paid_amount_after_tax"] = payment["base_party_amount"]
	if frappe.get_meta("Payment Entry").has_field("hero_multi_account"):
		values["hero_multi_account"] = 0
	frappe.db.set_value("Payment Entry", payment["name"], values, update_modified=True)
	for reference in payment["references"]:
		_write_reference(reference, multi=False)


def _write_same_currency_payment(payment):
	"""Change the receivable and leave the submitted amounts in place.

	The party currency is unchanged, so the existing party and bank amounts
	already balance.
	"""
	values = {
		payment["party_account_field"]: payment["party_account"],
		payment["party_currency_field"]: payment["party_account_currency"],
	}
	if frappe.get_meta("Payment Entry").has_field("hero_multi_account"):
		values["hero_multi_account"] = 0
	frappe.db.set_value("Payment Entry", payment["name"], values, update_modified=True)
	for reference in payment["references"]:
		_write_reference(reference, multi=False, accounts_only=True)


def _write_multi_payment(payment):
	if frappe.get_meta("Payment Entry").has_field("hero_multi_account"):
		frappe.db.set_value("Payment Entry", payment["name"], {"hero_multi_account": 1}, update_modified=True)
	for reference in payment["references"]:
		_write_reference(reference, multi=True)
	if frappe.db.table_exists("Payment Entry Deduction"):
		for name in frappe.get_all(
			"Payment Entry Deduction",
			filters={"parent": payment["name"], "is_exchange_gain_loss": 1},
			pluck="name",
		):
			frappe.db.delete("Payment Entry Deduction", {"name": name})


def _write_reference(reference, multi, accounts_only=False):
	if not reference.get("row_name"):
		return
	meta = frappe.get_meta("Payment Entry Reference")
	if accounts_only:
		values = {}
		for field, value in (
			("hero_account", reference["account"]),
			("hero_account_currency", reference["account_currency"]),
		):
			if meta.has_field(field):
				values[field] = value
		if values:
			frappe.db.set_value(
				"Payment Entry Reference", reference["row_name"], values, update_modified=True
			)
		return
	values = {
		"allocated_amount": reference["allocated_amount"],
		"exchange_rate": reference["exchange_rate"],
	}
	optional = {
		"hero_account": reference["account"],
		"hero_account_currency": reference["account_currency"],
		"hero_invoice_currency": reference["invoice_currency"],
		"hero_allocated_invoice_amount": reference["invoice_amount"],
		"hero_allocated_account_amount": reference["allocated_amount"],
		"hero_payment_rate": reference.get("payment_rate") or reference["exchange_rate"],
		"hero_booked_rate": reference.get("payment_rate") or reference["exchange_rate"],
	}
	for field, value in optional.items():
		if meta.has_field(field):
			values[field] = value
	frappe.db.set_value("Payment Entry Reference", reference["row_name"], values, update_modified=True)


def _rebuild_invoice(name):
	_clear_ledger("Sales Invoice", name)
	doc = frappe.get_doc("Sales Invoice", name)
	doc.flags.ignore_permissions = True
	doc.make_gl_entries(from_repost=True)


def _rebuild_payment(payment):
	_clear_ledger("Payment Entry", payment["name"])
	doc = frappe.get_doc("Payment Entry", payment["name"])
	doc.flags.ignore_permissions = True
	if payment["mode"] == MULTI and payment.get("advance_account"):
		doc.flags.hero_repair_advance_account = payment["advance_account"]
	doc.make_gl_entries()
	if payment["mode"] == MULTI:
		_persist_rebuilt_payment(doc)


def _persist_rebuilt_payment(doc):
	meta = frappe.get_meta("Payment Entry")
	values = {}
	for field in _HEADER_FIELDS:
		if meta.has_field(field):
			values[field] = doc.get(field)
	if values:
		frappe.db.set_value("Payment Entry", doc.name, values, update_modified=True)
	reference_meta = frappe.get_meta("Payment Entry Reference")
	for row in doc.get("references") or []:
		if not row.get("name"):
			continue
		reference_values = {}
		for field in _REFERENCE_FIELDS:
			if reference_meta.has_field(field):
				reference_values[field] = row.get(field)
		if reference_values:
			frappe.db.set_value("Payment Entry Reference", row.name, reference_values, update_modified=True)


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
	for name in chain["invoices"]:
		invoice = invoices[name]
		current = flt(frappe.db.get_value("Sales Invoice", name, "outstanding_amount"))
		expected = flt(invoice["outstanding_amount"])
		if not outstanding_matches(
			expected,
			current,
			invoice.get("party_account_currency"),
			invoice.get("account_currency"),
			invoice.get("currency"),
			invoice.get("conversion_rate"),
			plan.get("company_currency"),
		):
			return _("Outstanding on {0} would change from {1} to {2}.").format(name, expected, current)
	for name in chain["payments"]:
		current = _bank_amount(name)
		expected = flt(payments[name]["bank_amount"])
		if abs(current - expected) > 0.01:
			return _("Bank amount on {0} would change from {1} to {2}.").format(name, expected, current)
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


def _multi_ready() -> bool:
	if not frappe.db.exists("DocType", "Payment Entry Reference"):
		return False
	reference_meta = frappe.get_meta("Payment Entry Reference")
	payment_meta = frappe.get_meta("Payment Entry")
	return (
		reference_meta.has_field("hero_account")
		and reference_meta.has_field("hero_allocated_invoice_amount")
		and payment_meta.has_field("hero_multi_account")
	)


def _chain_result(chain, status, reason):
	return {
		"invoices": list(chain["invoices"]),
		"payments": list(chain["payments"]),
		"status": status,
		"reason": reason,
	}


def _rollback(savepoint):
	frappe.db.rollback(save_point=savepoint)
