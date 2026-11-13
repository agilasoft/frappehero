# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.collections_desk.logic import (
	CollectionError,
	allocate_receipt,
	assemble_client,
	build_queue,
	dispute_from_report,
	freeze_call,
	freeze_report,
	normalize_call,
	normalize_report,
	queue_summary,
	statement_email,
	tel_href,
)


def _call(**overrides):
	row = {
		"company": "Co",
		"customer": "Acme",
		"call_datetime": "2026-04-01 09:30:00",
		"direction": "Outbound",
		"collector": "collector@example.com",
		"phone": "+63 917 000 0000",
		"contact_person": "Ana",
		"outcome": "Reached",
		"notes": "Asked for the statement.",
	}
	row.update(overrides)
	return normalize_call(row)


class TestNormalizeCall(unittest.TestCase):
	def test_outbound_call_keeps_the_number_and_the_note(self):
		call = _call()
		self.assertEqual(call["phone"], "+63 917 000 0000")
		self.assertEqual(call["call_datetime"], "2026-04-01 09:30:00")
		self.assertEqual(call["promise_amount"], 0)
		self.assertIsNone(call["promise_date"])

	def test_promise_needs_an_amount_and_a_date(self):
		call = _call(outcome="Promised", notes="Will pay Friday.", promise_amount="1500.5", promise_date="2026-04-03")
		self.assertEqual(call["promise_amount"], 1500.5)
		self.assertEqual(call["promise_date"], "2026-04-03")
		with self.assertRaises(CollectionError):
			_call(outcome="Promised", notes="Soon.", promise_amount=100)
		with self.assertRaises(CollectionError):
			_call(outcome="No Answer", notes="", promise_amount=100, promise_date="2026-04-03")

	def test_missed_call_can_omit_the_note_and_inbound_can_omit_the_number(self):
		missed = _call(outcome="No Answer", notes="", phone="917")
		self.assertEqual(missed["notes"], "")
		inbound = _call(direction="Inbound", phone="", outcome="Callback", notes="Asked us to call back.", next_follow_up="2026-04-02")
		self.assertEqual(inbound["phone"], "")
		self.assertEqual(inbound["next_follow_up"], "2026-04-02")
		with self.assertRaises(CollectionError):
			_call(direction="Outbound", phone="")
		with self.assertRaises(CollectionError):
			_call(outcome="Callback", notes="Call back.", next_follow_up="")

	def test_company_and_customer_stay_on_a_saved_call(self):
		saved = _call()
		freeze_call(saved, saved)
		with self.assertRaises(CollectionError):
			freeze_call(saved, {**saved, "customer": "Other"})


class TestReport(unittest.TestCase):
	def test_new_report_starts_open_and_a_claim_can_raise_a_dispute(self):
		report = normalize_report(
			{
				"company": "Co",
				"customer": "Acme",
				"report_type": "Claim",
				"report_date": "2026-04-01",
				"summary": "Short payment on the invoice.",
				"sales_invoice": "SINV-1",
				"amount": "200",
			},
			is_new=True,
		)
		self.assertEqual(report["status"], "Open")
		self.assertEqual(report["amount"], 200)
		request = dispute_from_report({**report, "name": "RPT-1"})
		self.assertEqual(request["sales_invoice"], "SINV-1")
		self.assertEqual(request["reference_doctype"], "Hero Collection Report")
		self.assertEqual(request["source_module"], "Collections Desk")
		with self.assertRaises(CollectionError):
			dispute_from_report({**report, "report_type": "Incident", "name": "RPT-1"})
		with self.assertRaises(CollectionError):
			normalize_report({**report, "status": "Closed"}, is_new=True)

	def test_invoice_stays_once_a_dispute_is_opened(self):
		previous = {"company": "Co", "customer": "Acme", "sales_invoice": "SINV-1", "dispute": "DISP-1"}
		freeze_report(previous, previous)
		with self.assertRaises(CollectionError):
			freeze_report(previous, {**previous, "sales_invoice": "SINV-2"})


