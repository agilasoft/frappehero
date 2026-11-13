# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Collections Desk: the call queue, the client file, and the actions on a call."""

import frappe
from frappe import _
from frappe.utils import now, today

from frappehero.collections_desk.logic import (
	CollectionError,
	allocate_receipt,
	assert_invoice_for_customer,
	assemble_client,
	build_queue,
	dispute_from_report,
	normalize_call,
	normalize_report,
	queue_summary,
	statement_email,
)
from frappehero.dispute_desk.api import aging_rows, open_dispute_rows, receivable_invoices, statement_rows
from frappehero.dispute_desk.logic import DisputeError
from frappehero.flags import as_flag, clean_text, parse_payload

STAFF = ("System Manager", "Accounts Manager", "Accounts User")


def _staff():
	frappe.only_for(list(STAFF))


@frappe.whitelist()
def get_queue(company: str | None = None, text: str | None = None, overdue_only=0, followups_only=0, mine=0) -> dict:
	"""Customers with an open balance, and customers whose follow-up is due."""
	_staff()
	company_name = clean_text(company)
	if not company_name:
		return {"rows": [], "summary": _empty_summary()}
	invoices = receivable_invoices(company_name)
	calls = _calls(company_name)
	customers = _customer_rows(_ids(invoices, calls))
	current = today()
	try:
		rows = build_queue(
			customers,
			invoices,
			calls,
			current,
			text=text,
			overdue_only=overdue_only,
			followups_only=followups_only,
			collector=frappe.session.user if as_flag(mine) else "",
		)
		summary = queue_summary(rows, calls, current)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	return {"rows": rows, "summary": summary}


@frappe.whitelist()
def get_client(company: str, customer: str) -> dict:
	"""Credit, invoices, receipts, disputes, calls, and reports for one customer."""
	_staff()
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	profile, phones, emails, address = _customer_file(customer_name)
	invoices = [row for row in receivable_invoices(company_name, customer_name) if row["customer"] == customer_name]
	disputes = _disputes(company_name, customer_name)
	current = today()
	try:
		aging = aging_rows(company_name, customer_name, current)
		client = assemble_client(
			profile,
			{"credit_limit": _credit_limit(customer_name, company_name), "outstanding": _outstanding(invoices)},
			address,
			phones,
			emails,
			invoices,
			disputes,
			_payments(company_name, customer_name),
			_calls(company_name, customer_name),
			_reports(company_name, customer_name),
			aging,
		)
	except (CollectionError, DisputeError) as exc:
		frappe.throw(_(str(exc)))
	return client


@frappe.whitelist()
def save_call(
	company: str,
	customer: str,
	call_datetime: str,
	direction: str | None = None,
	phone: str | None = None,
	contact_person: str | None = None,
	outcome: str | None = None,
	notes: str | None = None,
	promise_amount=None,
	promise_date: str | None = None,
	next_follow_up: str | None = None,
) -> dict:
	"""Log one collection call."""
	_staff()
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	try:
		fields = normalize_call(
			{
				"company": company_name,
				"customer": customer_name,
				"call_datetime": call_datetime,
				"direction": direction,
				"phone": phone,
				"contact_person": contact_person,
				"outcome": outcome,
				"notes": notes,
				"promise_amount": promise_amount,
				"promise_date": promise_date,
				"next_follow_up": next_follow_up,
				"collector": frappe.session.user,
			}
		)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	doc = frappe.new_doc("Hero Collection Call")
	_apply(doc, fields)
	doc.insert(ignore_permissions=True)
	return _call_summary(doc)


@frappe.whitelist()
def preview_statement(company: str, customer: str) -> dict:
	"""The statement of account for the customer, including disputed lines."""
	_staff()
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	try:
		return statement_rows(company_name, customer_name)
	except DisputeError as exc:
		frappe.throw(_(str(exc)))


@frappe.whitelist()
def send_statement(
	company: str,
	customer: str,
	recipient: str | None = None,
	call_name: str | None = None,
) -> dict:
	"""Email the statement and, when a call is open, record who received it."""
	_staff()
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	_profile, _phones, emails, _address = _customer_file(customer_name)
	try:
		statement = statement_rows(company_name, customer_name)
	except DisputeError as exc:
		frappe.throw(_(str(exc)))
	customer_label = frappe.db.get_value("Customer", customer_name, "customer_name") or customer_name
	try:
		notice = statement_email(
			statement,
			customer_label,
			company_name,
			clean_text(recipient) or (emails[0] if emails else ""),
		)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	frappe.sendmail(
		recipients=[notice["recipient"]],
		subject=notice["subject"],
		message=notice["message"],
		delayed=False,
	)
	if clean_text(call_name):
		_stamp_call(
			call_name,
			company_name,
			customer_name,
			{"statement_sent_to": notice["recipient"], "statement_sent_on": now()},
		)
	return {"recipient": notice["recipient"], "amount_due": notice["amount_due"], "subject": notice["subject"]}


