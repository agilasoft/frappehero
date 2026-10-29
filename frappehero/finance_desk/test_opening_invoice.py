# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.opening_invoice_logic import (
	INVOICE_TYPE_OPTIONS,
	OpeningInvoiceError,
	against_can_link,
	apply_note,
	invoice_kind,
	is_note,
	retitle,
	return_line,
)


class _AttrDict(dict):
	"""Stand-in for frappe._dict: fields are read as attributes."""

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:
			raise AttributeError(key) from exc


def _invoice(qty=1, rate=25, item_name="Opening Invoice Item", description=None):
	return {
		"doctype": "Purchase Invoice",
		"items": [
			{
				"qty": qty,
				"rate": rate,
				"item_name": item_name,
				"description": item_name if description is None else description,
			}
		],
	}


class TestOpeningInvoiceKinds(unittest.TestCase):
	def test_credit_note_is_a_sales_return(self):
		kind = invoice_kind("Credit Note")
		self.assertEqual(kind["doctype"], "Sales Invoice")
		self.assertEqual(kind["party_type"], "Customer")
		self.assertEqual(kind["base_type"], "Sales")
		self.assertEqual(kind["is_return"], 1)
		self.assertTrue(is_note("credit note"))

	def test_debit_note_is_a_purchase_return(self):
		kind = invoice_kind("  Debit Note ")
		self.assertEqual(kind["doctype"], "Purchase Invoice")
		self.assertEqual(kind["party_type"], "Supplier")
		self.assertEqual(kind["base_type"], "Purchase")
		self.assertEqual(kind["is_return"], 1)

	def test_sales_and_purchase_stay_plain_invoices(self):
		sales = invoice_kind("Sales")
		purchase = invoice_kind("purchase")
		self.assertEqual(sales["is_return"], 0)
		self.assertEqual(sales["doctype"], "Sales Invoice")
		self.assertEqual(purchase["party_type"], "Supplier")
		self.assertFalse(is_note("Sales"))
		self.assertFalse(is_note("Purchase"))

	def test_options_keep_the_standard_types_first(self):
		self.assertEqual(INVOICE_TYPE_OPTIONS.split("\n"), ["Sales", "Purchase", "Credit Note", "Debit Note"])

	def test_unknown_type_is_rejected(self):
		with self.assertRaises(OpeningInvoiceError):
			invoice_kind("Journal")
		self.assertFalse(is_note(""))


class TestReturnLines(unittest.TestCase):
	def test_positive_upload_becomes_a_negative_quantity(self):
		self.assertEqual(return_line(2, 50), (-2.0, 50.0))

	def test_negative_amount_keeps_a_positive_rate(self):
		self.assertEqual(return_line(1, -80), (-1.0, 80.0))

	def test_blank_quantity_posts_the_rate_once(self):
		self.assertEqual(return_line(None, 40), (-1.0, 40.0))
		self.assertEqual(return_line(0, 40), (-1.0, 40.0))

	def test_absolute_amount_when_both_signs_are_negative(self):
		self.assertEqual(return_line(-2, -50), (-2.0, 50.0))

	def test_non_numeric_values_do_not_post_infinity(self):
		self.assertEqual(return_line("nope", float("inf")), (-1.0, 0.0))


class TestApplyNote(unittest.TestCase):
	def test_credit_note_links_a_submitted_sales_invoice(self):
		source = _invoice()
		stamped = apply_note(source, invoice_kind("Credit Note"), "SINV-1", linked=True)
		self.assertEqual(stamped["doctype"], "Sales Invoice")
		self.assertEqual(stamped["is_return"], 1)
		self.assertEqual(stamped["return_against"], "SINV-1")
		self.assertEqual(stamped["update_outstanding_for_self"], 0)
		self.assertEqual(stamped["items"][0]["qty"], -1.0)
		self.assertEqual(stamped["items"][0]["rate"], 25.0)
		self.assertEqual(stamped["items"][0]["item_name"], "Opening Credit Note")
		self.assertEqual(source["doctype"], "Purchase Invoice")
		self.assertEqual(source["items"][0]["qty"], 1)
		self.assertEqual(source["items"][0]["item_name"], "Opening Invoice Item")

	def test_missing_invoice_is_kept_on_the_note(self):
		stamped = apply_note(
			_invoice(item_name="Widget", description="Widget"),
			invoice_kind("Debit Note"),
			"OLD-9",
			linked=False,
		)
		self.assertEqual(stamped["doctype"], "Purchase Invoice")
		self.assertNotIn("return_against", stamped)
		self.assertEqual(stamped["update_outstanding_for_self"], 1)
		self.assertEqual(stamped["remarks"], "Against invoice OLD-9")
		self.assertEqual(stamped["items"][0]["item_name"], "Widget")

	def test_quantity_note_survives_the_generic_title(self):
		description = "Opening Invoice Item Original Quantity: 2.5"
		stamped = apply_note(
			_invoice(description=description),
			invoice_kind("Credit Note"),
			"",
			linked=False,
		)
		self.assertEqual(stamped["items"][0]["description"], "Opening Credit Note Original Quantity: 2.5")
		self.assertNotIn("remarks", stamped)

	def test_attribute_access_survives_for_the_importer(self):
		source = _AttrDict(
			doctype="Purchase Invoice",
			invoice_number=None,
			items=[
				_AttrDict(
					qty=1,
					rate=10000,
					item_name="Opening Credit Note",
					description="Opening Credit Note",
				)
			],
		)
		stamped = apply_note(source, invoice_kind("Credit Note"), "", linked=False)
		self.assertIsInstance(stamped, _AttrDict)
		self.assertIsInstance(stamped["items"][0], _AttrDict)
		self.assertIsNone(stamped.invoice_number)
		self.assertEqual(stamped.doctype, "Sales Invoice")
		self.assertEqual(stamped["items"][0].qty, -1.0)
		self.assertEqual(stamped["items"][0].rate, 10000.0)
		self.assertEqual(source["items"][0]["qty"], 1)

	def test_sales_upload_is_left_alone(self):
		source = _invoice()
		self.assertIs(apply_note(source, invoice_kind("Sales"), "SINV-1", linked=True), source)

	def test_against_invoice_must_be_submitted_in_the_company(self):
		self.assertTrue(against_can_link("SINV-1", "Acme", "Acme", 1))
		self.assertTrue(against_can_link("SINV-1", "Acme", "", "1"))
		self.assertFalse(against_can_link("SINV-1", "Acme", "Other", 1))
		self.assertFalse(against_can_link("SINV-1", "Acme", "Acme", 0))
		self.assertFalse(against_can_link("SINV-1", "Acme", "Acme", 2))
		self.assertFalse(against_can_link("", "Acme", "Acme", 1))

	def test_retitle_keeps_a_typed_item_name(self):
		self.assertEqual(retitle("Freight", "Opening Debit Note"), "Freight")
		self.assertEqual(retitle("", "Opening Debit Note"), "Opening Debit Note")
		self.assertEqual(retitle("opening invoice item", "Opening Debit Note"), "Opening Debit Note")
		self.assertEqual(
			retitle("Opening Invoice Itemization", "Opening Debit Note"), "Opening Invoice Itemization"
		)
