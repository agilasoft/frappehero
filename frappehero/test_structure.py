# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import json
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


class TestAppStructure(unittest.TestCase):
	def test_modules_cover_every_doctype_page_and_report(self):
		modules = {
			line.strip()
			for line in (PACKAGE / "modules.txt").read_text().splitlines()
			if line.strip() and not line.startswith("#")
		}
		self.assertEqual(
			modules,
			{"Frappe Hero", "Permission Studio", "Accounts Mapping", "Access Desk", "Finance Desk", "Dispute Desk"},
		)
		for path in PACKAGE.rglob("*.json"):
			payload = json.loads(path.read_text())
			kind = payload.get("doctype")
			if kind == "DocType":
				self.assertIn(payload["module"], modules, path)
				self._assert_doctype(payload, path)
			elif kind == "Page":
				self.assertIn(payload["module"], modules, path)
				script = path.with_suffix(".js")
				self.assertTrue(script.exists(), script)
				self.assertEqual(payload["name"], payload["page_name"])
			elif kind == "Report":
				self.assertIn(payload["module"], modules, path)
				self.assertEqual(payload["report_type"], "Script Report")
				self.assertTrue(path.with_suffix(".py").exists(), path)
				self.assertTrue(path.with_suffix(".js").exists(), path)
			elif kind == "Workspace":
				self.assertIn(payload["module"], modules, path)
				blocks = json.loads(payload["content"])
				shortcut_names = {row["label"] for row in payload["shortcuts"]}
				for block in blocks:
					if block["type"] == "shortcut":
						self.assertIn(block["data"]["shortcut_name"], shortcut_names)
					if block["type"] == "card":
						labels = [row["label"] for row in payload["links"] if row["type"] == "Card Break"]
						self.assertIn(block["data"]["card_name"], labels)

	def _assert_doctype(self, payload, path):
		fields = payload["fields"]
		names = [field["fieldname"] for field in fields]
		self.assertEqual(len(names), len(set(names)), path)
		self.assertEqual(list(payload["field_order"]), names, path)
		if payload.get("istable"):
			self.assertEqual(payload.get("permissions"), [])
		else:
			self.assertTrue(payload.get("permissions"), path)
			self.assertTrue(any(row.get("role") == "System Manager" for row in payload["permissions"]))
		for field in fields:
			if field["fieldtype"] == "Table":
				self.assertTrue(field.get("options"), field)
