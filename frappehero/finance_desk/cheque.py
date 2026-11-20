# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Assign cheque numbers from a Cheque Leaf onto Payment Entry."""

import frappe
from frappe import _

from frappehero.finance_desk.cheque_logic import (
	filter_leaves,
	mode_uses_cheque_leaf,
	plan_payment_cheque,
	preview_cheque,
	reconcile_issued_cheques,
	summarize_book,
	summarize_numbers,
)
from frappehero.flags import as_flag, clean_text


def validate_payment(doc, method=None):
	"""Reserve a cheque on draft save, and mark it used when the payment is submitted."""
	if not _ready(doc):
		return
	if doc.docstatus == 1 and getattr(doc, "_action", None) != "submit":
		return
	action = "submit" if getattr(doc, "_action", None) == "submit" else "save"
	_sync_payment(doc, action)


def submit_payment(doc, method=None):
	if not _ready(doc):
		return
	_sync_payment(doc, "submit")


def cancel_payment(doc, method=None):
	if not _ready(doc):
		return
	_sync_payment(doc, "cancel")


def trash_payment(doc, method=None):
	if not _ready(doc):
		return
	_sync_payment(doc, "trash")


def _sync_payment(doc, action):
	previous = _previous_payment(doc)
	selected = clean_text(doc.get("hero_cheque_leaf"))
	bank_account = _cheque_bank_account(doc)
	leaves = _load_leaves(bank_account, [selected, previous.get("hero_cheque_leaf")])
	numbers = _numbers_for([leaf["name"] for leaf in leaves])
	plan = plan_payment_cheque(
		action=action,
		payment_type=doc.get("payment_type"),
		bank_account=bank_account,
		company=doc.get("company"),
		mode_uses_cheque=_mode_uses_cheque(doc.get("mode_of_payment")),
		selected_leaf=selected,
		requested_number=doc.get("hero_cheque_number"),
		payment_name=doc.name,
		previous_leaf=previous.get("hero_cheque_leaf"),
		previous_number=previous.get("hero_cheque_number"),
		reference_no=doc.get("reference_no"),
		docstatus=doc.docstatus,
		leaves=leaves,
		numbers_by_leaf=numbers,
	)
	if plan["error"]:
		frappe.throw(_(plan["error"]))
	_write_updates(plan["updates"], doc)
	_apply_plan(doc, plan, action)


def _apply_plan(doc, plan, action):
	if action == "trash":
		return
	if action == "cancel":
		values = {"hero_cheque_state": plan["state"] or "Cancelled"}
	else:
		values = {
			"hero_cheque_leaf": plan["leaf"],
			"hero_cheque_number": plan["cheque_number"],
			"hero_cheque_state": plan["state"],
		}
		if plan["set_reference_no"] and plan["cheque_number"]:
			values["reference_no"] = plan["cheque_number"]
			if not doc.get("reference_date") and doc.get("posting_date"):
				values["reference_date"] = doc.posting_date
		elif plan["clear_reference_no"]:
			values["reference_no"] = ""
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	if doc.docstatus in (1, 2) and doc.name and not doc.get("__islocal"):
		frappe.db.set_value("Payment Entry", doc.name, values, update_modified=False)


def _write_updates(updates, doc):
	party = _cheque_party(doc)
	posting_date = doc.get("posting_date")
	for leaf_name, changes in (updates or {}).items():
		if not changes or not frappe.db.exists("Hero Cheque Leaf", leaf_name):
			continue
		frappe.db.sql(
			"select name from `tabHero Cheque Leaf` where name = %s for update",
			(leaf_name,),
		)
		current = {row["cheque_number"]: row for row in _numbers_for([leaf_name]).get(leaf_name, [])}
		for change in changes:
			row = current.get(change["cheque_number"])
			if row is None:
				frappe.throw(_("Cheque {0} is no longer on {1}.").format(change["cheque_number"], leaf_name))
			_assert_writable(row, change, doc.name)
			values = {
				"status": change["status"],
				"payment_entry": change.get("payment_entry") or "",
			}
			if change["status"] == "Available":
				values["party"] = ""
				values["posting_date"] = None
			elif change["status"] in ("Assigned", "Used"):
				values["party"] = party
				values["posting_date"] = posting_date
			frappe.db.set_value("Hero Cheque Number", row["name"], values, update_modified=False)


