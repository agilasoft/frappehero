# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest
from pathlib import Path

from frappehero.dispute_desk.logic import (
	DISPUTED_SECTION,
	STANDARD_ACTIONS,
	DisputeError,
	aging_bucket,
	close_dispute,
	dispute_tab_field_order,
	filter_disputes,
	raise_dispute,
	receivables_aging,
	rows_for_desk,
	sales_invoice_dispute_fields,
	sales_invoice_dispute_tab,
	statement_of_account,
)


def _action(invoice, kind, active=1, **extra):
	row = {
		"sales_invoice": invoice,
		"kind": kind,
		"source_doctype": extra.pop("source_doctype", "Hero Invoice Action"),
		"source_name": extra.pop("source_name", kind),
		"state": extra.pop("state", "Active"),
		"active": active,
		"invoice_action": extra.pop("invoice_action", f"{invoice}-{kind}"),
	}
	row.update(extra)
	return row


def _raise(actions, existing=None, **overrides):
	payload = {
		"reference_doctype": "Shipment",
		"reference_name": "SHIP-1",
		"sales_invoice": "SINV-1",
		"company": "Co",
		"customer": "Acme",
		"reason": "Short delivery",
		"source_module": "Logistics",
		"dispute_date": "2026-04-01",
		"existing_disputes": existing or [],
		"actions": actions,
	}
	payload.update(overrides)
	return raise_dispute(**payload)


class TestRaiseDispute(unittest.TestCase):
	def test_release_includes_custom_kind_and_leaves_the_rest(self):
		actions = [
			_action("SINV-1", "Hold", invoice_action="ACT-H"),
			_action("SINV-1", "Collection", invoice_action="ACT-C"),
			_action("SINV-1", "Dunning", source_doctype="Dunning", source_name="DUN-1", state="Unresolved"),
			_action("SINV-1", "Legal", invoice_action="ACT-L", state="Queued"),
			_action("SINV-1", "Hold", active=0, invoice_action="ACT-OLD", state="Released"),
			_action("SINV-9", "Collection", invoice_action="ACT-OTHER"),
		]
		result = _raise(actions)
		released = {(row["action_kind"], row["source_name"]) for row in result["dispute"]["releases"]}
		self.assertEqual(
			released,
			{("Hold", "Hold"), ("Collection", "Collection"), ("Dunning", "DUN-1"), ("Legal", "Legal")},
		)
		by_action = {row["invoice_action"]: row["active"] for row in result["actions"]}
		self.assertEqual(by_action["ACT-H"], 0)
		self.assertEqual(by_action["ACT-C"], 0)
		self.assertEqual(by_action["ACT-L"], 0)
		self.assertEqual(by_action["ACT-OLD"], 0)
		self.assertEqual(by_action["ACT-OTHER"], 1)
		dunning = next(row for row in result["dispute"]["releases"] if row["action_kind"] == "Dunning")
		self.assertEqual(dunning["previous_state"], "Unresolved")
		self.assertEqual(result["dispute"]["reference_doctype"], "Shipment")
		self.assertEqual(result["dispute"]["status"], "Open")
		self.assertTrue(set(STANDARD_ACTIONS).issubset(kind for kind, _name in released))

	def test_sales_invoice_source_defaults_the_invoice(self):
		result = _raise([], reference_doctype="Sales Invoice", reference_name="SINV-9", sales_invoice="")
		self.assertEqual(result["dispute"]["sales_invoice"], "SINV-9")
		self.assertEqual(result["dispute"]["releases"], [])

	def test_second_open_dispute_is_rejected(self):
		existing = [{"name": "DISP-1", "sales_invoice": "SINV-1", "status": "Open"}]
		with self.assertRaises(DisputeError):
			_raise([], existing)
		resolved = [{"name": "DISP-1", "sales_invoice": "SINV-1", "status": "Resolved"}]
		again = _raise([], resolved)
		self.assertEqual(again["dispute"]["status"], "Open")

	def test_close_leaves_actions_released(self):
		result = _raise([_action("SINV-1", "Hold"), _action("SINV-1", "Dunning")])
		closed = close_dispute(result["dispute"], "Resolved")
		self.assertEqual(closed["status"], "Resolved")
		self.assertEqual(len(closed["releases"]), 2)
		self.assertTrue(all(row["active"] == 0 for row in result["actions"]))
		cancelled = close_dispute(result["dispute"], "Cancelled")
		self.assertEqual(cancelled["status"], "Cancelled")
		with self.assertRaises(DisputeError):
			close_dispute(closed, "Open")