@frappe.whitelist()
def create_report(
	company: str,
	customer: str,
	report_type: str,
	summary: str,
	sales_invoice: str | None = None,
	amount=None,
	call_name: str | None = None,
	raise_dispute=0,
) -> dict:
	"""Create a claim or an incident. A claim that names one invoice can open a dispute."""
	_staff()
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	invoice_name = _require_invoice(company_name, customer_name, sales_invoice, submitted=as_flag(raise_dispute))
	try:
		fields = normalize_report(
			{
				"company": company_name,
				"customer": customer_name,
				"report_type": report_type,
				"report_date": today(),
				"summary": summary,
				"sales_invoice": invoice_name,
				"amount": amount,
				"collection_call": clean_text(call_name),
				"status": "Open",
			},
			is_new=True,
		)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	doc = frappe.new_doc("Hero Collection Report")
	_apply(doc, fields)
	doc.insert(ignore_permissions=True)
	dispute_name = ""
	if as_flag(raise_dispute):
		dispute_name = _raise_dispute(doc)
	if clean_text(call_name):
		_stamp_call(call_name, company_name, customer_name, {"collection_report": doc.name})
	return _report_summary(doc, dispute_name)


@frappe.whitelist()
def record_payment(
	company: str,
	customer: str,
	amount,
	invoices,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	call_name: str | None = None,
) -> dict:
	"""Draft a Receive payment for the invoices the staff picked, and link it on the call."""
	_staff()
	if not frappe.has_permission("Payment Entry", "create"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	company_name, customer_name = _party(company, customer)
	_require_customer(customer_name)
	posted = clean_text(posting_date) or today()
	selected = _selected_invoices(company_name, customer_name, parse_payload(invoices, []))
	company_currency = _company_value(company_name, "default_currency")
	try:
		allocation = allocate_receipt(amount, selected, company_currency)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	bank = _company_value(company_name, "default_bank_account") or _company_value(company_name, "default_cash_account")
	if not bank:
		frappe.throw(_("Set a default bank or cash account on {0} before recording a payment.").format(company_name))
	if not allocation["account"]:
		frappe.throw(_("The selected invoices have no receivable account."))
	payment = frappe.new_doc("Payment Entry")
	payment.payment_type = "Receive"
	payment.party_type = "Customer"
	payment.party = customer_name
	payment.company = company_name
	payment.posting_date = posted
	payment.paid_from = allocation["account"]
	payment.paid_to = bank
	payment.paid_amount = allocation["amount"]
	payment.received_amount = allocation["amount"]
	mode = clean_text(mode_of_payment)
	if mode:
		payment.mode_of_payment = mode
	if clean_text(call_name):
		payment.remarks = _("Collection call {0}.").format(clean_text(call_name))
	for row in allocation["references"]:
		payment.append(
			"references",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": row["sales_invoice"],
				"due_date": row["due_date"],
				"total_amount": row["grand_total"],
				"outstanding_amount": row["outstanding"],
				"allocated_amount": row["allocated"],
			},
		)
	payment.insert()
	if clean_text(call_name):
		_stamp_call(call_name, company_name, customer_name, {"payment_entry": payment.name})
	return {
		"name": payment.name,
		"amount": allocation["amount"],
		"allocated": allocation["allocated"],
		"references": [
			{"sales_invoice": row["sales_invoice"], "allocated": row["allocated"]} for row in allocation["references"]
		],
	}


def _raise_dispute(doc) -> str:
	from frappehero.dispute_desk.api import raise_dispute

	_require_invoice(doc.company, doc.customer, doc.sales_invoice, submitted=True)
	try:
		request = dispute_from_report(doc.as_dict())
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	dispute = raise_dispute(
		reference_doctype=request["reference_doctype"],
		reference_name=doc.name,
		sales_invoice=request["sales_invoice"],
		company=request["company"],
		customer=request["customer"],
		reason=request["reason"],
		source_module=request["source_module"],
	)
	doc.dispute = dispute["name"]
	doc.save(ignore_permissions=True)
	return dispute["name"]


