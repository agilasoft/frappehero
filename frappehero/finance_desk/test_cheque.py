# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.cheque_logic import (
	ChequeError,
	compose_numbers,
	conflicting_numbers,
	filter_leaves,
	generate_range,
	mode_uses_cheque_leaf,
	parse_extra_numbers,
	plan_payment_cheque,
	preview_cheque,
	summarize_book,
	summarize_numbers,
	validate_leaf_shape,
	validate_number_changes,
)


def _leaf(name, bank, status="Active", company="Acme", default=0):
	return {
		"name": name,
		"bank_account": bank,
		"company": company,
		"status": status,
		"is_default": default,
	}


def _numbers(*rows):
	parsed = []
	for row in rows:
		if isinstance(row, str):
			parsed.append({"cheque_number": row, "status": "Available", "payment_entry": ""})
		else:
			parsed.append({"cheque_number": row[0], "status": row[1], "payment_entry": row[2] if len(row) > 2 else ""})
	return parsed


def _plan(**overrides):
	base = {
		"action": "save",
		"payment_type": "Pay",
		"bank_account": "BDO",
		"company": "Acme",
		"mode_uses_cheque": True,
		"selected_leaf": "",
		"requested_number": "",
		"payment_name": "PE-1",
		"previous_leaf": "",
		"previous_number": "",
		"reference_no": "",
		"docstatus": 0,
		"leaves": [_leaf("Current", "BDO")],
		"numbers_by_leaf": {"Current": _numbers("1001", "1002")},
	}
	base.update(overrides)
	return plan_payment_cheque(**base)


class TestChequeSet(unittest.TestCase):
	def test_range_prefix_and_padding(self):
		self.assertEqual(generate_range("CHQ-", 1, 3, 4), ["CHQ-0001", "CHQ-0002", "CHQ-0003"])
		self.assertEqual(generate_range("", 12, 12, 0), ["12"])
		self.assertEqual(generate_range("", 0, 0, 0), [])
		self.assertEqual(generate_range("", "", "", 0), [])

	def test_range_rejects_a_broken_book(self):
		with self.assertRaises(ChequeError):
			generate_range("", 1, None, 0)
		with self.assertRaises(ChequeError):
			generate_range("", 10, 9, 0)
		with self.assertRaises(ChequeError):
			generate_range("", 0, 5, 0)
		with self.assertRaises(ChequeError):
			generate_range("", 1, 501, 0)
		self.assertEqual(len(generate_range("", 1, 500, 0)), 500)
		with self.assertRaises(ChequeError):
			generate_range("", 1, 2, 13)

	def test_extra_lines_skip_blanks_and_repeats(self):
		self.assertEqual(parse_extra_numbers(" 1001 \n\n1001\n1008\n"), ["1001", "1008"])

	def test_compose_adds_the_range_and_keeps_issued_rows(self):
		existing = [
			{"name": "a", "cheque_number": "1001", "status": "Used", "payment_entry": "PE-1", "party": "North"},
			{"name": "b", "cheque_number": "1009", "status": "Available", "payment_entry": ""},
		]
		rows = compose_numbers(existing, ["1001", "1002"], ["1008"])
		by_number = {row["cheque_number"]: row for row in rows}
		self.assertEqual(by_number["1001"]["status"], "Used")
		self.assertEqual(by_number["1001"]["name"], "a")
		self.assertEqual(by_number["1001"]["party"], "North")
		self.assertEqual(by_number["1002"]["status"], "Available")
		self.assertEqual(by_number["1008"]["status"], "Available")
		self.assertIn("1009", by_number)
		replaced = compose_numbers(existing, ["1003"], [], replace_available=1)
		self.assertEqual([row["cheque_number"] for row in replaced], ["1001", "1003"])

	def test_shape_and_changes(self):
		self.assertEqual(validate_leaf_shape({"status": "Draft", "bank_account": "BDO"}, []), [])
		self.assertTrue(validate_leaf_shape({"status": "Active", "bank_account": "BDO"}, []))
		previous = [
			{"name": "a", "cheque_number": "1001", "status": "Used", "payment_entry": "PE-1"},
			{"name": "b", "cheque_number": "1002", "status": "Available", "payment_entry": ""},
		]
		renumbered = [
			{"name": "a", "cheque_number": "1009", "status": "Used", "payment_entry": "PE-1"},
			{"name": "b", "cheque_number": "1002", "status": "Cancelled", "payment_entry": ""},
		]
		self.assertTrue(validate_number_changes(previous, renumbered))
		spoiled = [
			{"name": "b", "cheque_number": "1002", "status": "Available", "payment_entry": ""},
		]
		self.assertTrue(any("1001" in message for message in validate_number_changes(previous, spoiled)))
		voided = [
			{"name": "a", "cheque_number": "1001", "status": "Cancelled", "payment_entry": "PE-1"},
			{"name": "b", "cheque_number": "1002", "status": "Available", "payment_entry": ""},
		]
		self.assertEqual(validate_number_changes(previous, voided), [])
		restored = [
			{"name": "a", "cheque_number": "1001", "status": "Available", "payment_entry": ""},
			{"name": "b", "cheque_number": "1002", "status": "Available", "payment_entry": ""},
		]
		self.assertTrue(validate_number_changes(voided, restored))

	def test_same_number_on_two_leaves(self):
		clash = conflicting_numbers(["1001", "1002"], [{"name": "Old", "numbers": ["1002"]}])
		self.assertEqual(clash, [{"cheque_number": "1002", "leaf": "Old"}])