def _assert_writable(row, change, payment_name):
	status = change["status"]
	current = row["status"]
	owner = clean_text(row.get("payment_entry"))
	number = row["cheque_number"]
	if status in ("Assigned", "Used"):
		if current == "Cancelled":
			frappe.throw(_("Cheque {0} is cancelled on this Cheque Leaf.").format(number))
		if owner and owner != payment_name and current in ("Assigned", "Used"):
			frappe.throw(_("Cheque {0} is already {1} on {2}.").format(number, current.lower(), owner))
	if status == "Available" and current not in ("Available", "Assigned"):
		frappe.throw(_("Cheque {0} is {1} and stays on the leaf.").format(number, current.lower()))
	if status == "Cancelled" and current not in ("Cancelled", "Used"):
		frappe.throw(_("Cheque {0} is {1} and stays on the leaf.").format(number, current.lower()))


@frappe.whitelist()
def suggest_cheque(bank_account=None, company=None, mode_of_payment=None, leaf=None):
	"""Next free cheque for a Pay or Internal Transfer. The form offers it; saving reserves it."""
	_payer()
	bank_account = clean_text(bank_account)
	leaf = clean_text(leaf)
	if not frappe.db.table_exists("Hero Cheque Leaf"):
		return {"leaf": "", "cheque_number": "", "available": [], "error": None, "uses_cheque": False}
	leaves = _load_leaves(bank_account, [leaf])
	numbers = _numbers_for([row["name"] for row in leaves])
	uses_cheque = _mode_uses_cheque(mode_of_payment)
	return preview_cheque(
		leaves,
		numbers,
		bank_account,
		company=company,
		selected=leaf,
		mode_uses_cheque=uses_cheque,
	)


@frappe.whitelist()
def list_cheque_leaves(company=None, bank_account=None, status=None, usage=None, text=None):
	"""Leaves and how many numbers are still free. The page filters this list."""
	_finance()
	if not frappe.db.table_exists("Hero Cheque Leaf"):
		return {"leaves": [], "totals": summarize_book([])}
	filters = {}
	company = clean_text(company)
	bank_account = clean_text(bank_account)
	if company:
		filters["company"] = company
	if bank_account:
		filters["bank_account"] = bank_account
	rows = frappe.get_all(
		"Hero Cheque Leaf",
		filters=filters,
		fields=["name", "bank_account", "company", "bank", "status", "is_default"],
		limit_page_length=0,
	)
	numbers = _numbers_for([row.name for row in rows])
	leaves = []
	for row in rows:
		counts = summarize_numbers(numbers.get(row.name) or [])
		leaves.append(
			{
				"name": row.name,
				"bank_account": row.bank_account,
				"company": row.company,
				"bank": row.bank,
				"status": row.status,
				"is_default": as_flag(row.is_default),
				**counts,
			}
		)
	matched = filter_leaves(leaves, status=status, usage=usage, text=text)
	matched.sort(
		key=lambda leaf: (
			clean_text(leaf.get("bank_account")).casefold(),
			clean_text(leaf.get("name")).casefold(),
		)
	)
	return {"leaves": matched, "totals": summarize_book(matched)}


def _ready(doc) -> bool:
	if not frappe.db.table_exists("Hero Cheque Leaf") or not frappe.db.table_exists("Hero Cheque Number"):
		return False
	meta = frappe.get_meta("Payment Entry")
	return meta.has_field("hero_cheque_leaf") and meta.has_field("hero_cheque_number")


def _previous_payment(doc) -> dict:
	blank = {"hero_cheque_leaf": "", "hero_cheque_number": "", "hero_cheque_state": ""}
	if doc.get("__islocal") or not doc.name or not frappe.db.exists("Payment Entry", doc.name):
		return blank
	row = frappe.db.get_value(
		"Payment Entry",
		doc.name,
		["hero_cheque_leaf", "hero_cheque_number", "hero_cheque_state"],
		as_dict=True,
	)
	return row or blank


def _cheque_bank_account(doc) -> str:
	"""The Bank Account the cheque is drawn on.

	Pay uses Company Bank Account. Internal Transfer uses the Bank Account
	linked to Account Paid From. That link is filled during Payment Entry
	validate, which runs after this reservation, so the account is resolved here.
	"""
	payment_type = clean_text(doc.get("payment_type"))
	if payment_type == "Pay":
		return clean_text(doc.get("bank_account"))
	if payment_type != "Internal Transfer":
		return ""
	account = clean_text(doc.get("paid_from"))
	if account:
		return _bank_account_for_gl(account, doc.get("company"))
	return clean_text(doc.get("paid_from_bank_account"))


def _bank_account_for_gl(account, company) -> str:
	account = clean_text(account)
	if not account or not frappe.db.table_exists("Bank Account"):
		return ""
	filters = {"account": account, "disabled": 0}
	company = clean_text(company)
	if company and frappe.get_meta("Bank Account").has_field("company"):
		filters["company"] = company
	return clean_text(frappe.db.get_value("Bank Account", filters, "name"))