def _stamp_call(name, company, customer, values) -> None:
	if not frappe.db.exists("Hero Collection Call", name):
		frappe.throw(_("Collection call {0} was not found.").format(name))
	doc = frappe.get_doc("Hero Collection Call", name)
	if doc.company != company or doc.customer != customer:
		frappe.throw(_("That call is for a different customer."))
	for key, value in values.items():
		setattr(doc, key, value)
	doc.save(ignore_permissions=True)


def _require_invoice(company, customer, sales_invoice, submitted=False) -> str:
	"""Return the invoice name when it belongs to this customer. Blank stays blank."""
	name = clean_text(sales_invoice)
	if not name:
		return ""
	if not frappe.db.exists("Sales Invoice", name):
		frappe.throw(_("Sales Invoice {0} was not found.").format(name))
	row = frappe.db.get_value("Sales Invoice", name, ["company", "customer", "docstatus"], as_dict=True)
	try:
		assert_invoice_for_customer(
			name,
			company,
			customer,
			row.company,
			row.customer,
			docstatus=row.docstatus,
			submitted=submitted,
		)
	except CollectionError as exc:
		frappe.throw(_(str(exc)))
	return name


def _party(company, customer):
	company_name = clean_text(company)
	customer_name = clean_text(customer)
	if not company_name:
		frappe.throw(_("Company is required."))
	if not customer_name:
		frappe.throw(_("Customer is required."))
	return company_name, customer_name


def _require_customer(customer):
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} was not found.").format(customer))
	if not frappe.has_permission("Customer", "read", customer):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _apply(doc, fields):
	for key, value in fields.items():
		if key == "previous_status":
			continue
		setattr(doc, key, value)


def _ids(invoices, calls):
	found = {clean_text(row.get("customer")) for row in invoices}
	found.update(clean_text(row.get("customer")) for row in calls)
	return [customer for customer in found if customer]


def _customer_rows(names) -> list:
	if not names or not frappe.db.table_exists("Customer"):
		return []
	return frappe.get_all(
		"Customer",
		filters={"name": ["in", names]},
		fields=["name", "customer_name", "customer_group", "territory", "disabled"],
		limit_page_length=0,
		ignore_permissions=True,
	)


def _customer_file(customer):
	row = frappe.db.get_value(
		"Customer",
		customer,
		[
			"name",
			"customer_name",
			"customer_group",
			"territory",
			"tax_id",
			"disabled",
			"mobile_no",
			"email_id",
			"customer_primary_contact",
			"customer_primary_address",
		],
		as_dict=True,
	)
	phones = [row.mobile_no] if row.mobile_no else []
	emails = [row.email_id] if row.email_id else []
	contact = clean_text(row.customer_primary_contact)
	if contact and frappe.db.exists("Contact", contact):
		phone, mobile, email = frappe.db.get_value("Contact", contact, ["phone", "mobile_no", "email_id"])
		phones.extend([phone, mobile])
		emails.append(email)
		if frappe.db.table_exists("Contact Phone"):
			phones.extend(
				frappe.get_all("Contact Phone", filters={"parent": contact}, pluck="phone", ignore_permissions=True)
			)
		if frappe.db.table_exists("Contact Email"):
			emails.extend(
				frappe.get_all(
					"Contact Email", filters={"parent": contact}, pluck="email_id", ignore_permissions=True
				)
			)
	address = []
	address_name = clean_text(row.customer_primary_address)
	if address_name and frappe.db.exists("Address", address_name):
		place = frappe.db.get_value(
			"Address",
			address_name,
			["address_line1", "address_line2", "city", "state", "pincode", "country"],
			as_dict=True,
		)
		city = " ".join(part for part in (place.city, place.state, place.pincode) if part)
		address = [place.address_line1, place.address_line2, city, place.country]
	return row, phones, emails, address


def _credit_limit(customer, company):
	if not frappe.db.table_exists("Customer Credit Limit"):
		return None
	return frappe.db.get_value(
		"Customer Credit Limit",
		{"parent": customer, "parenttype": "Customer", "company": company},
		"credit_limit",
	)


def _outstanding(invoices) -> float:
	return round(sum(float(row.get("outstanding") or 0) for row in invoices), 2)


def _payments(company, customer) -> list:
	if not frappe.db.table_exists("Payment Entry"):
		return []
	return frappe.get_all(
		"Payment Entry",
		filters={
			"docstatus": 1,
			"company": company,
			"party_type": "Customer",
			"party": customer,
			"payment_type": "Receive",
		},
		fields=["name", "posting_date", "paid_amount", "mode_of_payment"],
		order_by="posting_date desc",
		limit=8,
		ignore_permissions=True,
	)