class TestAssignment(unittest.TestCase):
	def test_mode_name_and_flag(self):
		self.assertTrue(mode_uses_cheque_leaf("Cheque"))
		self.assertTrue(mode_uses_cheque_leaf("Manager's Check"))
		self.assertTrue(mode_uses_cheque_leaf("Wire", flagged=1))
		self.assertFalse(mode_uses_cheque_leaf("Wire Transfer"))
		self.assertFalse(mode_uses_cheque_leaf("Checking"))

	def test_pay_takes_the_next_number_and_keeps_it(self):
		first = _plan()
		self.assertIsNone(first["error"])
		self.assertEqual(first["leaf"], "Current")
		self.assertEqual(first["cheque_number"], "1001")
		self.assertEqual(first["state"], "Assigned")
		self.assertTrue(first["set_reference_no"])
		self.assertEqual(first["updates"]["Current"][0]["status"], "Assigned")
		held = _plan(
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-1"), "1002")},
		)
		self.assertEqual(held["cheque_number"], "1001")
		self.assertEqual(held["updates"], {})

	def test_specific_number_switches_and_releases_the_old_one(self):
		moved = _plan(
			requested_number="1002",
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-1"), "1002")},
		)
		self.assertEqual(moved["cheque_number"], "1002")
		statuses = {row["cheque_number"]: row["status"] for row in moved["updates"]["Current"]}
		self.assertEqual(statuses, {"1001": "Available", "1002": "Assigned"})

	def test_used_and_foreign_numbers_are_refused(self):
		taken = _plan(
			requested_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Used", "PE-9"), "1002")},
		)
		self.assertIn("PE-9", taken["error"])
		self.assertEqual(taken["updates"], {})
		cancelled = _plan(requested_number="1001", numbers_by_leaf={"Current": _numbers(("1001", "Cancelled", "PE-9"))})
		self.assertIn("cancelled", cancelled["error"])

	def test_receive_releases_a_draft_reservation(self):
		cleared = _plan(
			payment_type="Receive",
			previous_leaf="Current",
			previous_number="1001",
			reference_no="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-1"))},
		)
		self.assertEqual(cleared["cheque_number"], "")
		self.assertTrue(cleared["clear_reference_no"])
		self.assertEqual(cleared["updates"]["Current"][0]["status"], "Available")

	def test_cheque_mode_picks_the_default_leaf(self):
		leaves = [_leaf("Old", "BDO"), _leaf("New", "BDO", default=1)]
		numbers = {"Old": _numbers("1"), "New": _numbers("9")}
		picked = _plan(leaves=leaves, numbers_by_leaf=numbers)
		self.assertEqual(picked["leaf"], "New")
		self.assertEqual(picked["cheque_number"], "9")
		ambiguous = _plan(leaves=[_leaf("Old", "BDO"), _leaf("New", "BDO")], numbers_by_leaf=numbers)
		self.assertIn("Choose a Cheque Leaf", ambiguous["error"])
		missing = _plan(leaves=[], numbers_by_leaf={})
		self.assertIn("Add an active Cheque Leaf", missing["error"])

	def test_a_chosen_leaf_must_belong_to_the_bank_account(self):
		wrong = _plan(selected_leaf="Other", leaves=[_leaf("Other", "BPI"), _leaf("Current", "BDO")])
		self.assertIn("BPI", wrong["error"])
		closed = _plan(selected_leaf="Current", leaves=[_leaf("Current", "BDO", status="Closed")])
		self.assertIn("Closed", closed["error"])
		other_company = _plan(selected_leaf="Current", leaves=[_leaf("Current", "BDO", company="Other")])
		self.assertIn("Other", other_company["error"])

	def test_manual_leaf_on_a_non_cheque_mode(self):
		idle = _plan(mode_uses_cheque=False)
		self.assertIsNone(idle["error"])
		self.assertEqual(idle["cheque_number"], "")
		manual = _plan(mode_uses_cheque=False, selected_leaf="Current")
		self.assertEqual(manual["cheque_number"], "1001")

	def test_submit_uses_the_number_and_cancel_voids_it(self):
		submitted = _plan(
			action="submit",
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-1"), "1002")},
		)
		self.assertEqual(submitted["state"], "Used")
		self.assertEqual(submitted["updates"]["Current"][0]["status"], "Used")
		voided = _plan(
			action="cancel",
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Used", "PE-1"))},
		)
		self.assertEqual(voided["state"], "Cancelled")
		self.assertEqual(voided["updates"]["Current"][0]["status"], "Cancelled")
		self.assertEqual(voided["updates"]["Current"][0]["payment_entry"], "PE-1")

	def test_trash_leaves_a_number_owned_by_another_payment(self):
		trashed = _plan(
			action="trash",
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-9"))},
		)
		self.assertIsNone(trashed["error"])
		self.assertEqual(trashed["updates"], {})

	def test_trash_returns_the_number_to_the_set(self):
		trashed = _plan(
			action="trash",
			previous_leaf="Current",
			previous_number="1001",
			numbers_by_leaf={"Current": _numbers(("1001", "Assigned", "PE-1"))},
		)
		self.assertEqual(trashed["updates"]["Current"][0]["status"], "Available")
		self.assertEqual(trashed["updates"]["Current"][0]["payment_entry"], "")

	def test_submitted_payment_keeps_its_cheque(self):
		kept = _plan(docstatus=1, previous_leaf="Current", previous_number="1001", requested_number="1002")
		self.assertEqual(kept["cheque_number"], "1001")
		self.assertEqual(kept["updates"], {})

	def test_switching_leaves_releases_the_previous_book(self):
		moved = _plan(
			selected_leaf="New",
			previous_leaf="Old",
			previous_number="1",
			leaves=[_leaf("Old", "BDO"), _leaf("New", "BDO")],
			numbers_by_leaf={
				"Old": _numbers(("1", "Assigned", "PE-1")),
				"New": _numbers("9"),
			},
		)
		self.assertIsNone(moved["error"])
		self.assertEqual(moved["leaf"], "New")
		self.assertEqual(moved["cheque_number"], "9")
		self.assertEqual(moved["updates"]["Old"][0]["status"], "Available")
		self.assertEqual(moved["updates"]["New"][0]["cheque_number"], "9")

	def test_preview_offers_the_next_free_number(self):
		preview = preview_cheque(
			[_leaf("Current", "BDO")],
			{"Current": _numbers(("1001", "Used", "PE-1"), "1002")},
			"BDO",
			company="Acme",
			mode_uses_cheque=True,
		)
		self.assertEqual(preview["cheque_number"], "1002")
		self.assertEqual(preview["available"], ["1002"])
		self.assertIsNone(preview["error"])


