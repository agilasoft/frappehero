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

	def test_frappe_hero_is_on_the_desk(self):
		hooks = (PACKAGE / "hooks.py").read_text()
		self.assertIn('app_home = "/desk/frappe-hero"', hooks)
		self.assertIn('"sequence_id": 50', hooks)
		icon = json.loads((PACKAGE / "desktop_icon" / "frappe_hero.json").read_text())
		self.assertEqual(icon["doctype"], "Desktop Icon")
		self.assertEqual(icon["label"], "Frappe Hero")
		self.assertEqual(icon["icon_type"], "App")
		self.assertEqual(icon["link"], "/desk/frappe-hero")
		self.assertEqual(icon["standard"], 1)
		self.assertEqual(icon["hidden"], 0)
		self.assertEqual(icon["logo_url"], "/assets/frappehero/images/logo.svg")
		dock = json.loads((PACKAGE / "dock" / "frappehero" / "frappehero.json").read_text())
		self.assertEqual(dock["name"], "frappehero")
		self.assertEqual(dock["app"], "frappehero")
		self.assertEqual(dock["standard"], 1)
		titles = [row["title"] for row in dock["items"]]
		self.assertEqual(titles[0], "Frappe Hero")
		self.assertEqual(
			set(titles),
			{"Frappe Hero", "Permission Studio", "Accounts Mapping", "Access Desk", "Finance Desk", "Dispute Desk"},
		)
		for row in dock["items"]:
			self.assertEqual(row["link_type"], "Sidebar")
			self.assertTrue(row["icon"])
			folder = row["link_to"].lower().replace(" ", "_")
			sidebar_path = PACKAGE / folder / "sidebar" / folder / f"{folder}.json"
			sidebar = json.loads(sidebar_path.read_text())
			self.assertEqual(sidebar["doctype"], "Sidebar")
			self.assertEqual(sidebar["title"], row["link_to"])
			self.assertEqual(sidebar["module"], row["link_to"])
			self.assertEqual(sidebar["standard"], 1)
			self.assertEqual(sidebar["items"][0]["type"], "Link")
		workspace = json.loads(
			(PACKAGE / "frappe_hero" / "workspace" / "frappe_hero" / "frappe_hero.json").read_text()
		)
		self.assertEqual(workspace["app"], "frappehero")

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