class TestStatement(unittest.TestCase):
	def _rows(self):
		return [
			_invoice("SINV-1", "2026-01-01", "2026-01-31", 100),
			_invoice("SINV-2", "2026-01-15", "2026-02-15", 40),
			_invoice("SINV-3", "2026-02-01", "2026-03-01", 25),
			_invoice("SINV-4", "2026-03-15", "2026-04-15", 80),
			_invoice("SINV-9", "2026-01-01", "2026-01-31", 999, customer="Other"),
		]

	def test_disputed_section_is_outside_the_amount_due(self):
		disputes = [{"name": "DISP-1", "sales_invoice": "SINV-2", "status": "Open"}]
		result = statement_of_account(
			self._rows(),
			disputes,
			customer="Acme",
			company="Co",
			from_date="2026-01-01",
			to_date="2026-02-28",
		)
		self.assertEqual(result["amount_due"], 125)
		self.assertEqual(result["disputed_outstanding"], 40)
		body = [row["sales_invoice"] for row in result["rows"]]
		self.assertEqual(body, ["SINV-1", "SINV-3"])
		self.assertEqual(result["rows"][0]["running_balance"], 100)
		self.assertEqual(result["rows"][1]["running_balance"], 125)
		self.assertTrue(all(row["section"] == "" for row in result["rows"]))
		disputed = result["disputed_rows"]
		self.assertEqual([row["sales_invoice"] for row in disputed], ["SINV-2"])
		self.assertEqual(disputed[0]["section"], DISPUTED_SECTION)
		self.assertIsNone(disputed[0]["running_balance"])
		self.assertEqual(disputed[0]["outstanding"], 40)
		self.assertEqual(
			[row["sales_invoice"] for row in rows_for_desk(result)],
			["SINV-1", "SINV-3", "SINV-2"],
		)

	def test_resolved_dispute_returns_to_the_statement(self):
		disputes = [{"name": "DISP-1", "sales_invoice": "SINV-2", "status": "Resolved"}]
		result = statement_of_account(
			self._rows(),
			disputes,
			customer="Acme",
			company="Co",
			from_date="2026-01-01",
			to_date="2026-02-28",
		)
		self.assertEqual([row["sales_invoice"] for row in result["rows"]], ["SINV-1", "SINV-2", "SINV-3"])
		self.assertEqual(result["amount_due"], 165)
		self.assertEqual(result["disputed_outstanding"], 0)
		self.assertEqual(result["disputed_rows"], [])
		self.assertTrue(all(row["section"] == "" for row in result["rows"]))


