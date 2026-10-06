# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.dispute_desk.logic import (
	DISPUTED_SECTION,
	STANDARD_ACTIONS,
	DisputeError,
	aging_bucket,
	close_dispute,
	raise_dispute,
	receivables_aging,
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
		self.assertEqual(body, ["SINV-1", "SINV-3", "", "SINV-2"])
		self.assertEqual(result["rows"][0]["running_balance"], 100)
		self.assertEqual(result["rows"][1]["running_balance"], 125)
		section = result["rows"][2]
		self.assertEqual(section["section"], DISPUTED_SECTION)
		self.assertEqual(section["is_section"], 1)
		disputed = result["rows"][3]
		self.assertEqual(disputed["section"], DISPUTED_SECTION)
		self.assertIsNone(disputed["running_balance"])
		self.assertEqual(disputed["outstanding"], 40)

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
		self.assertEqual(names, ["D91", "D30", "D31", "CUR", "", "D90"])
		disputed = result["rows"][-1]
		self.assertEqual(disputed["section"], DISPUTED_SECTION)
		self.assertEqual(disputed["outstanding"], 50)
		self.assertEqual(disputed["age_days"], 90)
		self.assertEqual(disputed["days_61_90"], 0)
		self.assertEqual(result["rows"][-2]["section"], DISPUTED_SECTION)
		self.assertEqual(result["rows"][-2]["is_section"], 1)


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