def _cheque_party(doc) -> str:
	named = clean_text(doc.get("party_name") or doc.get("party"))
	if not named and clean_text(doc.get("payment_type")) == "Internal Transfer":
		named = clean_text(doc.get("paid_to"))
	return named[:140]


def backfill_internal_transfers() -> dict:
	"""Mark Cheque Leaf numbers already stored on an Internal Transfer.

	Called from migrate. A number that is not on the paying bank's leaf is left
	alone, and a number held by another payment is left with that payment.
	"""
	empty = {"numbers": 0, "payments": 0, "skipped": []}
	if not _backfill_ready():
		return empty
	payments = _issued_transfers()
	if not payments:
		return empty
	_fill_transfer_banks(payments)
	banks = sorted({row["bank_account"] for row in payments if row.get("bank_account")})
	leaves = _leaves_for_banks(banks)
	numbers = _numbers_for([leaf["name"] for leaf in leaves])
	plan = reconcile_issued_cheques(payments, leaves, numbers)
	written = _apply_issued(plan)
	_report_backfill(written)
	return written


def _backfill_ready() -> bool:
	if not frappe.db.table_exists("Payment Entry"):
		return False
	if not frappe.db.table_exists("Hero Cheque Leaf") or not frappe.db.table_exists("Hero Cheque Number"):
		return False
	meta = frappe.get_meta("Payment Entry")
	return meta.has_field("hero_cheque_leaf") and meta.has_field("hero_cheque_number") and meta.has_field("hero_cheque_state")


def _issued_transfers() -> list[dict]:
	meta = frappe.get_meta("Payment Entry")
	fields = [
		"name",
		"docstatus",
		"reference_no",
		"paid_from",
		"paid_to",
		"company",
		"posting_date",
		"party",
		"party_name",
		"hero_cheque_leaf",
		"hero_cheque_number",
		"hero_cheque_state",
	]
	if meta.has_field("paid_from_bank_account"):
		fields.append("paid_from_bank_account")
	rows = frappe.get_all(
		"Payment Entry",
		filters={"payment_type": "Internal Transfer", "docstatus": ["in", [0, 1, 2]]},
		fields=fields,
		limit_page_length=0,
	)
	payments = []
	for row in rows:
		number = clean_text(row.reference_no) or clean_text(row.hero_cheque_number)
		if not number:
			continue
		bank = clean_text(getattr(row, "paid_from_bank_account", "") or "")
		payments.append(
			{
				"name": row.name,
				"payment_type": "Internal Transfer",
				"docstatus": row.docstatus,
				"reference_no": row.reference_no,
				"hero_cheque_number": row.hero_cheque_number,
				"hero_cheque_leaf": row.hero_cheque_leaf,
				"hero_cheque_state": row.hero_cheque_state,
				"bank_account": bank,
				"paid_from": row.paid_from,
				"company": row.company,
				"posting_date": row.posting_date,
				"party": clean_text(row.party_name or row.party or row.paid_to)[:140],
			}
		)
	return payments


def _fill_transfer_banks(payments):
	pending = [row for row in payments if not row.get("bank_account") and clean_text(row.get("paid_from"))]
	if not pending or not frappe.db.table_exists("Bank Account"):
		return
	accounts = sorted({clean_text(row.get("paid_from")) for row in pending})
	found = frappe.get_all(
		"Bank Account",
		filters={"account": ["in", accounts], "disabled": 0},
		fields=["name", "account", "company"],
		limit_page_length=0,
	)
	by_account = {}
	for row in found:
		by_account.setdefault(clean_text(row.account), []).append(row)
	for payment in pending:
		matches = by_account.get(clean_text(payment.get("paid_from"))) or []
		company = clean_text(payment.get("company"))
		chosen = next((row for row in matches if not company or clean_text(row.company) == company), None)
		if chosen:
			payment["bank_account"] = chosen.name


def _leaves_for_banks(banks) -> list[dict]:
	if not banks or not frappe.db.table_exists("Hero Cheque Leaf"):
		return []
	rows = frappe.get_all(
		"Hero Cheque Leaf",
		filters={"bank_account": ["in", list(banks)]},
		fields=["name", "bank_account", "company", "status", "is_default"],
		limit_page_length=0,
	)
	return [
		{
			"name": row.name,
			"bank_account": row.bank_account,
			"company": row.company,
			"status": row.status,
			"is_default": row.is_default,
		}
		for row in rows
	]