class TestAging(unittest.TestCase):
	def test_bucket_edges(self):
		self.assertEqual(
			[aging_bucket(days) for days in (0, 1, 30, 31, 60, 61, 90, 91)],
			["Current", "1-30", "1-30", "31-60", "31-60", "61-90", "61-90", "91 and over"],
		)

	def test_disputed_invoices_stay_out_of_the_buckets(self):
		rows = [
			_invoice("CUR", "2026-03-01", "2026-04-15", 10),
			_invoice("D30", "2026-02-01", "2026-03-02", 5),
			_invoice("D31", "2026-02-01", "2026-03-01", 20),
			_invoice("D90", "2025-12-01", "2026-01-01", 50),
			_invoice("D91", "2025-01-01", "2025-12-31", 7),
			_invoice("FUTURE", "2026-05-01", "2026-05-15", 15),
		]
		disputes = [{"name": "DISP-1", "sales_invoice": "D90", "status": "Open"}]
		result = receivables_aging(rows, disputes, "2026-04-01", customer="Acme", company="Co")
		self.assertEqual(
			result["buckets"],
			{"Current": 10, "1-30": 5, "31-60": 20, "61-90": 0, "91 and over": 7},
		)
		self.assertEqual(result["amount_due"], 42)
		self.assertEqual(result["disputed_outstanding"], 50)
		names = [row["sales_invoice"] for row in result["rows"]]
		self.assertEqual(names, ["D91", "D30", "D31", "CUR"])
		self.assertTrue(all(not row["section"] for row in result["rows"]))
		disputed = result["disputed_rows"]
		self.assertEqual([row["sales_invoice"] for row in disputed], ["D90"])
		self.assertEqual(disputed[0]["section"], DISPUTED_SECTION)
		self.assertEqual(disputed[0]["outstanding"], 50)
		self.assertEqual(disputed[0]["age_days"], 90)
		self.assertEqual(disputed[0]["days_61_90"], 0)
		self.assertEqual(
			[row["sales_invoice"] for row in rows_for_desk(result)],
			["D91", "D30", "D31", "CUR", "D90"],
		)


class TestDisputeFilters(unittest.TestCase):
	def _rows(self):
		return [
			{
				"name": "DISP-1",
				"company": "Co",
				"customer": "Acme",
				"sales_invoice": "SINV-1",
				"status": "Open",
				"dispute_date": "2026-04-01",
				"reason": "Short delivery",
				"reference_doctype": "Shipment",
				"reference_name": "SHIP-1",
				"source_module": "Logistics",
			},
			{
				"name": "DISP-2",
				"company": "Co",
				"customer": "Other",
				"sales_invoice": "SINV-2",
				"status": "Resolved",
				"dispute_date": "2026-05-01",
				"reason": "Price",
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-2",
				"source_module": "ERPNext",
			},
			{
				"name": "DISP-3",
				"company": "Other Co",
				"customer": "Acme",
				"sales_invoice": "SINV-3",
				"status": "Open",
				"dispute_date": "2026-04-15",
				"reason": "Damage",
				"reference_doctype": "Shipment",
				"reference_name": "SHIP-9",
				"source_module": "Logistics",
			},
		]

	def test_filters_combine(self):
		rows = self._rows()
		self.assertEqual(
			[row["name"] for row in filter_disputes(rows, company="Co", status="Open")],
			["DISP-1"],
		)
		self.assertEqual(
			[row["name"] for row in filter_disputes(rows, status="All")],
			["DISP-1", "DISP-2", "DISP-3"],
		)
		self.assertEqual(
			[row["name"] for row in filter_disputes(rows, text="ship-1")],
			["DISP-1"],
		)
		self.assertEqual(
			[row["name"] for row in filter_disputes(rows, customer="Acme", from_date="2026-04-10", to_date="2026-04-20")],
			["DISP-3"],
		)
		self.assertEqual(filter_disputes(rows, sales_invoice="SINV-2"), [rows[1]])
		self.assertEqual(filter_disputes(rows, text="short"), [rows[0]])

	def test_printouts_section_disputed_transactions(self):
		root = Path(__file__).resolve().parent / "report"
		for name in ("statement_of_account", "receivables_aging"):
			html = (root / name / f"{name}.html").read_text()
			script = (root / name / f"{name}.js").read_text()
			self.assertIn("Disputed Transactions", html)
			self.assertIn("report.disputed_rows", html)
			self.assertIn('row.section !== "Disputed Transactions"', script)
			self.assertNotIn("Section", (root / name / f"{name}.py").read_text().split("def _summary")[0])


