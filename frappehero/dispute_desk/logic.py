# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for invoice disputes, statements, and receivables aging.

Opening a dispute releases every active action on that sales invoice.
Hold, Collection, and Dunning are the usual kinds. Any other kind is
released as well. Closing the dispute does not put those actions back.

The Sales Invoice form keeps that dispute on its own tab, with the customer
credit position and any holds. The tab is not a section inside the invoice
header.

Statement of Account and Receivables Aging leave an open dispute out of the
amount due and the aging buckets. The table is only the invoices still due.
Disputed Transactions is a section on the printout.
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


def sales_invoice_dispute_fields() -> list[dict]:
	"""Custom fields for the Sales Invoice Dispute tab.

	The tab is anchored after Connections. A section inserted after Customer
	would sit in the invoice header and pull Company, the posting dates, and
	the credit-note checks into that section.
	"""
	return [
		{
			"fieldname": "hero_dispute_tab",
			"label": "Dispute",
			"fieldtype": "Tab Break",
			"insert_after": "connections_tab",
		},
		{
			"fieldname": "hero_dispute_section",
			"label": "Dispute",
			"fieldtype": "Section Break",
			"insert_after": "hero_dispute_tab",
			"collapsible": 0,
		},
		{
			"fieldname": "hero_dispute",
			"label": "Dispute",
			"fieldtype": "Link",
			"options": "Hero Dispute",
			"insert_after": "hero_dispute_section",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"description": "The open dispute for this invoice. Statement of Account and Receivables Aging list it under Disputed Transactions.",
		},
		{
			"fieldname": "hero_dispute_column",
			"fieldtype": "Column Break",
			"insert_after": "hero_dispute",
		},
		{
			"fieldname": "hero_dispute_status",
			"label": "Dispute Status",
			"fieldtype": "Data",
			"insert_after": "hero_dispute_column",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "hero_credit_section",
			"label": "Credit",
			"fieldtype": "Section Break",
			"insert_after": "hero_dispute_status",
			"collapsible": 0,
			"description": "Customer credit limit for this company, the outstanding balance, and credit notes raised against this invoice.",
		},
		{
			"fieldname": "hero_credit_html",
			"fieldtype": "HTML",
			"insert_after": "hero_credit_section",
			"print_hide": 1,
		},
		{
			"fieldname": "hero_holds_section",
			"label": "Holds",
			"fieldtype": "Section Break",
			"insert_after": "hero_credit_html",
			"collapsible": 0,
			"description": "Invoice holds and Hold actions. Opening a dispute releases them.",
		},
		{
			"fieldname": "hero_holds_html",
			"fieldtype": "HTML",
			"insert_after": "hero_holds_section",
			"print_hide": 1,
		},
	]


def dispute_tab_fieldnames() -> tuple[str, ...]:
	return tuple(row["fieldname"] for row in sales_invoice_dispute_fields())


def dispute_tab_field_order(field_order) -> list[str]:
	"""Put the dispute fields on a tab at the end of a Sales Invoice field order.

	Customize Form can save a field order that leaves the Dispute section in
	the invoice header, between the customer and Company. Those fields are
	removed from the middle. Company, the posting dates, and the credit-note
	checks keep their relative order. The Dispute tab and its fields are appended.
	"""
	names = dispute_tab_fieldnames()
	tab = "hero_dispute_tab"
	dispute = set(names)
	incoming = [clean_text(name) for name in field_order or [] if clean_text(name)]
	present = set(incoming)
	if not (present & (dispute - {tab})):
		return incoming
	rest = [name for name in incoming if name not in dispute]
	body = [name for name in names if name == tab or name in present]
	return rest + body


