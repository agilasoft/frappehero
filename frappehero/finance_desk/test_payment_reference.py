# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.payment_reference_logic import (
	columns_for_references,
	should_write_invoice_currency,
	source_from_document,
	source_from_dunning,
	source_from_journal,
)


class TestInvoiceCurrencyColumns(unittest.TestCase):
	def test_rounded_total_is_the_invoice_amount(self):
		columns = columns_for_references(
			[{"reference_doctype": "Sales Invoice", "reference_name": "SINV-1"}],
			{
				("Sales Invoice", "SINV-1"): source_from_document(
					{"currency": " USD ", "rounded_total": 100.25, "grand_total": 100}
				)
			},
		)
		self.assertEqual(
			columns,
			[{"hero_invoice_currency": "USD", "hero_invoice_amount": 100.25}],
		)

	def test_zero_rounded_total_uses_the_grand_total(self):
		source = source_from_document(
			{"currency": "EUR", "rounded_total": 0, "grand_total": 80}
		)
		columns = columns_for_references(
			[{"reference_doctype": "Purchase Invoice", "reference_name": "PINV-1"}],
			{("Purchase Invoice", "PINV-1"): source},
		)
		self.assertEqual(columns[0]["hero_invoice_currency"], "EUR")
		self.assertEqual(columns[0]["hero_invoice_amount"], 80)

	def test_negative_return_keeps_its_sign(self):
		source = source_from_document(
			{"currency": "USD", "rounded_total": -40.5, "grand_total": -39}
		)
		columns = columns_for_references(
			[{"reference_doctype": "Sales Invoice", "reference_name": "SINV-RET"}],
			{("Sales Invoice", "SINV-RET"): source},
		)
		self.assertEqual(columns[0]["hero_invoice_amount"], -40.5)

	def test_missing_currency_or_source_stays_blank(self):
		self.assertIsNone(source_from_document({"currency": "", "grand_total": 10}))
		self.assertIsNone(source_from_document(None))
		columns = columns_for_references(
			[
				{"reference_doctype": "Sales Invoice", "reference_name": "GONE"},
				{"reference_doctype": "", "reference_name": ""},
				{"reference_doctype": "Sales Order", "reference_name": "SO-1"},
			],
			{
				("Sales Order", "SO-1"): source_from_document(
					{"currency": "", "grand_total": 15}
				)
			},
		)
		self.assertEqual(
			columns,
			[
				{"hero_invoice_currency": "", "hero_invoice_amount": 0.0},
				{"hero_invoice_currency": "", "hero_invoice_amount": 0.0},
				{"hero_invoice_currency": "", "hero_invoice_amount": 0.0},
			],
		)

	def test_currency_with_no_amount_is_zero(self):
		source = source_from_document(
			{"currency": "PHP", "rounded_total": 0, "grand_total": 0}
		)
		columns = columns_for_references(
			[{"reference_doctype": "Expense Claim", "reference_name": "EXP-1"}],
			{("Expense Claim", "EXP-1"): source},
		)
		self.assertEqual(
			columns,
			[{"hero_invoice_currency": "PHP", "hero_invoice_amount": 0.0}],
		)

	def test_journal_party_lines_sum_in_one_currency(self):
		lines = [
			{
				"party_type": "Customer",
				"party": "North",
				"account_currency": "USD",
				"debit_in_account_currency": 40,
				"credit_in_account_currency": 0,
			},
			{
				"party_type": "Customer",
				"party": "North",
				"account_currency": "USD",
				"debit_in_account_currency": 60,
				"credit_in_account_currency": 0,
			},
			{
				"party_type": "Customer",
				"party": "Other",
				"account_currency": "EUR",
				"debit_in_account_currency": 10,
				"credit_in_account_currency": 0,
			},
		]
		source = source_from_journal(lines, "Customer", "North")
		self.assertEqual(source["currency"], "USD")
		self.assertEqual(source["amount"], 100)

		supplier = source_from_journal(
			[
				{
					"party_type": "Supplier",
					"party": "Mill",
					"account_currency": "EUR",
					"debit_in_account_currency": 0,
					"credit_in_account_currency": 30,
				},
				{
					"party_type": "Supplier",
					"party": "Mill",
					"account_currency": "EUR",
					"debit_in_account_currency": 5,
					"credit_in_account_currency": 0,
				},
			],
			"Supplier",
			"Mill",
		)
		self.assertEqual(supplier["amount"], 25)

	def test_journal_credit_reduces_the_customer_sum(self):
		source = source_from_journal(
			[
				{
					"party_type": "Customer",
					"party": "North",
					"account_currency": "USD",
					"debit_in_account_currency": 100,
					"credit_in_account_currency": 0,
				},
				{
					"party_type": "Customer",
					"party": "North",
					"account_currency": "USD",
					"debit_in_account_currency": 0,
					"credit_in_account_currency": 25,
				},
			],
			"Customer",
			"North",
		)
		self.assertEqual(source["amount"], 75)

	def test_journal_mixed_currency_is_blank(self):
		self.assertIsNone(
			source_from_journal(
				[
					{
						"party_type": "Customer",
						"party": "North",
						"account_currency": "USD",
						"debit_in_account_currency": 10,
						"credit_in_account_currency": 0,
					},
					{
						"party_type": "Customer",
						"party": "North",
						"account_currency": "EUR",
						"debit_in_account_currency": 10,
						"credit_in_account_currency": 0,
					},
				],
				"Customer",
				"North",
			)
		)
		self.assertIsNone(source_from_journal([], "Customer", "North"))

	def test_dunning_uses_grand_total_then_dunning_amount(self):
		self.assertIsNone(
			source_from_dunning({"currency": "USD", "grand_total": 20}, has_currency_field=False)
		)
		self.assertIsNone(source_from_dunning({"currency": "", "grand_total": 20}, True))
		grand = source_from_dunning(
			{"currency": "USD", "grand_total": 20, "dunning_amount": 5}, True
		)
		fallback = source_from_dunning(
			{"currency": "USD", "grand_total": 0, "dunning_amount": 15}, True
		)
		columns = columns_for_references(
			[
				{"reference_doctype": "Dunning", "reference_name": "DUN-1"},
				{"reference_doctype": "Dunning", "reference_name": "DUN-2"},
			],
			{("Dunning", "DUN-1"): grand, ("Dunning", "DUN-2"): fallback},
		)
		self.assertEqual(columns[0]["hero_invoice_amount"], 20)
		self.assertEqual(columns[1]["hero_invoice_currency"], "USD")
		self.assertEqual(columns[1]["hero_invoice_amount"], 15)

	def test_columns_are_written_on_draft_save_and_submit_only(self):
		self.assertTrue(should_write_invoice_currency(0, "save"))
		self.assertTrue(should_write_invoice_currency(0, None))
		self.assertTrue(should_write_invoice_currency(1, "submit"))
		self.assertFalse(should_write_invoice_currency(1, "update_after_submit"))
		self.assertFalse(should_write_invoice_currency(1, None))
		self.assertFalse(should_write_invoice_currency(2, "cancel"))

	def test_mixed_rows_stay_independent(self):
		journal = source_from_journal(
			[
				{
					"party_type": "Customer",
					"party": "North",
					"account_currency": "USD",
					"debit_in_account_currency": 40,
					"credit_in_account_currency": 0,
				},
				{
					"party_type": "Customer",
					"party": "North",
					"account_currency": "USD",
					"debit_in_account_currency": 60,
					"credit_in_account_currency": 0,
				},
			],
			"Customer",
			"North",
		)
		columns = columns_for_references(
			[
				{"reference_doctype": "Sales Invoice", "reference_name": "SINV-1"},
				{"reference_doctype": "Sales Invoice", "reference_name": ""},
				{"reference_doctype": "Journal Entry", "reference_name": "JV-1"},
				{"reference_doctype": "Purchase Order", "reference_name": "PO-MISSING"},
			],
			{
				("Sales Invoice", "SINV-1"): source_from_document(
					{"currency": "PHP", "rounded_total": 0, "grand_total": 56000}
				),
				("Journal Entry", "JV-1"): journal,
			},
		)
		self.assertEqual(
			[column["hero_invoice_currency"] for column in columns],
			["PHP", "", "USD", ""],
		)
		self.assertEqual(
			[column["hero_invoice_amount"] for column in columns],
			[56000, 0.0, 100, 0.0],
		)