def _calls(company, customer=None) -> list:
	if not frappe.db.table_exists("Hero Collection Call"):
		return []
	filters = {"company": company}
	if customer:
		filters["customer"] = customer
	return frappe.get_all(
		"Hero Collection Call",
		filters=filters,
		fields=[
			"name",
			"customer",
			"company",
			"call_datetime",
			"direction",
			"phone",
			"contact_person",
			"outcome",
			"notes",
			"collector",
			"promise_amount",
			"promise_date",
			"next_follow_up",
			"statement_sent_to",
			"payment_entry",
			"collection_report",
		],
		order_by="call_datetime desc",
		limit_page_length=0,
		ignore_permissions=True,
	)


def _reports(company, customer) -> list:
	if not frappe.db.table_exists("Hero Collection Report"):
		return []
	return frappe.get_all(
		"Hero Collection Report",
		filters={"company": company, "customer": customer},
		fields=[
			"name",
			"customer",
			"report_type",
			"report_date",
			"status",
			"sales_invoice",
			"amount",
			"summary",
			"dispute",
			"collection_call",
		],
		order_by="report_date desc",
		limit_page_length=0,
		ignore_permissions=True,
	)


def _disputes(company, customer) -> list:
	rows = open_dispute_rows(company, customer)
	names = [row.name if hasattr(row, "name") else row.get("name") for row in rows]
	names = [name for name in names if name]
	reasons = {}
	if names and frappe.db.table_exists("Hero Dispute"):
		for row in frappe.get_all(
			"Hero Dispute",
			filters={"name": ["in", names]},
			fields=["name", "reason"],
			limit_page_length=0,
			ignore_permissions=True,
		):
			reasons[row.name] = row.reason
	enriched = []
	for row in rows:
		item = dict(row)
		item["reason"] = reasons.get(item.get("name"), "")
		enriched.append(item)
	return enriched


def _selected_invoices(company, customer, picked) -> list:
	wanted = []
	for item in picked or []:
		if isinstance(item, str):
			name = clean_text(item)
		else:
			name = clean_text((item or {}).get("sales_invoice") or (item or {}).get("name"))
		if name:
			wanted.append(name)
	if not wanted:
		return []
	details = {}
	if frappe.db.table_exists("Sales Invoice"):
		for row in frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", wanted], "company": company, "customer": customer, "docstatus": 1},
			fields=["name", "debit_to", "grand_total", "outstanding_amount", "due_date", "currency", "customer", "company"],
			limit_page_length=0,
			ignore_permissions=True,
		):
			details[row.name] = row
	chosen = []
	for name in wanted:
		row = details.get(name)
		if not row or float(row.outstanding_amount or 0) <= 0:
			continue
		chosen.append(
			{
				"sales_invoice": row.name,
				"customer": row.customer,
				"company": row.company,
				"due_date": row.due_date,
				"outstanding": row.outstanding_amount,
				"account": row.debit_to,
				"currency": row.currency,
				"grand_total": row.grand_total,
			}
		)
	return chosen


def _company_value(company, fieldname) -> str:
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} was not found.").format(company))
	meta = frappe.get_meta("Company")
	if not meta.has_field(fieldname):
		return ""
	return clean_text(frappe.db.get_value("Company", company, fieldname))


def _empty_summary():
	return {"customers": 0, "amount_due": 0, "promises_due": 0, "calls_today": 0}


def _call_summary(doc) -> dict:
	return {
		"name": doc.name,
		"company": doc.company,
		"customer": doc.customer,
		"call_datetime": doc.call_datetime,
		"direction": doc.direction,
		"phone": doc.phone,
		"contact_person": doc.contact_person,
		"outcome": doc.outcome,
		"notes": doc.notes,
		"collector": doc.collector,
		"promise_amount": doc.promise_amount,
		"promise_date": doc.promise_date,
		"next_follow_up": doc.next_follow_up,
		"statement_sent_to": doc.statement_sent_to,
		"payment_entry": doc.payment_entry,
		"collection_report": doc.collection_report,
	}


def _report_summary(doc, dispute_name="") -> dict:
	return {
		"name": doc.name,
		"company": doc.company,
		"customer": doc.customer,
		"report_type": doc.report_type,
		"report_date": doc.report_date,
		"status": doc.status,
		"sales_invoice": doc.sales_invoice,
		"amount": doc.amount,
		"summary": doc.summary,
		"collection_call": doc.collection_call,
		"dispute": dispute_name or doc.dispute,
	}