def header_column_breaks_to_hide(fields) -> list[str]:
	"""Column breaks to drop so the Sales Invoice header is three columns.

	``fields`` follows the form order. Each item has ``fieldname`` and
	``fieldtype``. Hidden breaks are included so they do not leave an empty
	column. Only the first section counts, so Items and the later sections keep
	their columns. When that section has more than two visible column breaks,
	the earliest extras are returned and the last two stay: customer, dates,
	then the credit-note checks.
	"""
	hidden_breaks = []
	visible_breaks = []
	started = False
	for field in fields or []:
		if not isinstance(field, dict):
			continue
		fieldname = clean_text(field.get("fieldname"))
		if fieldname == "__newname":
			continue
		fieldtype = clean_text(field.get("fieldtype"))
		if fieldtype == "Tab Break":
			if started:
				break
			continue
		if fieldtype == "Section Break":
			if started:
				break
			started = True
			continue
		if not fieldtype:
			continue
		started = True
		if fieldtype != "Column Break" or not fieldname:
			continue
		if as_flag(field.get("hidden")):
			hidden_breaks.append(fieldname)
		else:
			visible_breaks.append(fieldname)
	extras = visible_breaks[:-2] if len(visible_breaks) > 2 else []
	return hidden_breaks + extras


def sales_invoice_dispute_tab(
	customer,
	company,
	currency,
	credit_limit,
	outstanding,
	bypass_credit_limit_check,
	is_return,
	return_against,
	credit_notes,
	holds,
	sales_invoice=None,
) -> dict:
	"""Credit position and holds for the Sales Invoice Dispute tab.

	``credit_limit`` is None when this company has no limit. Zero is the same
	as no limit. ``holds`` may mix invoice flags, invoice actions, and dispute
	releases. Only holds are returned. An active hold wins over a released
	copy of the same source and state.
	"""
	limit_set = 0
	limit = _money(credit_limit)
	if limit is not None and limit > 0:
		limit_set = 1
	else:
		limit = None
	balance = _money(outstanding)
	if balance is None:
		balance = 0.0
	available = round(limit - balance, 2) if limit_set else None
	notes = []
	company_currency = clean_text(currency)
	for note in credit_notes or []:
		name = clean_text(note.get("name"))
		if not name:
			continue
		note_currency = clean_text(note.get("currency")) or company_currency
		note_outstanding = note.get("outstanding")
		if note_outstanding is None or note_outstanding == "":
			note_outstanding = note.get("outstanding_amount")
		notes.append(
			{
				"name": name,
				"posting_date": _date_text(note.get("posting_date")),
				"grand_total": _money(note.get("grand_total")) or 0.0,
				"outstanding": _money(note_outstanding) or 0.0,
				"currency": note_currency,
			}
		)
	notes.sort(key=lambda row: (row.get("posting_date") or "", row["name"]))
	return {
		"customer_known": 1 if clean_text(customer) else 0,
		"company_known": 1 if clean_text(company) else 0,
		"currency": company_currency,
		"limit_set": limit_set,
		"credit_limit": limit,
		"outstanding": balance,
		"available": available,
		"bypass_credit_limit_check": as_flag(bypass_credit_limit_check),
		"is_return": as_flag(is_return),
		"return_against": clean_text(return_against) or None,
		"credit_notes": notes,
		"holds": _holds_for_tab(holds, sales_invoice),
	}


def _holds_for_tab(holds, sales_invoice) -> list[dict]:
	invoice = clean_text(sales_invoice)
	kept = {}
	for source in holds or []:
		row = _hold_for_tab(source, invoice)
		if not row:
			continue
		key = (row["source_doctype"], row["source_name"], row["state"])
		current = kept.get(key)
		if current and current["active"] and not row["active"]:
			if not current["dispute"] and row["dispute"]:
				current["dispute"] = row["dispute"]
			continue
		if current and not row["dispute"]:
			row["dispute"] = current["dispute"]
		kept[key] = row
	rows = list(kept.values())
	rows.sort(key=lambda row: (0 if row["active"] else 1, row["source_doctype"], row["source_name"], row["state"]))
	return rows


def _hold_for_tab(row, sales_invoice) -> dict | None:
	fieldname = clean_text(row.get("fieldname"))
	kind = clean_text(row.get("kind") or row.get("action_kind"))
	dispute = clean_text(row.get("dispute")) or None
	if fieldname in HOLD_FIELDS:
		if not as_flag(row.get("active")):
			return None
		return {
			"source_doctype": "Sales Invoice",
			"source_name": clean_text(row.get("source_name") or sales_invoice),
			"state": fieldname,
			"active": 1,
			"dispute": dispute,
		}
	if not _is_hold_kind(kind):
		return None
	return {
		"source_doctype": clean_text(row.get("source_doctype")) or "Hero Invoice Action",
		"source_name": clean_text(row.get("source_name") or row.get("name")),
		"state": clean_text(row.get("state") or row.get("previous_state")),
		"active": as_flag(row.get("active")),
		"dispute": dispute,
	}


