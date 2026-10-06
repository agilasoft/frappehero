# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for invoice disputes, statements, and receivables aging.

Opening a dispute releases every active action on that sales invoice.
Hold, Collection, and Dunning are the usual kinds. Any other kind is
released as well. Closing the dispute does not put those actions back.

Statement of Account and Receivables Aging still list the invoice, under
Disputed Transactions, and leave it out of the amount due and the buckets.
"""

from datetime import date, datetime

from frappehero.flags import as_flag, clean_text

DISPUTE_STATUSES = ("Open", "Resolved", "Cancelled")
STANDARD_ACTIONS = ("Hold", "Collection", "Dunning")
DISPUTED_SECTION = "Disputed Transactions"
AGING_BUCKETS = ("Current", "1-30", "31-60", "61-90", "91 and over")
BUCKET_FIELDS = {
	"Current": "current",
	"1-30": "days_1_30",
	"31-60": "days_31_60",
	"61-90": "days_61_90",
	"91 and over": "days_91_over",
}
HOLD_FIELDS = ("on_hold", "is_on_hold")


class DisputeError(ValueError):
	"""A dispute, action, or statement that breaks the rules."""


def raise_dispute(
	reference_doctype,
	reference_name,
	sales_invoice,
	company,
	customer,
	reason,
	source_module,
	dispute_date,
	existing_disputes,
	actions,
) -> dict:
	"""Build an open dispute and the actions it releases.

	``existing_disputes`` are earlier disputes. ``actions`` are holds,
	collections, dunning, and anything else registered against invoices.
	"""
	fields = normalize_dispute_fields(
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"sales_invoice": sales_invoice,
			"company": company,
			"customer": customer,
			"reason": reason,
			"source_module": source_module,
			"dispute_date": dispute_date,
			"status": "Open",
		}
	)
	assert_no_open_dispute(fields["sales_invoice"], existing_disputes)
	updated, releases = release_invoice_actions(fields["sales_invoice"], actions)
	fields["releases"] = releases
	return {"dispute": fields, "actions": updated}


def normalize_dispute_fields(row) -> dict:
	reference_doctype = clean_text(row.get("reference_doctype"))
	reference_name = clean_text(row.get("reference_name"))
	sales_invoice = clean_text(row.get("sales_invoice"))
	if reference_doctype == "Sales Invoice" and not sales_invoice:
		sales_invoice = reference_name
	if not reference_doctype or not reference_name:
		raise DisputeError("Source document is required.")
	if not sales_invoice:
		raise DisputeError("Sales invoice is required.")
	if not clean_text(row.get("company")):
		raise DisputeError("Company is required.")
	if not clean_text(row.get("customer")):
		raise DisputeError("Customer is required.")
	if not clean_text(row.get("reason")):
		raise DisputeError("Reason is required.")
	dispute_date = _as_date(row.get("dispute_date"))
	if not dispute_date:
		raise DisputeError("Dispute date is required.")
	status = clean_text(row.get("status")) or "Open"
	if status not in DISPUTE_STATUSES:
		raise DisputeError("Status must be Open, Resolved, or Cancelled.")
	return {
		"company": clean_text(row.get("company")),
		"customer": clean_text(row.get("customer")),
		"sales_invoice": sales_invoice,
		"dispute_date": dispute_date.isoformat(),
		"reason": clean_text(row.get("reason")),
		"status": status,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"source_module": clean_text(row.get("source_module")),
	}


def validate_status_transition(previous, new, is_new) -> str:
	"""Return the status to store. A new dispute starts open."""
	status = clean_text(new) or "Open"
	if status not in DISPUTE_STATUSES:
		raise DisputeError("Status must be Open, Resolved, or Cancelled.")
	if is_new or not clean_text(previous):
		if status != "Open":
			raise DisputeError("A new dispute starts open.")
		return status
	prior = clean_text(previous)
	if prior == status:
		return status
	if prior == "Open" and status in ("Resolved", "Cancelled"):
		return status
	raise DisputeError("An open dispute can be resolved or cancelled.")


def assert_no_open_dispute(sales_invoice, existing_disputes, ignore_name=None) -> None:
	invoice = clean_text(sales_invoice)
	skip = clean_text(ignore_name)
	for dispute in existing_disputes or []:
		if clean_text(dispute.get("sales_invoice")) != invoice:
			continue
		if clean_text(dispute.get("status")) != "Open":
			continue
		if skip and clean_text(dispute.get("name")) == skip:
			continue
		raise DisputeError(f"An open dispute already exists for {invoice}.")


def release_invoice_actions(sales_invoice, actions) -> tuple[list[dict], list[dict]]:
	"""Release every active action on this invoice. Other invoices stay as they are."""
	invoice = clean_text(sales_invoice)
	updated = []
	releases = []
	for action in actions or []:
		row = _action_row(action)
		if row["sales_invoice"] == invoice and row["active"]:
			row["active"] = 0
			releases.append(
				{
					"action_kind": row["kind"],
					"source_doctype": row["source_doctype"],
					"source_name": row["source_name"],
					"previous_state": row["state"],
					"invoice_action": row["invoice_action"] or None,
				}
			)
		updated.append(row)
	return updated, releases


def close_dispute(dispute, status) -> dict:
	"""Resolve or cancel. Released actions are left released."""
	new_status = validate_status_transition(dispute.get("status"), status, is_new=False)
	updated = dict(dispute)
	updated["status"] = new_status
	updated["releases"] = list(dispute.get("releases") or [])
	return updated


def prepare_invoice_action(action, existing_disputes) -> dict:
	"""Normalize one hold, collection, dunning, or other action.

	An active action cannot be added while that invoice has an open dispute.
	"""
	row = _action_row(action)
	if not row["sales_invoice"]:
		raise DisputeError("Sales invoice is required.")
	if not row["kind"]:
		raise DisputeError("Action kind is required.")
	if row["active"]:
		assert_no_open_dispute(row["sales_invoice"], existing_disputes)
	row["customer"] = clean_text(action.get("customer"))
	row["company"] = clean_text(action.get("company"))
	return row


def invoice_link_for(disputes, sales_invoice) -> dict:
	"""Custom field values for the sales invoice. Empty once nothing is open."""
	invoice = clean_text(sales_invoice)
	open_rows = [
		row
		for row in disputes or []
		if clean_text(row.get("sales_invoice")) == invoice and clean_text(row.get("status")) == "Open"
	]
	if not open_rows:
		return {"hero_dispute": None, "hero_dispute_status": None}
	return {
		"hero_dispute": clean_text(open_rows[0].get("name")) or None,
		"hero_dispute_status": "Open",
	}


def statement_of_account(rows, disputes, customer=None, company=None, from_date=None, to_date=None) -> dict:
	"""Outstanding invoices for one statement.

	Open disputed invoices follow a Disputed Transactions section and are
	excluded from the running balance.
	"""
	start = _as_date(from_date)
	end = _as_date(to_date)
	normal, disputed = _split(rows, disputes, customer, company, start, end, as_of=None)
	balance = 0.0
	statement = []
	for row in _sorted_rows(normal):
		balance = round(balance + row["outstanding"], 2)
		statement.append({**row, "running_balance": balance, "section": "", "is_section": 0, "bold": 0})
	disputed_total = round(sum(row["outstanding"] for row in disputed), 2)
	if disputed:
		statement.append(_section_row(customer))
		for row in _sorted_rows(disputed):
			statement.append(
				{**row, "running_balance": None, "section": DISPUTED_SECTION, "is_section": 0, "bold": 0}
			)
	return {
		"rows": statement,
		"amount_due": balance,
		"disputed_outstanding": disputed_total,
	}


def receivables_aging(rows, disputes, as_of, customer=None, company=None) -> dict:
	"""Age outstanding invoices. Open disputes sit under Disputed Transactions."""
	end = _as_date(as_of)
	if not end:
		raise DisputeError("As-of date is required.")
	normal, disputed = _split(rows, disputes, customer, company, None, None, as_of=end)
	buckets = {name: 0.0 for name in AGING_BUCKETS}
	aged = []
	for row in _sorted_rows(normal):
		days = _age_days(row, end)
		bucket = aging_bucket(days)
		amounts = _bucket_amounts(bucket, row["outstanding"])
		buckets[bucket] = round(buckets[bucket] + row["outstanding"], 2)
		aged.append({**row, "age_days": days, "section": "", "is_section": 0, "bold": 0, **amounts})
	disputed_total = round(sum(row["outstanding"] for row in disputed), 2)
	if disputed:
		aged.append(_section_row(customer))
		for row in _sorted_rows(disputed):
			days = _age_days(row, end)
			amounts = _bucket_amounts(None, 0)
			aged.append(
				{
					**row,
					"age_days": days,
					"section": DISPUTED_SECTION,
					"is_section": 0,
					"bold": 0,
					**amounts,
				}
			)
	return {
		"rows": aged,
		"buckets": buckets,
		"amount_due": round(sum(buckets.values()), 2),
		"disputed_outstanding": disputed_total,
	}


def same_day(left, right) -> bool:
	return _as_date(left) == _as_date(right)


def aging_bucket(days: int) -> str:
	if days <= 0:
		return "Current"
	if days <= 30:
		return "1-30"
	if days <= 60:
		return "31-60"
	if days <= 90:
		return "61-90"
	return "91 and over"


def _split(rows, disputes, customer, company, from_date, to_date, as_of):
	open_invoices = {
		clean_text(dispute.get("sales_invoice"))
		for dispute in disputes or []
		if clean_text(dispute.get("status")) == "Open" and clean_text(dispute.get("sales_invoice"))
	}
	wanted_customer = clean_text(customer)
	wanted_company = clean_text(company)
	normal = []
	disputed = []
	for source in rows or []:
		row = _invoice_row(source)
		if row["outstanding"] == 0:
			continue
		if wanted_customer and row["customer"] != wanted_customer:
			continue
		if wanted_company and row["company"] != wanted_company:
			continue
		if not _posted_in_range(row["posting_date"], from_date, to_date, as_of):
			continue
		if row["sales_invoice"] in open_invoices:
			disputed.append(row)
		else:
			normal.append(row)
	return normal, disputed


def _invoice_row(source) -> dict:
	return {
		"sales_invoice": clean_text(source.get("sales_invoice") or source.get("name")),
		"customer": clean_text(source.get("customer")),
		"company": clean_text(source.get("company")),
		"posting_date": _date_text(source.get("posting_date")),
		"due_date": _date_text(source.get("due_date")),
		"outstanding": round(float(source.get("outstanding") or source.get("outstanding_amount") or 0), 2),
	}


def _action_row(action) -> dict:
	kind = clean_text(action.get("kind") or action.get("action_kind"))
	state = clean_text(action.get("state") or action.get("previous_state")) or "Active"
	invoice_action = clean_text(action.get("invoice_action"))
	if not invoice_action and clean_text(action.get("source_doctype")) == "Hero Invoice Action":
		invoice_action = clean_text(action.get("source_name") or action.get("name"))
	return {
		"sales_invoice": clean_text(action.get("sales_invoice")),
		"kind": kind,
		"source_doctype": clean_text(action.get("source_doctype")),
		"source_name": clean_text(action.get("source_name")),
		"state": state,
		"active": as_flag(action.get("active")),
		"invoice_action": invoice_action,
		"customer": clean_text(action.get("customer")),
		"company": clean_text(action.get("company")),
	}


def _section_row(customer) -> dict:
	return {
		"sales_invoice": "",
		"customer": clean_text(customer),
		"company": "",
		"posting_date": None,
		"due_date": None,
		"outstanding": None,
		"running_balance": None,
		"age_days": None,
		"section": DISPUTED_SECTION,
		"is_section": 1,
		"bold": 1,
		**_bucket_amounts(None, 0),
	}


def _bucket_amounts(bucket, amount) -> dict:
	amounts = {field: 0.0 for field in BUCKET_FIELDS.values()}
	if bucket:
		amounts[BUCKET_FIELDS[bucket]] = round(float(amount or 0), 2)
	return amounts


def _sorted_rows(rows) -> list[dict]:
	return sorted(rows, key=lambda row: (row.get("posting_date") or "", row.get("sales_invoice") or ""))


def _posted_in_range(posting_date, from_date, to_date, as_of) -> bool:
	if not from_date and not to_date and not as_of:
		return True
	posted = _as_date(posting_date)
	if from_date or to_date:
		if not posted:
			return False
		if from_date and posted < from_date:
			return False
		if to_date and posted > to_date:
			return False
	if as_of and posted and posted > as_of:
		return False
	return True


def _age_days(row, as_of: date) -> int:
	due = _as_date(row.get("due_date")) or _as_date(row.get("posting_date")) or as_of
	return (as_of - due).days


def _date_text(value):
	parsed = _as_date(value)
	if not parsed:
		return None
	return parsed.isoformat()


def _as_date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = clean_text(value)
	if not text:
		return None
	try:
		return date.fromisoformat(text[:10])
	except ValueError as exc:
		raise DisputeError("Use a date like 2026-04-01.") from exc
