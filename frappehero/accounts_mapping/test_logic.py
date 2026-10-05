# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.accounts_mapping.logic import (
	coverage,
	line_completion,
	suggest_for_account,
	suggest_mappings,
	unmapped_rows,
	validate_map,
	visible_tree,
)


def chart():
	return [
		{"name": "Assets", "parent_account": None, "is_group": 1, "root_type": "Asset", "account_name": "Assets", "disabled": 0},
		{"name": "Current Assets", "parent_account": "Assets", "is_group": 1, "root_type": "Asset", "account_name": "Current Assets", "disabled": 0},
		{"name": "Cash", "parent_account": "Current Assets", "is_group": 0, "root_type": "Asset", "account_name": "Cash", "account_number": "1110", "account_type": "Cash", "disabled": 0},
		{"name": "Bank", "parent_account": "Current Assets", "is_group": 0, "root_type": "Asset", "account_name": "Bank", "account_number": "1120", "account_type": "Bank", "disabled": 0},
		{"name": "Old Cash", "parent_account": "Current Assets", "is_group": 0, "root_type": "Asset", "account_name": "Old Cash", "account_number": "1119", "account_type": "Cash", "disabled": 1},
		{"name": "Income", "parent_account": None, "is_group": 1, "root_type": "Income", "account_name": "Income", "disabled": 0},
		{"name": "Sales", "parent_account": "Income", "is_group": 0, "root_type": "Income", "account_name": "Sales", "account_number": "4100", "account_type": "Income Account", "disabled": 0},
	]


def _names(nodes):
	found = []
	for node in nodes:
		found.append(node["name"])
		found.extend(_names(node["children"]))
	return found


class TestLineStatus(unittest.TestCase):
	def test_completion_follows_the_map_type(self):
		line = {"target_account": "Cash - Other", "external_code": "", "reporting_group": "Cash"}
		self.assertEqual(line_completion("Another Company", line), "mapped")
		self.assertEqual(line_completion("External Code", line), "partial")
		self.assertEqual(line_completion("Reporting Group", line), "mapped")

	def test_coverage_ignores_groups_and_disabled(self):
		status = {"Cash": "mapped", "Bank": "unmapped", "Sales": "partial", "Old Cash": "unmapped"}
		stats = coverage(chart(), status)
		self.assertEqual(stats["total"], 3)
		self.assertEqual(stats["mapped"], 1)
		self.assertEqual(stats["partial"], 1)
		self.assertEqual(stats["unmapped"], 1)
		self.assertEqual(stats["percent"], 33.3)


class TestTreeFilters(unittest.TestCase):
	def test_unmapped_keeps_the_ancestor_path(self):
		status = {"Cash": "mapped", "Bank": "unmapped", "Sales": "mapped", "Old Cash": "unmapped"}
		tree = visible_tree(chart(), status, {"status": "unmapped"})
		self.assertEqual(_names(tree), ["Assets", "Current Assets", "Bank"])
		assets = tree[0]
		self.assertEqual(assets["status"], "unmapped")
		self.assertEqual(assets["total_leaves"], 1)
		self.assertEqual(assets["mapped_leaves"], 0)

	def test_partial_parent_when_siblings_differ(self):
		status = {"Cash": "mapped", "Bank": "unmapped", "Sales": "mapped", "Old Cash": "unmapped"}
		tree = visible_tree(chart(), status, {})
		assets = tree[0]
		self.assertEqual(assets["status"], "partial")
		self.assertEqual(assets["mapped_leaves"], 1)
		self.assertEqual(assets["total_leaves"], 2)

	def test_search_matches_a_parent_name(self):
		status = {account["name"]: "unmapped" for account in chart()}
		tree = visible_tree(chart(), status, {"search": "current assets"})
		self.assertEqual(_names(tree), ["Assets", "Current Assets", "Cash", "Bank"])

	def test_search_matches_an_account_number(self):
		status = {account["name"]: "unmapped" for account in chart()}
		tree = visible_tree(chart(), status, {"search": "4100"})
		self.assertEqual(_names(tree), ["Income", "Sales"])

	def test_root_type_and_account_type(self):
		status = {account["name"]: "unmapped" for account in chart()}
		tree = visible_tree(chart(), status, {"root_types": ["Asset"], "account_types": ["Cash"]})
		self.assertEqual(_names(tree), ["Assets", "Current Assets", "Cash"])

	def test_disabled_is_hidden_until_asked_for(self):
		status = {account["name"]: "unmapped" for account in chart()}
		hidden = _names(visible_tree(chart(), status, {}))
		shown = _names(visible_tree(chart(), status, {"include_disabled": 1}))
		self.assertNotIn("Old Cash", hidden)
		self.assertIn("Old Cash", shown)


