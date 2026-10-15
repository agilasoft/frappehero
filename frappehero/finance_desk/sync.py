# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe


def lock_bsp_rate(doc, method=None):
	"""Keep the BSP flag under the rate sync.

	A new Currency Exchange starts unmarked. An existing flag is put back
	unless the sync itself is writing the row.
	"""
	if not doc.meta.has_field("hero_bsp"):
		return
	if doc.flags.get("hero_bsp_sync"):
		return
	if doc.is_new():
		doc.hero_bsp = 0
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	doc.hero_bsp = before.get("hero_bsp")
