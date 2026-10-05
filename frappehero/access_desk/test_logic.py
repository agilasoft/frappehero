# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.access_desk.logic import (
	apply_rows,
	clone_permission_rows,
	default_conflicts,
	diff_roles,
	expired_share_names,
	line_state,
	merge_permissions,
	render_notice,
	review_snapshot,
	role_matrix,
	share_plan,
	should_send,
)


def _perm(doctype, role, **bits):
	row = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	row.update(bits)
	return row


class TestRoles(unittest.TestCase):
	def test_custom_replaces_standard_for_the_same_key(self):
		standard = [_perm("Sales Invoice", "Sales User", read=1, write=1)]
		custom = [_perm("Sales Invoice", "Sales User", read=1, write=0, submit=1)]
		merged = merge_permissions(standard, custom)
		self.assertEqual(len(merged), 1)
		self.assertEqual(merged[0]["write"], 0)
		self.assertEqual(merged[0]["submit"], 1)

	def test_matrix_and_missing_read(self):
		perms = [
			_perm("Sales Invoice", "Sales User", read=1, write=1),
			_perm("Journal Entry", "Accounts User", write=1),
		]
		doctypes = [
			{"name": "Sales Invoice", "module": "Accounts"},
			{"name": "Journal Entry", "module": "Accounts"},
			{"name": "Item", "module": "Stock"},
		]
		shown = role_matrix(perms, doctypes)
		self.assertEqual([row["doctype"] for row in shown["rows"]], ["Sales Invoice", "Journal Entry"])
		missing = role_matrix(perms, doctypes, {"missing_read": 1, "module": "Accounts"})
		self.assertEqual([row["doctype"] for row in missing["rows"]], ["Journal Entry"])
		self.assertTrue(missing["rows"][0]["nobody_read"])
		stock = role_matrix(perms, doctypes, {"missing_read": "1", "module": "Stock"})
		self.assertEqual([row["doctype"] for row in stock["rows"]], ["Item"])

	def test_diff_and_clone(self):
		perms = [
			_perm("Sales Invoice", "Sales User", read=1, write=1),
			_perm("Sales Invoice", "Sales Manager", read=1, submit=1),
			_perm("Sales Invoice", "Sales User", read=1, permlevel=1),
		]
		diffs = diff_roles(perms, "Sales User", "Sales Manager")
		bits = {(row["bit"], row["left"], row["right"]) for row in diffs}
		self.assertIn(("write", 1, 0), bits)
		self.assertIn(("submit", 0, 1), bits)
		cloned = clone_permission_rows(perms, "Sales User", "Sales Reviewer")
		self.assertEqual(len(cloned), 2)
		self.assertTrue(all(row["role"] == "Sales Reviewer" for row in cloned))
		level_one = [row for row in cloned if row["permlevel"] == 1][0]
		self.assertEqual(level_one["read"], 1)


class TestReviewsDefaultsShares(unittest.TestCase):
	def test_snapshot_ignores_order_and_stales_a_confirmation(self):
		members = [{"user": "b@example.com", "full_name": "Bee"}, {"user": "a@example.com", "full_name": "Ay"}]
		rules = [
			{"reference_doctype": "Company", "for_value": "North", "apply_to_all_doctypes": 1},
			{"reference_doctype": "Company", "for_value": "South", "apply_to_all_doctypes": "0", "applicable_for": "Sales Invoice"},
		]
		first = review_snapshot(list(reversed(members)), list(reversed(rules)))
		second = review_snapshot(members, rules)
		self.assertEqual(first, second)
		self.assertEqual(
			line_state("Confirmed", first["members"], first["rules"], second["members"], second["rules"]),
			"Confirmed",
		)
		changed = review_snapshot(members[:1], rules)
		self.assertEqual(
			line_state("Exception", first["members"], first["rules"], changed["members"], changed["rules"]),
			"Stale",
		)
		self.assertEqual(
			line_state("Pending", first["members"], first["rules"], changed["members"], changed["rules"]),
			"Pending",
		)

	def test_empty_default_is_not_a_conflict(self):
		members = [{"user": "a@example.com"}, {"user": "b@example.com"}]
		defaults = [{"default_key": "Company", "default_value": "North"}]
		current = {("a@example.com", "Company"): "", ("b@example.com", "Company"): "South"}
		rows = default_conflicts(members, defaults, current)
		by_user = {row["user"]: row["conflict"] for row in rows}
		self.assertFalse(by_user["a@example.com"])
		self.assertTrue(by_user["b@example.com"])
		self.assertEqual(apply_rows(members, defaults)[0]["value"], "North")

	def test_share_plan_and_expiry(self):
		plan = share_plan([{"user": "a@example.com"}, {"user": "b@example.com"}], [{"user": "a@example.com"}])
		self.assertEqual(plan["missing"], ["b@example.com"])
		self.assertEqual(plan["already"], ["a@example.com"])
		names = expired_share_names(
			[
				{"name": "old", "hero_expires_on": "2026-10-04"},
				{"name": "today", "hero_expires_on": "2026-10-05"},
				{"name": "open", "hero_expires_on": ""},
			],
			"2026-10-05",
		)
		self.assertEqual(names, ["old"])

	def test_notifications_send_once_a_day(self):
		self.assertFalse(should_send(0, None, "2026-10-05"))
		self.assertFalse(should_send(1, "2026-10-05", "2026-10-05"))
		self.assertTrue(should_send("1", "2026-10-04", "2026-10-05"))
		notice = render_notice("Unmapped Accounts", {"count": 3, "map": "Statutory"})
		self.assertIn("Statutory", notice["body"])
		self.assertIn("3", notice["subject"])


if __name__ == "__main__":
	unittest.main()
