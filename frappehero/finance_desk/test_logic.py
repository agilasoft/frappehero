# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.logic import (
	can_create_journal,
	classify_opening_line,
	filter_dimension_rows,
	group_tax_map,
	items_without_tax,
	match_opening_lines,
	parse_trial_balance,
	summarize_dimensions,
	value_to_apply,
)


class TestDimensions(unittest.TestCase):
	def test_statuses(self):
		summary = summarize_dimensions(
			[
				{"account": "Cash", "total": 4, "missing": 0},
				{"account": "Rent", "total": 4, "missing": 4},
				{"account": "Sales", "total": 4, "missing": 1},
				{"account": "Idle", "total": 0, "missing": 0},
			]
		)
		by_account = {row["account"]: row["status"] for row in summary["rows"]}
		self.assertEqual(by_account, {"Cash": "complete", "Rent": "missing", "Sales": "partial", "Idle": "empty"})
		self.assertEqual(summary["rows"][2]["percent"], 75.0)
		self.assertEqual(summary["overall"]["status"], "partial")
		filtered = filter_dimension_rows(summary["rows"], "missing", "rent")
		self.assertEqual([row["account"] for row in filtered], ["Rent"])

	def test_value_to_apply_fills_only_empty_opt_in_rows(self):
		default = {"account": "Cash", "default_value": "Main", "apply_on_new_entries": 1}
		self.assertEqual(value_to_apply("Cash", "", default), "Main")
		self.assertIsNone(value_to_apply("Cash", "Other", default))
		self.assertIsNone(value_to_apply("Cash", "", {**default, "apply_on_new_entries": 0}))
		self.assertIsNone(value_to_apply("Rent", "", default))


class TestTax(unittest.TestCase):
	def test_inheritance_and_items(self):
		groups = group_tax_map(
			[
				{"name": "All", "parent_item_group": "", "template": "VAT"},
				{"name": "Goods", "parent_item_group": "All"},
				{"name": "Services", "parent_item_group": ""},
				{"name": "Consulting", "parent_item_group": "Services", "template": "Service VAT"},
			]
		)
		by_name = {row["name"]: row for row in groups}
		self.assertEqual(by_name["Goods"]["status"], "mapped")
		self.assertEqual(by_name["Goods"]["inherited_from"], "All")
		self.assertIsNone(by_name["Consulting"]["inherited_from"])
		self.assertEqual(by_name["Services"]["status"], "unmapped")
		missing = items_without_tax(
			[
				{"name": "ITEM-1", "item_group": "Goods"},
				{"name": "ITEM-2", "item_group": "Services"},
				{"name": "ITEM-3", "item_group": "Services", "own_template": "Service VAT"},
			],
			groups,
		)
		self.assertEqual([row["name"] for row in missing], ["ITEM-2"])


class TestOpening(unittest.TestCase):
	def test_parse_and_match(self):
		text = "Account Number\tAccount Name\tDebit\tCredit\n1000\tCash\t1,000.50\t0\n\n2000\tSales\t0\t40\n"
		rows = parse_trial_balance(text)
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["debit"], 1000.5)
		comma = parse_trial_balance("Account,Debit,Credit\nCash,10,0\n")
		self.assertEqual(comma[0]["account_name"], "Cash")
		candidates = [
			{"name": "Cash - A", "account_number": "1000", "account_name": "Cash", "is_group": 0},
			{"name": "Cash - B", "account_number": "1000", "account_name": "Petty", "is_group": 0},
			{"name": "Sales - A", "account_number": "2000", "account_name": "Sales", "is_group": 0},
			{"name": "Assets", "account_number": "1000", "account_name": "Assets", "is_group": 1},
		]
		ambiguous = classify_opening_line({"account_number": "1000", "account_name": "Cash"}, candidates)
		self.assertEqual(ambiguous["match_status"], "Ambiguous")
		unique = classify_opening_line({"account_number": "2000", "account_name": "Sales"}, candidates)
		self.assertEqual(unique["matched_account"], "Sales - A")
		by_name = classify_opening_line({"account_name": "Petty"}, candidates)
		self.assertEqual(by_name["match_reason"], "Same account name")
		lines = match_opening_lines(
			[{"account_number": "2000", "account_name": "Sales", "debit": 0, "credit": 40}],
			candidates,
		)
		self.assertEqual(lines[0]["match_status"], "Matched")

	def test_journal_requires_a_full_match_and_a_balance(self):
		balanced = [
			{"match_status": "Matched", "matched_account": "Cash", "debit": 10, "credit": 0},
			{"match_status": "Matched", "matched_account": "Equity", "debit": 0, "credit": 10},
		]
		self.assertTrue(can_create_journal(balanced))
		self.assertFalse(can_create_journal([]))
		self.assertFalse(can_create_journal([{**balanced[0], "match_status": "Unmatched", "matched_account": None}]))
		self.assertFalse(can_create_journal([{**balanced[0], "credit": 1}]))


if __name__ == "__main__":
	unittest.main()