class TestQueue(unittest.TestCase):
	def setUp(self):
		self.customers = [
			{"name": "Acme", "customer_name": "Acme Freight", "customer_group": "Commercial", "territory": "North"},
			{"name": "Beta", "customer_name": "Beta Lines", "customer_group": "Commercial", "territory": "South"},
			{"name": "Cairn", "customer_name": "Cairn Co", "customer_group": "Commercial", "territory": "North"},
		]
		self.invoices = [
			{"sales_invoice": "SINV-1", "customer": "Acme", "outstanding": 100, "due_date": "2026-03-01"},
			{"sales_invoice": "SINV-2", "customer": "Acme", "outstanding": 40, "due_date": "2026-04-15"},
			{"sales_invoice": "SINV-3", "customer": "Beta", "outstanding": 80, "due_date": "2026-04-20"},
		]
		self.calls = [
			{
				"name": "CALL-1",
				"customer": "Acme",
				"call_datetime": "2026-04-01 09:00:00",
				"outcome": "Promised",
				"collector": "ada@example.com",
				"promise_amount": 100,
				"promise_date": "2026-04-02",
				"next_follow_up": "2026-04-02",
			},
			{
				"name": "CALL-2",
				"customer": "Cairn",
				"call_datetime": "2026-04-02 11:00:00",
				"outcome": "Callback",
				"collector": "ada@example.com",
				"next_follow_up": "2026-04-02",
			},
		]

	def test_follow_up_comes_before_the_older_balance(self):
		rows = build_queue(self.customers, self.invoices, self.calls, "2026-04-02")
		self.assertEqual([row["customer"] for row in rows], ["Acme", "Cairn", "Beta"])
		acme = rows[0]
		self.assertEqual(acme["outstanding"], 140)
		self.assertEqual(acme["oldest_due"], "2026-03-01")
		self.assertEqual(acme["last_outcome"], "Promised")
		self.assertEqual(acme["overdue"], 1)
		self.assertEqual(rows[1]["outstanding"], 0)
		self.assertEqual(rows[1]["follow_up_due"], 1)

	def test_filters_narrow_the_queue(self):
		overdue = build_queue(self.customers, self.invoices, self.calls, "2026-04-02", overdue_only=1)
		self.assertEqual([row["customer"] for row in overdue], ["Acme"])
		followups = build_queue(self.customers, self.invoices, self.calls, "2026-04-02", followups_only=1)
		self.assertEqual([row["customer"] for row in followups], ["Acme", "Cairn"])
		mine = build_queue(self.customers, self.invoices, self.calls, "2026-04-02", collector="ada@example.com")
		self.assertEqual([row["customer"] for row in mine], ["Acme", "Cairn"])
		found = build_queue(self.customers, self.invoices, self.calls, "2026-04-02", text="beta")
		self.assertEqual([row["customer"] for row in found], ["Beta"])

	def test_summary_counts_promises_and_calls_logged_today(self):
		rows = build_queue(self.customers, self.invoices, self.calls, "2026-04-02")
		summary = queue_summary(rows, self.calls, "2026-04-02")
		self.assertEqual(summary["customers"], 3)
		self.assertEqual(summary["amount_due"], 220)
		self.assertEqual(summary["promises_due"], 1)
		self.assertEqual(summary["calls_today"], 1)


class TestClientFile(unittest.TestCase):
	def test_open_dispute_is_marked_on_the_invoice(self):
		client = assemble_client(
			{"name": "Acme", "customer_name": "Acme Freight", "tax_id": "TIN-1"},
			{"credit_limit": 5000, "outstanding": 140},
			["1 Dock", "", "Manila"],
			["+63 917 000 0000", "+63 917 000 0000", ""],
			["ada@acme.test"],
			[
				{"sales_invoice": "SINV-2", "customer": "Acme", "outstanding": 40, "due_date": "2026-04-15"},
				{"sales_invoice": "SINV-1", "customer": "Acme", "outstanding": 100, "due_date": "2026-03-01"},
			],
			[{"name": "DISP-1", "sales_invoice": "SINV-1", "status": "Open", "reason": "Short"}],
			[{"name": "PE-1", "posting_date": "2026-03-15", "paid_amount": 50, "mode_of_payment": "Cash"}],
			[{"name": "CALL-1", "customer": "Acme", "call_datetime": "2026-04-01 09:00:00", "outcome": "Reached"}],
			[{"name": "RPT-1", "customer": "Acme", "report_type": "Incident", "report_date": "2026-04-01", "status": "Open", "summary": "No answer yesterday."}],
			{"amount_due": 40, "buckets": {"Current": 40}},
		)
		self.assertEqual(client["phone"], "+63 917 000 0000")
		self.assertEqual(client["tel"], "tel:+639170000000")
		self.assertEqual(client["email"], "ada@acme.test")
		self.assertEqual(client["address"], ["1 Dock", "Manila"])
		self.assertEqual([row["sales_invoice"] for row in client["invoices"]], ["SINV-1", "SINV-2"])
		self.assertEqual(client["invoices"][0]["disputed"], 1)
		self.assertEqual(client["invoices"][1]["disputed"], 0)
		self.assertEqual(client["credit_limit"], 5000)
		self.assertEqual(client["calls"][0]["outcome"], "Reached")