def _apply_issued(plan) -> dict:
	blocked = set()
	written_numbers = 0
	for change in plan.get("numbers") or []:
		if not change.get("name") or not frappe.db.exists("Hero Cheque Number", change["name"]):
			blocked.add(change.get("payment_entry"))
			continue
		current = frappe.db.get_value(
			"Hero Cheque Number",
			change["name"],
			["status", "payment_entry"],
			as_dict=True,
		)
		owner = clean_text(current.payment_entry if current else "")
		status = clean_text(current.status if current else "")
		if owner and owner != change["payment_entry"] and status in ("Assigned", "Used", "Cancelled"):
			blocked.add(change["payment_entry"])
			continue
		frappe.db.set_value(
			"Hero Cheque Number",
			change["name"],
			{
				"status": change["status"],
				"payment_entry": change["payment_entry"],
				"party": change.get("party") or "",
				"posting_date": change.get("posting_date") or None,
			},
			update_modified=False,
		)
		written_numbers += 1
	written_payments = 0
	for payment in plan.get("payments") or []:
		if payment["name"] in blocked or not frappe.db.exists("Payment Entry", payment["name"]):
			continue
		frappe.db.set_value(
			"Payment Entry",
			payment["name"],
			{
				"hero_cheque_leaf": payment["hero_cheque_leaf"],
				"hero_cheque_number": payment["hero_cheque_number"],
				"hero_cheque_state": payment["hero_cheque_state"],
			},
			update_modified=False,
		)
		written_payments += 1
	skipped = list(plan.get("skipped") or [])
	return {"numbers": written_numbers, "payments": written_payments, "skipped": skipped}


def _report_backfill(written):
	skipped = written.get("skipped") or []
	if not written.get("numbers") and not written.get("payments") and not skipped:
		return
	lines = [
		"Cheque Leaf: updated {numbers} number(s) from {payments} Internal Transfer(s). Skipped {count}.".format(
			numbers=written.get("numbers") or 0,
			payments=written.get("payments") or 0,
			count=len(skipped),
		)
	]
	for row in skipped[:20]:
		lines.append("- {payment}: {reason}".format(**row))
	if len(skipped) > 20:
		lines.append("- and {0} more".format(len(skipped) - 20))
	print("\n".join(lines))


def _mode_uses_cheque(mode_of_payment) -> bool:
	mode = clean_text(mode_of_payment)
	if not mode or not frappe.db.exists("Mode of Payment", mode):
		return False
	flagged = 0
	if frappe.get_meta("Mode of Payment").has_field("hero_uses_cheque_leaf"):
		flagged = frappe.db.get_value("Mode of Payment", mode, "hero_uses_cheque_leaf") or 0
	return mode_uses_cheque_leaf(mode, flagged)


def _load_leaves(bank_account, extra_names) -> list[dict]:
	if not frappe.db.table_exists("Hero Cheque Leaf"):
		return []
	fields = ["name", "bank_account", "company", "status", "is_default"]
	rows = []
	if bank_account:
		rows.extend(
			frappe.get_all(
				"Hero Cheque Leaf",
				filters={"bank_account": bank_account},
				fields=fields,
				limit_page_length=0,
			)
		)
	seen = {row.name for row in rows}
	for name in extra_names or []:
		name = clean_text(name)
		if not name or name in seen or not frappe.db.exists("Hero Cheque Leaf", name):
			continue
		extra = frappe.db.get_value("Hero Cheque Leaf", name, fields, as_dict=True)
		if extra:
			rows.append(extra)
			seen.add(extra.name)
	return [
		{
			"name": row.name,
			"bank_account": row.bank_account,
			"company": row.company,
			"status": row.status,
			"is_default": row.is_default,
		}
		for row in rows
	]


def _numbers_for(leaf_names) -> dict:
	names = [clean_text(name) for name in leaf_names or [] if clean_text(name)]
	if not names or not frappe.db.table_exists("Hero Cheque Number"):
		return {}
	rows = frappe.get_all(
		"Hero Cheque Number",
		filters={"parent": ["in", names], "parenttype": "Hero Cheque Leaf"},
		fields=["name", "parent", "cheque_number", "status", "payment_entry", "party", "posting_date", "idx"],
		order_by="idx asc",
		limit_page_length=0,
	)
	grouped = {name: [] for name in names}
	for row in rows:
		grouped.setdefault(row.parent, []).append(
			{
				"name": row.name,
				"cheque_number": row.cheque_number,
				"status": row.status,
				"payment_entry": row.payment_entry,
				"party": row.party,
				"posting_date": row.posting_date,
			}
		)
	return grouped


def _payer():
	if not frappe.has_permission("Payment Entry", ptype="write"):
		frappe.throw(_("Not permitted to assign a cheque number."), frappe.PermissionError)


def _finance():
	frappe.only_for(["System Manager", "Accounts Manager"])