class TestSalesInvoiceDisputeTab(unittest.TestCase):
	def test_dispute_tab_stays_out_of_the_invoice_header(self):
		fields = sales_invoice_dispute_fields()
		by_name = {row["fieldname"]: row for row in fields}
		names = [row["fieldname"] for row in fields]
		self.assertEqual(len(names), len(set(names)))
		self.assertEqual(by_name["hero_dispute_tab"]["fieldtype"], "Tab Break")
		self.assertEqual(by_name["hero_dispute_tab"]["label"], "Dispute")
		self.assertEqual(by_name["hero_dispute_tab"]["insert_after"], "connections_tab")
		self.assertEqual(by_name["hero_dispute_section"]["fieldtype"], "Section Break")
		self.assertEqual(by_name["hero_dispute_section"]["insert_after"], "hero_dispute_tab")
		self.assertEqual(by_name["hero_dispute_section"].get("collapsible"), 0)
		self.assertNotIn("customer", [row.get("insert_after") for row in fields])
		self.assertEqual(by_name["hero_credit_section"]["label"], "Credit")
		self.assertEqual(by_name["hero_holds_section"]["label"], "Holds")
		self.assertEqual(by_name["hero_credit_html"]["fieldtype"], "HTML")
		self.assertEqual(by_name["hero_holds_html"]["fieldtype"], "HTML")
		self.assertLess(names.index("hero_dispute_tab"), names.index("hero_dispute_section"))
		self.assertLess(names.index("hero_dispute_column"), names.index("hero_dispute_status"))
		self.assertLess(names.index("hero_credit_section"), names.index("hero_holds_section"))
		self.assertEqual(by_name["hero_dispute"]["options"], "Hero Dispute")
		self.assertEqual(by_name["hero_dispute"]["read_only"], 1)

	def test_saved_field_order_lifts_the_dispute_section_out_of_the_header(self):
		order = [
			"title",
			"customer",
			"customer_name",
			"tax_id",
			"hero_dispute_section",
			"hero_dispute",
			"hero_dispute_status",
			"company",
			"posting_date",
			"is_return",
			"is_debit_note",
			"connections_tab",
			"logistics_tab",
		]
		result = dispute_tab_field_order(order)
		self.assertEqual(
			result,
			[
				"title",
				"customer",
				"customer_name",
				"tax_id",
				"company",
				"posting_date",
				"is_return",
				"is_debit_note",
				"connections_tab",
				"logistics_tab",
				"hero_dispute_tab",
				"hero_dispute_section",
				"hero_dispute",
				"hero_dispute_status",
			],
		)
		self.assertLess(result.index("tax_id"), result.index("company"))
		self.assertLess(result.index("company"), result.index("hero_dispute_tab"))
		self.assertEqual(dispute_tab_field_order(result), result)
		self.assertEqual(dispute_tab_field_order(["customer", "company"]), ["customer", "company"])
		with_credit = dispute_tab_field_order(order + ["hero_credit_section", "hero_holds_html"])
		self.assertEqual(
			with_credit[with_credit.index("hero_dispute_tab") :],
			[
				"hero_dispute_tab",
				"hero_dispute_section",
				"hero_dispute",
				"hero_dispute_status",
				"hero_credit_section",
				"hero_holds_html",
			],
		)

	def test_credit_position_and_credit_notes(self):
		tab = sales_invoice_dispute_tab(
			customer="Acme",
			company="Co",
			currency="PHP",
			credit_limit="1000",
			outstanding=250,
			bypass_credit_limit_check=1,
			is_return=1,
			return_against="SINV-1",
			credit_notes=[
				{
					"name": "SINV-RET-2",
					"posting_date": "2026-04-02",
					"grand_total": -40,
					"outstanding_amount": 0,
					"currency": "PHP",
				},
				{"name": " ", "grand_total": 5},
				{
					"name": "SINV-RET-1",
					"posting_date": "2026-04-01",
					"grand_total": -15.5,
					"outstanding": 0,
					"currency": "",
				},
			],
			holds=[],
			sales_invoice="SINV-9",
		)
		self.assertEqual(tab["customer_known"], 1)
		self.assertEqual(tab["company_known"], 1)
		self.assertEqual(tab["limit_set"], 1)
		self.assertEqual(tab["credit_limit"], 1000)
		self.assertEqual(tab["outstanding"], 250)
		self.assertEqual(tab["available"], 750)
		self.assertEqual(tab["bypass_credit_limit_check"], 1)
		self.assertEqual(tab["is_return"], 1)
		self.assertEqual(tab["return_against"], "SINV-1")
		self.assertEqual(
			[row["name"] for row in tab["credit_notes"]],
			["SINV-RET-1", "SINV-RET-2"],
		)
		self.assertEqual(tab["credit_notes"][0]["currency"], "PHP")
		self.assertEqual(tab["credit_notes"][0]["outstanding"], 0)
		self.assertEqual(tab["credit_notes"][0]["grand_total"], -15.5)
		self.assertEqual(tab["holds"], [])

	def test_missing_limit_leaves_available_empty(self):
		tab = sales_invoice_dispute_tab(
			customer="Acme",
			company="Co",
			currency="PHP",
			credit_limit=0,
			outstanding=80,
			bypass_credit_limit_check=0,
			is_return=0,
			return_against="",
			credit_notes=None,
			holds=None,
		)
		self.assertEqual(tab["limit_set"], 0)
		self.assertIsNone(tab["credit_limit"])
		self.assertIsNone(tab["available"])
		self.assertEqual(tab["outstanding"], 80)
		self.assertEqual(tab["credit_notes"], [])
		over = sales_invoice_dispute_tab(
			customer="Acme",
			company="",
			currency="PHP",
			credit_limit=100,
			outstanding=150,
			bypass_credit_limit_check=0,
			is_return=0,
			return_against=None,
			credit_notes=[],
			holds=[],
		)
		self.assertEqual(over["company_known"], 0)
		self.assertEqual(over["available"], -50)

	def test_holds_keep_active_and_released_only(self):
		tab = sales_invoice_dispute_tab(
			customer="",
			company="Co",
			currency="",
			credit_limit=None,
			outstanding=None,
			bypass_credit_limit_check=0,
			is_return=0,
			return_against=None,
			credit_notes=[],
			sales_invoice="SINV-1",
			holds=[
				{"fieldname": "on_hold", "active": 1, "source_name": "SINV-1"},
				{
					"kind": "Hold",
					"source_doctype": "Sales Invoice",
					"source_name": "SINV-1",
					"state": "on_hold",
					"active": 0,
					"dispute": "DISP-1",
				},
				{"fieldname": "is_on_hold", "active": 0, "source_name": "SINV-1"},
				{
					"kind": "Collection",
					"source_doctype": "Hero Invoice Action",
					"source_name": "ACT-C",
					"state": "Active",
					"active": 1,
				},
				{
					"kind": "On Hold",
					"source_doctype": "Hero Invoice Action",
					"source_name": "ACT-H",
					"state": "Released",
					"active": 0,
					"dispute": "DISP-1",
				},
				{
					"action_kind": "Dunning",
					"source_doctype": "Dunning",
					"source_name": "DUN-1",
					"previous_state": "Unresolved",
					"active": 0,
				},
			],
		)
		self.assertEqual(tab["customer_known"], 0)
		self.assertEqual(tab["outstanding"], 0)
		self.assertEqual(
			[(row["source_name"], row["state"], row["active"], row["dispute"]) for row in tab["holds"]],
			[("SINV-1", "on_hold", 1, "DISP-1"), ("ACT-H", "Released", 0, "DISP-1")],
		)


def _invoice(name, posting_date, due_date, outstanding, customer="Acme", company="Co"):
	return {
		"sales_invoice": name,
		"customer": customer,
		"company": company,
		"posting_date": posting_date,
		"due_date": due_date,
		"outstanding": outstanding,
	}


if __name__ == "__main__":
	unittest.main()
