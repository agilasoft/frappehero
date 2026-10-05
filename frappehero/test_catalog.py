# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.catalog import MODULE_IDEAS, ideas_for


class TestCatalog(unittest.TestCase):
	def test_every_idea_has_the_fields_the_page_renders(self):
		areas = set()
		for idea in MODULE_IDEAS:
			for key in ("name", "area", "summary", "problem", "shape", "builds_on"):
				self.assertTrue(str(idea.get(key) or "").strip(), idea.get("name"))
			areas.add(idea["area"])
		self.assertIn("Permissions", areas)
		self.assertIn("Accounts", areas)

	def test_filters(self):
		self.assertGreater(len(ideas_for("Accounts")), 0)
		self.assertTrue(all(idea["area"] == "Accounts" for idea in ideas_for("Accounts")))
		found = ideas_for("All", "required dimension")
		self.assertEqual([idea["name"] for idea in found], ["Dimension Coverage"])
		self.assertEqual(ideas_for("Permissions", "tax template"), [])


if __name__ == "__main__":
	unittest.main()
