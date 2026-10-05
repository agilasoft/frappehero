# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import frappe

from frappehero.finance_desk.logic import DIMENSION_FIELDS, value_to_apply
from frappehero.flags import as_flag

ALLOWED_FIELDS = frozenset(DIMENSION_FIELDS.values())


def apply_dimension_defaults(doc, method=None):
	"""Fill an empty dimension from an opted-in Hero Dimension Default.

	A value already on the entry is left as it was. The lookup is cached
	for the rest of the request.
	"""
	if as_flag(doc.get("is_cancelled")):
		return
	account = doc.get("account")
	company = doc.get("company")
	if not account or not company:
		return
	if not frappe.db.table_exists("Hero Dimension Default"):
		return
	cache = getattr(frappe.local, "hero_dimension_defaults", None)
	if cache is None:
		cache = {}
		frappe.local.hero_dimension_defaults = cache
	key = (company, account)
	if key not in cache:
		cache[key] = frappe.get_all(
			"Hero Dimension Default",
			filters={"company": company, "account": account, "apply_on_new_entries": 1},
			fields=["account", "dimension", "default_value", "apply_on_new_entries"],
			limit_page_length=0,
			ignore_permissions=True,
		)
	for row in cache[key]:
		fieldname = DIMENSION_FIELDS.get(row.dimension)
		if fieldname not in ALLOWED_FIELDS or not doc.meta.has_field(fieldname):
			continue
		value = value_to_apply(account, doc.get(fieldname), row)
		if value:
			doc.set(fieldname, value)