class TestSuggestions(unittest.TestCase):
	def test_unique_account_number_wins(self):
		source = {"name": "Cash - A", "account_name": "Cash", "account_number": "1110", "is_group": 0}
		candidates = [
			{"name": "Cash - B", "account_name": "Petty Cash", "account_number": "1110", "is_group": 0},
			{"name": "Bank - B", "account_name": "Bank", "account_number": "1120", "is_group": 0},
		]
		suggestion = suggest_for_account(source, candidates, "Another Company")
		self.assertEqual(suggestion["target_account"], "Cash - B")
		self.assertEqual(suggestion["reason"], "Same account number")

	def test_ambiguous_number_is_not_a_guess(self):
		source = {"name": "Cash - A", "account_name": "Cash", "account_number": "1110", "is_group": 0}
		candidates = [
			{"name": "Cash - B", "account_name": "Cash", "account_number": "1110", "is_group": 0},
			{"name": "Cash - C", "account_name": "Cash", "account_number": "1110", "is_group": 0},
		]
		self.assertIsNone(suggest_for_account(source, candidates, "Another Company"))

	def test_account_name_when_numbers_differ(self):
		source = {"name": "Sales - A", "account_name": "Sales", "account_number": "4100", "is_group": 0}
		candidates = [
			{"name": "Sales - B", "account_name": "Sales", "account_number": "4000", "is_group": 0},
		]
		suggestion = suggest_for_account(source, candidates, "Another Company")
		self.assertEqual(suggestion["reason"], "Same account name")

	def test_external_code_and_reporting_group(self):
		source = {"name": "Cash - A", "account_name": "Cash", "account_number": "1110", "account_type": "Cash", "root_type": "Asset", "is_group": 0}
		external = suggest_for_account(source, [], "External Code")
		self.assertEqual(external["external_code"], "1110")
		group = suggest_for_account({**source, "account_number": ""}, [], "Reporting Group")
		self.assertEqual(group["reporting_group"], "Cash")
		fallback = suggest_for_account(
			{"name": "Misc", "account_name": "Misc", "root_type": "Expense", "is_group": 0},
			[],
			"Reporting Group",
		)
		self.assertEqual(fallback["reason"], "Root type")

	def test_suggest_mappings_skips_done_and_groups(self):
		sources = chart()
		suggestions = suggest_mappings(sources, [], "External Code", already_mapped={"Cash"})
		accounts = {row["source_account"] for row in suggestions}
		self.assertNotIn("Cash", accounts)
		self.assertNotIn("Assets", accounts)
		self.assertIn("Bank", accounts)
		self.assertNotIn("Old Cash", accounts)


class TestValidateAndReport(unittest.TestCase):
	def test_validate_map(self):
		account_map = {
			"mapping_type": "Another Company",
			"company": "A",
			"target_company": "A",
			"lines": [
				{"source_account": "Cash"},
				{"source_account": "Cash", "target_account": "Cash"},
			],
		}
		errors = validate_map(account_map, {"Cash": "A"})
		self.assertTrue(any("different" in error for error in errors))
		self.assertTrue(any("more than once" in error for error in errors))
		self.assertTrue(any("itself" in error for error in errors))

		clean = validate_map(
			{
				"mapping_type": "External Code",
				"company": "A",
				"lines": [{"source_account": "Cash", "external_code": "1110"}],
			},
			{"Cash": "A"},
		)
		self.assertEqual(clean, [])
		group_errors = validate_map(
			{"mapping_type": "External Code", "company": "A", "lines": [{"source_account": "Assets"}]},
			{"Assets": "A"},
			{"Assets"},
		)
		self.assertTrue(any("group account" in error for error in group_errors))

	def test_unmapped_rows_follow_status(self):
		lines = [{"source_account": "Cash", "target_account": "Cash - B"}]
		rows = unmapped_rows(chart(), lines, "Another Company", {"status": "unmapped"})
		self.assertEqual([row["account"] for row in rows], ["Bank", "Sales"])


if __name__ == "__main__":
	unittest.main()