class TestStatementAndReceipt(unittest.TestCase):
	def test_statement_email_escapes_the_customer_and_needs_an_address(self):
		notice = statement_email(
			{
				"rows": [
					{
						"posting_date": "2026-03-01",
						"sales_invoice": "SINV-1",
						"due_date": "2026-03-15",
						"outstanding": 100,
						"running_balance": 100,
					}
				],
				"disputed_rows": [
					{"posting_date": "2026-03-02", "sales_invoice": "SINV-9", "due_date": "2026-03-20", "outstanding": 20}
				],
				"amount_due": 100,
				"disputed_outstanding": 20,
			},
			"Acme <script>",
			"Co",
			"ada@acme.test",
		)
		self.assertEqual(notice["subject"], "Statement of Account - Acme <script>")
		self.assertIn("Acme &lt;script&gt;", notice["message"])
		self.assertNotIn("<script>", notice["message"])
		self.assertIn("SINV-9", notice["message"])
		self.assertEqual(notice["recipient"], "ada@acme.test")
		self.assertEqual(notice["amount_due"], 100)
		with self.assertRaises(CollectionError):
			statement_email({"rows": [], "amount_due": 0}, "Acme", "Co", "not-an-email")

	def test_receipt_pays_the_oldest_invoice_first(self):
		result = allocate_receipt(
			120,
			[
				{"sales_invoice": "SINV-2", "outstanding": 80, "due_date": "2026-04-01", "account": "Debtors", "currency": "PHP", "grand_total": 80},
				{"sales_invoice": "SINV-1", "outstanding": 100, "due_date": "2026-03-01", "account": "Debtors", "currency": "PHP", "grand_total": 100},
			],
			"PHP",
		)
		self.assertEqual([(row["sales_invoice"], row["allocated"]) for row in result["references"]], [("SINV-1", 100), ("SINV-2", 20)])
		self.assertEqual(result["account"], "Debtors")
		self.assertEqual(result["allocated"], 120)

	def test_receipt_refuses_an_extra_a_blank_selection_and_a_split_account(self):
		invoices = [
			{"sales_invoice": "SINV-1", "outstanding": 100, "due_date": "2026-03-01", "account": "Debtors", "currency": "PHP"}
		]
		with self.assertRaises(CollectionError):
			allocate_receipt(150, invoices, "PHP")
		with self.assertRaises(CollectionError):
			allocate_receipt(0, invoices, "PHP")
		with self.assertRaises(CollectionError):
			allocate_receipt(10, [], "PHP")
		with self.assertRaises(CollectionError):
			allocate_receipt(
				10,
				[
					{"sales_invoice": "SINV-1", "outstanding": 10, "due_date": "2026-03-01", "account": "Debtors", "currency": "PHP"},
					{"sales_invoice": "SINV-2", "outstanding": 10, "due_date": "2026-03-02", "account": "Debtors USD", "currency": "PHP"},
				],
				"PHP",
			)
		with self.assertRaises(CollectionError):
			allocate_receipt(
				10,
				[{"sales_invoice": "SINV-1", "outstanding": 10, "due_date": "2026-03-01", "account": "Debtors", "currency": "USD"}],
				"PHP",
			)


class TestPhoneLink(unittest.TestCase):
	def test_tel_link_keeps_a_leading_plus_and_the_digits(self):
		self.assertEqual(tel_href("+63 917 000 0000"), "tel:+639170000000")
		self.assertEqual(tel_href("desk"), "")


if __name__ == "__main__":
	unittest.main()