def _is_hold_kind(kind) -> bool:
	text = clean_text(kind).casefold().replace("_", " ")
	return text in {"hold", "on hold"}


def _money(value):
	if value is None or value == "":
		return None
	return round(float(value), 2)


def statement_of_account(rows, disputes, customer=None, company=None, from_date=None, to_date=None) -> dict:
	"""Outstanding invoices for one statement.

	``rows`` is the table: invoices still in the amount due. ``disputed_rows``
	is the Disputed Transactions section on the printout, with no running balance.
	"""
	start = _as_date(from_date)
	end = _as_date(to_date)
	normal, disputed = _split(rows, disputes, customer, company, start, end, as_of=None)
	balance = 0.0
	statement = []
	for row in _sorted_rows(normal):
		balance = round(balance + row["outstanding"], 2)
		statement.append({**row, "running_balance": balance, "section": "", "is_section": 0, "bold": 0})
	disputed_rows = [
		{**row, "running_balance": None, "section": DISPUTED_SECTION, "is_section": 0, "bold": 0}
		for row in _sorted_rows(disputed)
	]
	return {
		"rows": statement,
		"disputed_rows": disputed_rows,
		"amount_due": balance,
		"disputed_outstanding": round(sum(row["outstanding"] for row in disputed), 2),
	}


def receivables_aging(rows, disputes, as_of, customer=None, company=None) -> dict:
	"""Age outstanding invoices.

	Open disputes stay out of the buckets. They are ``disputed_rows``, printed
	under Disputed Transactions, not lines on the aging table.
	"""
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
	disputed_rows = []
	for row in _sorted_rows(disputed):
		days = _age_days(row, end)
		disputed_rows.append(
			{
				**row,
				"age_days": days,
				"section": DISPUTED_SECTION,
				"is_section": 0,
				"bold": 0,
				**_bucket_amounts(None, 0),
			}
		)
	return {
		"rows": aged,
		"disputed_rows": disputed_rows,
		"buckets": buckets,
		"amount_due": round(sum(buckets.values()), 2),
		"disputed_outstanding": round(sum(row["outstanding"] for row in disputed), 2),
	}


def rows_for_desk(result) -> list:
	"""Table lines first, then the printout's Disputed Transactions lines."""
	rows = list(result.get("rows") or [])
	rows.extend(result.get("disputed_rows") or [])
	return rows


def filter_disputes(
	rows,
	company=None,
	customer=None,
	status=None,
	sales_invoice=None,
	text=None,
	from_date=None,
	to_date=None,
) -> list:
	"""Keep disputes that match the Dispute Desk filters.

	A blank status, or All, does not filter by status. ``text`` matches the
	invoice, customer, source, reason, and status.
	"""
	wanted_company = clean_text(company)
	wanted_customer = clean_text(customer)
	wanted_invoice = clean_text(sales_invoice)
	wanted_status = clean_text(status)
	if wanted_status.casefold() == "all":
		wanted_status = ""
	start = _as_date(from_date) if clean_text(from_date) else None
	end = _as_date(to_date) if clean_text(to_date) else None
	query = " ".join(clean_text(text).casefold().split())
	matched = []
	for row in rows or []:
		if wanted_company and clean_text(row.get("company")) != wanted_company:
			continue
		if wanted_customer and clean_text(row.get("customer")) != wanted_customer:
			continue
		if wanted_invoice and clean_text(row.get("sales_invoice")) != wanted_invoice:
			continue
		if wanted_status and clean_text(row.get("status")) != wanted_status:
			continue
		if start or end:
			disputed_on = _as_date(row.get("dispute_date"))
			if not disputed_on:
				continue
			if start and disputed_on < start:
				continue
			if end and disputed_on > end:
				continue
		if query:
			haystack = " ".join(
				clean_text(row.get(key))
				for key in (
					"name",
					"company",
					"customer",
					"sales_invoice",
					"status",
					"reason",
					"reference_doctype",
					"reference_name",
					"source_module",
				)
			).casefold()
			if query not in haystack:
				continue
		matched.append(row)
	return matched


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