class TestLeafList(unittest.TestCase):
	def test_summary_and_filters(self):
		summary = summarize_numbers(
			_numbers(("1001", "Used", "PE-1"), "1002", ("1003", "Cancelled", ""), ("1004", "Assigned", "PE-2"))
		)
		self.assertEqual(summary["usage"], "open")
		self.assertEqual(summary["available"], 1)
		exhausted = summarize_numbers(_numbers(("1001", "Used", "PE-1")))
		self.assertEqual(exhausted["usage"], "exhausted")
		self.assertEqual(summarize_numbers([])["usage"], "empty")
		leaves = [
			{"name": "Current", "bank_account": "BDO", "company": "Acme", "bank": "BDO", "status": "Active", **summary},
			{
				"name": "Old",
				"bank_account": "BPI",
				"company": "Acme",
				"bank": "BPI",
				"status": "Closed",
				**exhausted,
			},
		]
		self.assertEqual([row["name"] for row in filter_leaves(leaves, bank_account="BDO")], ["Current"])
		self.assertEqual([row["name"] for row in filter_leaves(leaves, usage="exhausted")], ["Old"])
		self.assertEqual([row["name"] for row in filter_leaves(leaves, text="bpi")], ["Old"])
		self.assertEqual(summarize_book(leaves)["leaves"], 2)
		self.assertEqual(summarize_book(leaves)["used"], 2)


if __name__ == "__main__":
	unittest.main()
