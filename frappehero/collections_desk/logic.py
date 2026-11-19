# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Pure rules for the collections call log.

The desk queues customers who still owe money, and customers whose follow-up
is due. A call records who was reached and any promise. A promise needs an
amount and a date. A missed call cannot carry one.

The statement email is the same statement the report prints. A receipt is
split across the invoices the staff picked, oldest due first, and only when
those invoices share a receivable account and the company currency.
"""

import html
from datetime import date, datetime

from frappehero.flags import as_flag, clean_text

OUTCOMES = (
	"Reached",
	"No Answer",
	"Busy",
	"Wrong Number",
	"Voicemail",
	"Promised",
	"Refused",
	"Disputed",
	"Callback",
)
NO_PROMISE = ("No Answer", "Busy", "Wrong Number", "Voicemail")
NOTES_REQUIRED = ("Reached", "Promised", "Refused", "Disputed", "Callback")
DIRECTIONS = ("Outbound", "Inbound")
REPORT_TYPES = ("Claim", "Incident")
REPORT_STATUSES = ("Open", "Closed")


class CollectionError(ValueError):
	"""A call, report, statement, or receipt that breaks the rules."""


def normalize_call(row) -> dict:
	"""Return the call fields to store."""
	company = clean_text(row.get("company"))
	customer = clean_text(row.get("customer"))
	if not company:
		raise CollectionError("Company is required.")
	if not customer:
		raise CollectionError("Customer is required.")
	direction = clean_text(row.get("direction")) or "Outbound"
	if direction not in DIRECTIONS:
		raise CollectionError("Direction must be Outbound or Inbound.")
	outcome = clean_text(row.get("outcome"))
	if outcome not in OUTCOMES:
		raise CollectionError("Choose a call outcome.")
	call_time = _as_datetime(row.get("call_datetime") or row.get("call_time"))
	if not call_time:
		raise CollectionError("Call time is required.")
	phone = clean_text(row.get("phone"))
	if direction == "Outbound" and not phone:
		raise CollectionError("An outbound call needs the number dialed.")
	notes = clean_text(row.get("notes"))
	if outcome in NOTES_REQUIRED and not notes:
		raise CollectionError("Write what was said on the call.")
	collector = clean_text(row.get("collector"))
	if not collector:
		raise CollectionError("Collector is required.")
	promise_amount, promise_date = _promise(outcome, row.get("promise_amount"), row.get("promise_date"))
	follow_up = _optional_date(row.get("next_follow_up"), "Next follow-up")
	if outcome == "Callback" and not follow_up:
		raise CollectionError("A callback needs a follow-up date.")
	sent_on = row.get("statement_sent_on")
	return {
		"company": company,
		"customer": customer,
		"call_datetime": _datetime_text(call_time),
		"direction": direction,
		"collector": collector,
		"phone": phone,
		"contact_person": clean_text(row.get("contact_person")),
		"outcome": outcome,
		"notes": notes,
		"promise_amount": promise_amount,
		"promise_date": promise_date,
		"next_follow_up": follow_up,
		"statement_sent_to": clean_text(row.get("statement_sent_to")),
		"statement_sent_on": _optional_datetime(sent_on, "Statement sent on"),
		"payment_entry": clean_text(row.get("payment_entry")),
		"collection_report": clean_text(row.get("collection_report")),
	}


def freeze_call(previous, current) -> None:
	"""The customer on a saved call stays put."""
	if not previous:
		return
	if clean_text(previous.get("company")) != clean_text(current.get("company")):
		raise CollectionError("The company on a call cannot change.")
	if clean_text(previous.get("customer")) != clean_text(current.get("customer")):
		raise CollectionError("The customer on a call cannot change.")


def normalize_report(row, previous_status=None, is_new=False) -> dict:
	"""Return the claim or incident fields to store."""
	company = clean_text(row.get("company"))
	customer = clean_text(row.get("customer"))
	if not company:
		raise CollectionError("Company is required.")
	if not customer:
		raise CollectionError("Customer is required.")
	report_type = clean_text(row.get("report_type"))
	if report_type not in REPORT_TYPES:
		raise CollectionError("Type must be Claim or Incident.")
	report_date = _as_date(row.get("report_date"))
	if not report_date:
		raise CollectionError("Report date is required.")
	summary = clean_text(row.get("summary"))
	if not summary:
		raise CollectionError("Summary is required.")
	status = clean_text(row.get("status")) or "Open"
	if status not in REPORT_STATUSES:
		raise CollectionError("Status must be Open or Closed.")
	if is_new and status != "Open":
		raise CollectionError("A new report starts open.")
	amount = _optional_amount(row.get("amount"))
	if amount is not None and amount < 0:
		raise CollectionError("Amount cannot be negative.")
	return {
		"company": company,
		"customer": customer,
		"report_type": report_type,
		"report_date": report_date.isoformat(),
		"status": status,
		"sales_invoice": clean_text(row.get("sales_invoice")),
		"amount": amount or 0,
		"summary": summary,
		"collection_call": clean_text(row.get("collection_call")),
		"dispute": clean_text(row.get("dispute")),
		"previous_status": clean_text(previous_status),
	}


def freeze_report(previous, current) -> None:
	"""The customer stays put. The invoice stays put once a dispute is open."""
	if not previous:
		return
	if clean_text(previous.get("company")) != clean_text(current.get("company")):
		raise CollectionError("The company on a report cannot change.")
	if clean_text(previous.get("customer")) != clean_text(current.get("customer")):
		raise CollectionError("The customer on a report cannot change.")
	if clean_text(previous.get("dispute")) and clean_text(previous.get("sales_invoice")) != clean_text(
		current.get("sales_invoice")
	):
		raise CollectionError("The sales invoice cannot change after a dispute is opened.")


def assert_invoice_for_customer(invoice, company, customer, invoice_company, invoice_customer, docstatus=None, submitted=False) -> None:
	"""The named invoice has to be this customer's, in this company.

	A dispute also needs the invoice to be submitted. A blank invoice is allowed.
	"""
	if not clean_text(invoice):
		return
	if clean_text(invoice_company) != clean_text(company) or clean_text(invoice_customer) != clean_text(customer):
		raise CollectionError("That sales invoice is not for this customer.")
	if submitted and int(docstatus or 0) != 1:
		raise CollectionError("A dispute needs a submitted sales invoice.")


def dispute_from_report(report) -> dict:
	"""The dispute a claim can open. An incident, or a claim with no invoice, cannot."""
	report_type = clean_text(report.get("report_type"))
	invoice = clean_text(report.get("sales_invoice"))
	if report_type != "Claim" or not invoice:
		raise CollectionError("A dispute needs a claim that names one sales invoice.")
	reason = clean_text(report.get("summary"))
	if not reason:
		raise CollectionError("Summary is required.")
	return {
		"reference_doctype": "Hero Collection Report",
		"reference_name": clean_text(report.get("name")),
		"sales_invoice": invoice,
		"company": clean_text(report.get("company")),
		"customer": clean_text(report.get("customer")),
		"reason": reason,
		"source_module": "Collections Desk",
	}


def build_queue(customers, invoices, calls, today, text="", overdue_only=0, followups_only=0, collector="") -> list:
	"""Customers to call, follow-ups due first, then the oldest invoice."""
	as_of = _as_date(today)
	if not as_of:
		raise CollectionError("Today is required.")
	profiles = {}
	for source in customers or []:
		customer = clean_text(source.get("customer") or source.get("name"))
		if not customer:
			continue
		profiles[customer] = _profile(source, customer)
	outstanding = {}
	oldest = {}
	for source in invoices or []:
		row = _invoice(source)
		if not row["customer"] or row["outstanding"] <= 0:
			continue
		profiles.setdefault(row["customer"], _profile({}, row["customer"]))
		outstanding[row["customer"]] = round(outstanding.get(row["customer"], 0) + row["outstanding"], 2)
		due = row["due_date"] or ""
		if due and (row["customer"] not in oldest or due < oldest[row["customer"]]):
			oldest[row["customer"]] = due
	latest = {}
	for source in calls or []:
		call = _call_stamp(source)
		if not call["customer"]:
			continue
		profiles.setdefault(call["customer"], _profile({}, call["customer"]))
		current = latest.get(call["customer"])
		if current is None or (call["call_time"], call["name"]) >= (current["call_time"], current["name"]):
			latest[call["customer"]] = call
	query = clean_text(text).casefold()
	wanted = clean_text(collector)
	today_text = as_of.isoformat()
	rows = []
	for customer, profile in profiles.items():
		owed = outstanding.get(customer, 0.0)
		call = latest.get(customer) or {}
		follow = call.get("next_follow_up") or ""
		follow_due = bool(follow) and follow <= today_text
		if owed <= 0 and not follow_due:
			continue
		due = oldest.get(customer) or ""
		overdue = bool(due) and due < today_text and owed > 0
		if as_flag(overdue_only) and not overdue:
			continue
		if as_flag(followups_only) and not follow_due:
			continue
		if wanted and clean_text(call.get("collector")) != wanted:
			continue
		card = {
			**profile,
			"outstanding": owed,
			"oldest_due": due or None,
			"overdue": 1 if overdue else 0,
			"last_outcome": call.get("outcome") or "",
			"last_call": call.get("call_time") or None,
			"next_follow_up": follow or None,
			"follow_up_due": 1 if follow_due else 0,
			"promise_amount": call.get("promise_amount") or 0,
			"promise_date": call.get("promise_date") or None,
			"collector": call.get("collector") or "",
		}
		if query and query not in _queue_haystack(card):
			continue
		rows.append(card)
	rows.sort(
		key=lambda row: (
			0 if row["follow_up_due"] else 1,
			row["next_follow_up"] or "9999-99-99",
			row["oldest_due"] or "9999-99-99",
			-row["outstanding"],
			row["customer_name"].casefold(),
		)
	)
	return rows


def queue_summary(rows, calls, today) -> dict:
	"""Customers waiting, the amount due, promises due, and calls logged today."""
	as_of = _as_date(today)
	if not as_of:
		raise CollectionError("Today is required.")
	today_text = as_of.isoformat()
	promises = 0
	for row in rows or []:
		promise = row.get("promise_date") or ""
		if promise and promise <= today_text and _money_value(row.get("promise_amount")) > 0:
			promises += 1
	logged = 0
	for source in calls or []:
		when = _as_datetime(source.get("call_datetime") or source.get("call_time"))
		if when and when.date().isoformat() == today_text:
			logged += 1
	return {
		"customers": len(rows or []),
		"amount_due": round(sum(_money_value(row.get("outstanding")) for row in rows or []), 2),
		"promises_due": promises,
		"calls_today": logged,
	}


def assemble_client(customer, credit, address, phones, emails, invoices, disputes, payments, calls, reports, aging) -> dict:
	"""One customer file for the call page."""
	profile = _profile(customer or {}, clean_text((customer or {}).get("customer") or (customer or {}).get("name")))
	if not profile["customer"]:
		raise CollectionError("Customer is required.")
	open_invoices = {
		clean_text(row.get("sales_invoice"))
		for row in disputes or []
		if clean_text(row.get("sales_invoice")) and clean_text(row.get("status") or "Open") == "Open"
	}
	invoice_rows = []
	for source in invoices or []:
		row = _invoice(source)
		if row["customer"] and row["customer"] != profile["customer"]:
			continue
		if row["outstanding"] <= 0:
			continue
		row["disputed"] = 1 if row["sales_invoice"] in open_invoices else 0
		invoice_rows.append(row)
	invoice_rows.sort(key=lambda row: (row["due_date"] or "9999-99-99", row["sales_invoice"]))
	phone_list = _unique(phones)
	email_list = _unique(emails)
	phone = phone_list[0] if phone_list else ""
	limit = (credit or {}).get("credit_limit")
	call_rows = [_call_stamp(row) for row in calls or []]
	call_rows.sort(key=lambda row: (row["call_time"], row["name"]), reverse=True)
	report_rows = [_report_stamp(row) for row in reports or []]
	report_rows.sort(key=lambda row: (row["report_date"] or "", row["name"]), reverse=True)
	payment_rows = [_payment(row) for row in payments or []]
	payment_rows.sort(key=lambda row: (row["posting_date"] or "", row["name"]), reverse=True)
	return {
		**profile,
		"tax_id": clean_text((customer or {}).get("tax_id")),
		"credit_limit": None if limit in (None, "") else _money_value(limit),
		"outstanding": _money_value((credit or {}).get("outstanding")),
		"phones": phone_list,
		"emails": email_list,
		"phone": phone,
		"email": email_list[0] if email_list else "",
		"tel": tel_href(phone),
		"address": [clean_text(line) for line in address or [] if clean_text(line)],
		"invoices": invoice_rows,
		"aging": aging or {},
		"payments": payment_rows,
		"disputes": [_dispute(row) for row in disputes or [] if clean_text(row.get("status") or "Open") == "Open"],
		"calls": call_rows,
		"reports": report_rows,
	}


def statement_email(statement, customer_name, company, recipient) -> dict:
	"""Subject, recipient, and HTML body for one statement."""
	address = clean_text(recipient)
	if not _email_ok(address):
		raise CollectionError("A statement needs an email address.")
	name = clean_text(customer_name) or clean_text((statement or {}).get("customer"))
	company_name = clean_text(company)
	if not name:
		raise CollectionError("Customer is required.")
	if not company_name:
		raise CollectionError("Company is required.")
	rows = list((statement or {}).get("rows") or [])
	disputed = list((statement or {}).get("disputed_rows") or [])
	amount_due = round(float((statement or {}).get("amount_due") or 0), 2)
	disputed_outstanding = round(float((statement or {}).get("disputed_outstanding") or 0), 2)
	parts = [
		"<p>",
		html.escape(f"Statement of Account for {name}."),
		"</p>",
		"<p>",
		html.escape(f"Amount due: {_money(amount_due)}"),
		"</p>",
		_statement_table(rows, with_balance=True),
	]
	if disputed:
		parts.extend(
			[
				"<h3>Disputed Transactions</h3>",
				"<p>",
				html.escape(f"Open disputes. Left out of the amount due. {_money(disputed_outstanding)}"),
				"</p>",
				_statement_table(disputed, with_balance=False),
			]
		)
	parts.append(f"<p>{html.escape(company_name)}</p>")
	return {
		"subject": f"Statement of Account - {name}",
		"recipient": address,
		"message": "".join(parts),
		"amount_due": amount_due,
	}


def allocate_receipt(amount, invoices, company_currency=None) -> dict:
	"""Split a receipt across the selected invoices, oldest due first.

	The amount cannot exceed what those invoices still owe. Invoices on
	different receivable accounts, or in another currency, are refused so the
	staff record that receipt on Payment Entry.
	"""
	paid = _money_value(amount)
	if paid <= 0:
		raise CollectionError("Enter the amount received.")
	chosen = []
	for source in invoices or []:
		row = _invoice(source)
		if row["outstanding"] <= 0:
			continue
		row["account"] = clean_text(source.get("account"))
		row["currency"] = clean_text(source.get("currency"))
		row["grand_total"] = _money_value(source.get("grand_total") or row["outstanding"])
		chosen.append(row)
	if not chosen:
		raise CollectionError("Choose at least one open invoice.")
	accounts = {row["account"] for row in chosen if row["account"]}
	if len(accounts) > 1:
		raise CollectionError(
			"These invoices sit on different receivable accounts. Record the payment on Payment Entry."
		)
	currencies = {row["currency"] for row in chosen if row["currency"]}
	company_ccy = clean_text(company_currency)
	if company_ccy and currencies and currencies != {company_ccy}:
		raise CollectionError("These invoices use another currency. Record the payment on Payment Entry.")
	chosen.sort(key=lambda row: (row["due_date"] or "9999-99-99", row["sales_invoice"]))
	total = round(sum(row["outstanding"] for row in chosen), 2)
	if paid > total:
		raise CollectionError(
			"The amount is more than the selected invoices. Record the extra on Payment Entry."
		)
	left = paid
	references = []
	for row in chosen:
		if left <= 0:
			break
		take = round(min(left, row["outstanding"]), 2)
		if take <= 0:
			continue
		references.append({**row, "allocated": take})
		left = round(left - take, 2)
	return {
		"amount": paid,
		"allocated": round(paid - left, 2),
		"account": next(iter(accounts), ""),
		"references": references,
	}


def tel_href(phone) -> str:
	"""A tel link, or a blank string when the number has no digits."""
	text = clean_text(phone)
	if not text:
		return ""
	digits = "".join(ch for ch in text if ch.isdigit())
	if text.startswith("+"):
		digits = f"+{digits}"
	if not digits or digits == "+":
		return ""
	return f"tel:{digits}"


def _promise(outcome, amount, promise_date):
	paid = _optional_amount(amount)
	promised_on = _optional_date(promise_date, "Promise date")
	has_amount = paid is not None and paid != 0
	if outcome in NO_PROMISE and (has_amount or promised_on):
		raise CollectionError("That outcome cannot carry a promise.")
	if outcome == "Promised" and (not has_amount or paid < 0 or not promised_on):
		raise CollectionError("A promise needs an amount and a date.")
	if has_amount and paid < 0:
		raise CollectionError("Promise amount cannot be negative.")
	if has_amount != bool(promised_on):
		raise CollectionError("A promise needs an amount and a date.")
	if has_amount and paid <= 0:
		raise CollectionError("A promise needs an amount and a date.")
	return (paid or 0, promised_on)


def _profile(source, customer) -> dict:
	return {
		"customer": customer,
		"customer_name": clean_text(source.get("customer_name")) or customer,
		"customer_group": clean_text(source.get("customer_group")),
		"territory": clean_text(source.get("territory")),
		"disabled": as_flag(source.get("disabled")),
	}


def _invoice(source) -> dict:
	return {
		"sales_invoice": clean_text(source.get("sales_invoice") or source.get("name")),
		"customer": clean_text(source.get("customer")),
		"company": clean_text(source.get("company")),
		"posting_date": _date_text(source.get("posting_date")),
		"due_date": _date_text(source.get("due_date")),
		"outstanding": _money_value(source.get("outstanding") if source.get("outstanding") not in (None, "") else source.get("outstanding_amount")),
	}


def _call_stamp(source) -> dict:
	when = _as_datetime(source.get("call_datetime") or source.get("call_time"))
	return {
		"name": clean_text(source.get("name")),
		"customer": clean_text(source.get("customer")),
		"company": clean_text(source.get("company")),
		"call_time": _datetime_text(when) if when else "",
		"outcome": clean_text(source.get("outcome")),
		"direction": clean_text(source.get("direction")),
		"phone": clean_text(source.get("phone")),
		"contact_person": clean_text(source.get("contact_person")),
		"notes": clean_text(source.get("notes")),
		"collector": clean_text(source.get("collector")),
		"promise_amount": _money_value(source.get("promise_amount")),
		"promise_date": _date_text(source.get("promise_date")),
		"next_follow_up": _date_text(source.get("next_follow_up")),
		"statement_sent_to": clean_text(source.get("statement_sent_to")),
		"payment_entry": clean_text(source.get("payment_entry")),
		"collection_report": clean_text(source.get("collection_report")),
	}


def _report_stamp(source) -> dict:
	return {
		"name": clean_text(source.get("name")),
		"customer": clean_text(source.get("customer")),
		"report_type": clean_text(source.get("report_type")),
		"report_date": _date_text(source.get("report_date")),
		"status": clean_text(source.get("status")),
		"sales_invoice": clean_text(source.get("sales_invoice")),
		"amount": _money_value(source.get("amount")),
		"summary": clean_text(source.get("summary")),
		"dispute": clean_text(source.get("dispute")),
		"collection_call": clean_text(source.get("collection_call")),
	}


def _payment(source) -> dict:
	return {
		"name": clean_text(source.get("name")),
		"posting_date": _date_text(source.get("posting_date")),
		"paid_amount": _money_value(source.get("paid_amount")),
		"mode_of_payment": clean_text(source.get("mode_of_payment")),
	}


def _dispute(source) -> dict:
	return {
		"name": clean_text(source.get("name")),
		"sales_invoice": clean_text(source.get("sales_invoice")),
		"status": clean_text(source.get("status") or "Open"),
		"reason": clean_text(source.get("reason")),
	}


def _queue_haystack(card) -> str:
	return " ".join(
		[
			card.get("customer") or "",
			card.get("customer_name") or "",
			card.get("customer_group") or "",
			card.get("territory") or "",
			card.get("last_outcome") or "",
		]
	).casefold()


def _statement_table(rows, with_balance) -> str:
	headers = ["Posting Date", "Sales Invoice", "Due Date", "Outstanding"]
	if with_balance:
		headers.append("Running Balance")
	head = "".join(f"<th>{html.escape(label)}</th>" for label in headers)
	body = []
	for row in rows:
		cells = [
			row.get("posting_date") or "",
			row.get("sales_invoice") or "",
			row.get("due_date") or "",
			_money(row.get("outstanding")),
		]
		if with_balance:
			cells.append("" if row.get("running_balance") is None else _money(row.get("running_balance")))
		body.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells) + "</tr>")
	if not body:
		body.append(f'<tr><td colspan="{len(headers)}">No invoices are due.</td></tr>')
	return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _unique(values) -> list:
	seen = []
	for value in values or []:
		text = clean_text(value)
		if text and text not in seen:
			seen.append(text)
	return seen


def _email_ok(value) -> bool:
	if " " in value or value.count("@") != 1:
		return False
	local, domain = value.split("@")
	return bool(local and domain and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def _optional_amount(value):
	if value is None or value == "":
		return None
	return _money_value(value)


def _money_value(value) -> float:
	if value is None or value == "":
		return 0.0
	try:
		return round(float(value), 2)
	except (TypeError, ValueError) as exc:
		raise CollectionError("Enter an amount.") from exc


def _money(value) -> str:
	return f"{_money_value(value):,.2f}"


def _optional_date(value, label):
	if value is None or clean_text(value) == "":
		return None
	parsed = _as_date(value)
	if not parsed:
		raise CollectionError(f"{label} is not a date.")
	return parsed.isoformat()


def _optional_datetime(value, label):
	if value is None or clean_text(value) == "":
		return None
	parsed = _as_datetime(value)
	if not parsed:
		raise CollectionError(f"{label} is not a date.")
	return _datetime_text(parsed)


def _date_text(value):
	if value is None or clean_text(value) == "":
		return None
	parsed = _as_date(value)
	if not parsed:
		return None
	return parsed.isoformat()


def _datetime_text(value) -> str:
	return value.strftime("%Y-%m-%d %H:%M:%S")


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
		raise CollectionError("Use a date like 2026-04-01.") from exc


def _as_datetime(value):
	if isinstance(value, datetime):
		return value.replace(microsecond=0)
	if isinstance(value, date):
		return datetime(value.year, value.month, value.day)
	text = clean_text(value).replace("T", " ")
	if not text:
		return None
	if len(text) == 10:
		parsed = _as_date(text)
		return datetime(parsed.year, parsed.month, parsed.day)
	for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
		try:
			return datetime.strptime(text[:size], fmt)
		except ValueError:
			continue
	raise CollectionError("Use a date and time like 2026-04-01 09:30:00.")
