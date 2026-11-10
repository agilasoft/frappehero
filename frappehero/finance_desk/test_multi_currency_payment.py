# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest
from decimal import Decimal
from pathlib import Path

from frappehero.finance_desk.multi_currency_payment_logic import (
	MultiCurrencyPaymentError,
	header_account,
	paid_and_received,
	party_side_amount,
	payment_type_for,
	prepare_payment,
	spans_accounts,
)

PACKAGE = Path(__file__).resolve().parent


def _payment(**overrides):
	payment = {
		"party_type": "Supplier",
		"party": "Acme",
		"company_currency": "PHP",
		"payment_currency": "USD",
		"payment_exchange_rate": 56,
		"bank_account": "Bank USD",
		"gain_loss_account": "Exchange Gain/Loss",
		"cost_center": "Main",
	}
	payment.update(overrides)
	return payment


def _invoice(
	name,
	currency,
	account,
	allocated,
	outstanding=None,
	booked_rate=1,
	payment_rate=1,
	doctype="Purchase Invoice",
):
	return {
		"account": account,
		"account_currency": currency,
		"reference_doctype": doctype,
		"reference_name": name,
		"invoice_currency": currency,
		"outstanding_amount": outstanding if outstanding is not None else allocated,
		"allocated_amount": allocated,
		"booked_rate": booked_rate,
		"payment_rate": payment_rate,
	}


def _balanced(accounts):
	debit = sum((Decimal(str(row["debit"])) for row in accounts), Decimal(0))
	credit = sum((Decimal(str(row["credit"])) for row in accounts), Decimal(0))
	return debit, credit


class TestMultiCurrencyPayment(unittest.TestCase):
	def test_usd_bank_clears_usd_php_and_eur_invoices(self):
		result = prepare_payment(
			_payment(paid_amount=892.86),
			[
				_invoice("PINV-USD", "USD", "Creditors USD", 500, booked_rate=55, payment_rate=56),
				_invoice("PINV-PHP", "PHP", "Creditors PHP", 10000, booked_rate=1, payment_rate=1),
				_invoice("PINV-EUR", "EUR", "Creditors EUR", 200, booked_rate=58, payment_rate=60),
			],
		)
		self.assertEqual(result["payment_type"], "Pay")
		self.assertEqual(result["multi_currency"], 1)
		self.assertEqual(
			[row["payment_amount"] for row in result["allocations"]],
			[500, 178.57, 214.29],
		)
		self.assertEqual(result["allocated_amount"], 892.86)
		self.assertEqual(result["unallocated_amount"], 0)
		self.assertEqual(result["paid_amount"], 892.86)
		self.assertEqual(result["base_paid_amount"], 50000.16)
		self.assertEqual(result["exchange_gain_loss"], -900.16)
		party = [row for row in result["accounts"] if row["reference_name"]]
		self.assertEqual(
			[
				(row["account"], row["debit_in_account_currency"], row["exchange_rate"], row["debit"])
				for row in party
			],
			[
				("Creditors USD", 500, 55, 27500),
				("Creditors PHP", 10000, 1, 10000),
				("Creditors EUR", 200, 58, 11600),
			],
		)
		self.assertTrue(all(row["credit"] == 0 for row in party))
		gain = next(row for row in result["accounts"] if row["account"] == "Exchange Gain/Loss")
		self.assertEqual(gain["debit"], 900.16)
		self.assertEqual(gain["cost_center"], "Main")
		bank = result["accounts"][-1]
		self.assertEqual(bank["account"], "Bank USD")
		self.assertEqual(bank["account_currency"], "USD")
		self.assertEqual(bank["credit_in_account_currency"], 892.86)
		self.assertEqual(bank["exchange_rate"], 56)
		self.assertEqual(bank["credit"], 50000.16)
		self.assertEqual(_balanced(result["accounts"])[0], _balanced(result["accounts"])[1])

	def test_same_currency_payment_has_no_gain_or_loss(self):
		result = prepare_payment(
			_payment(paid_amount=100),
			[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=56, payment_rate=56)],
		)
		self.assertEqual(result["exchange_gain_loss"], 0)
		self.assertEqual([row["account"] for row in result["accounts"]], ["Creditors USD", "Bank USD"])
		self.assertEqual(result["accounts"][0]["debit"], 5600)
		self.assertEqual(result["accounts"][1]["credit"], 5600)
		self.assertIsNone(result["advance"])

	def test_company_currency_payment_is_not_multi_currency(self):
		result = prepare_payment(
			_payment(
				company_currency="USD",
				payment_currency="USD",
				payment_exchange_rate=1,
				bank_account="Bank USD",
				paid_amount=100,
			),
			[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=1, payment_rate=1)],
		)
		self.assertEqual(result["multi_currency"], 0)
		self.assertEqual(result["accounts"][0]["debit"], 100)
		self.assertEqual(result["accounts"][1]["credit"], 100)

	def test_booked_rate_difference_is_a_supplier_loss(self):
		result = prepare_payment(
			_payment(paid_amount=100),
			[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=50, payment_rate=56)],
		)
		self.assertEqual(result["exchange_gain_loss"], -600)
		self.assertEqual(result["accounts"][0]["debit"], 5000)
		self.assertEqual(result["accounts"][0]["exchange_rate"], 50)
		gain = result["accounts"][1]
		self.assertEqual(gain["debit"], 600)
		self.assertEqual(gain["debit_in_account_currency"], 600)
		self.assertEqual(result["accounts"][2]["credit"], 5600)

	def test_customer_receipt_reverses_the_sides(self):
		result = prepare_payment(
			_payment(party_type="Customer", party="Northwind", paid_amount=100),
			[
				_invoice(
					"SINV-USD",
					"USD",
					"Debtors USD",
					100,
					booked_rate=50,
					payment_rate=56,
					doctype="Sales Invoice",
				)
			],
		)
		self.assertEqual(result["payment_type"], "Receive")
		self.assertEqual(result["exchange_gain_loss"], 600)
		party = result["accounts"][0]
		self.assertEqual(party["credit_in_account_currency"], 100)
		self.assertEqual(party["credit"], 5000)
		self.assertEqual(party["debit"], 0)
		self.assertEqual(result["accounts"][1]["credit"], 600)
		bank = result["accounts"][-1]
		self.assertEqual(bank["debit_in_account_currency"], 100)
		self.assertEqual(bank["debit"], 5600)
		self.assertEqual(_balanced(result["accounts"])[0], _balanced(result["accounts"])[1])

	def test_matching_bank_currency_uses_the_invoice_amount(self):
		result = prepare_payment(
			_payment(paid_amount=500),
			[_invoice("PINV-USD", "USD", "Creditors USD", 500, booked_rate=55, payment_rate=70)],
		)
		self.assertEqual(result["allocations"][0]["payment_amount"], 500)
		self.assertEqual(result["allocations"][0]["payment_rate"], 70)

	def test_blank_paid_amount_uses_the_allocated_total(self):
		result = prepare_payment(
			_payment(),
			[_invoice("PINV-USD", "USD", "Creditors USD", 40, booked_rate=56, payment_rate=56)],
		)
		self.assertEqual(result["paid_amount"], 40)
		self.assertEqual(result["unallocated_amount"], 0)

	def test_amount_above_the_allocation_is_an_advance(self):
		result = prepare_payment(
			_payment(
				paid_amount=150,
				advance_account="Creditors USD",
				advance_account_currency="USD",
			),
			[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=56, payment_rate=56)],
		)
		self.assertEqual(result["unallocated_amount"], 50)
		self.assertEqual(result["exchange_gain_loss"], 0)
		self.assertEqual(
			result["advance"],
			{
				"account": "Creditors USD",
				"account_currency": "USD",
				"amount": 50,
				"exchange_rate": 56,
				"base": 2800,
			},
		)
		advance = next(row for row in result["accounts"] if row["is_advance"] == "Yes")
		self.assertEqual(advance["account"], "Creditors USD")
		self.assertEqual(advance["debit_in_account_currency"], 50)
		self.assertEqual(advance["reference_name"], "")
		self.assertEqual(advance["party"], "Acme")
		bank = result["accounts"][-1]
		self.assertEqual(bank["credit_in_account_currency"], 150)
		self.assertEqual(bank["credit"], 8400)
		self.assertEqual(_balanced(result["accounts"])[0], _balanced(result["accounts"])[1])

	def test_advance_in_a_third_currency_leaves_the_rounding_on_gain_or_loss(self):
		result = prepare_payment(
			_payment(
				paid_amount=150,
				advance_account="Creditors EUR",
				advance_account_currency="EUR",
				advance_exchange_rate=60,
			),
			[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=56, payment_rate=56)],
		)
		self.assertEqual(result["advance"]["amount"], 46.67)
		self.assertEqual(result["advance"]["base"], 2800.2)
		gain = next(row for row in result["accounts"] if row["account"] == "Exchange Gain/Loss")
		self.assertEqual(gain["credit"], 0.2)
		self.assertEqual(_balanced(result["accounts"])[0], _balanced(result["accounts"])[1])

	def test_company_currency_account_posts_at_one(self):
		result = prepare_payment(
			_payment(paid_amount=100),
			[_invoice("PINV-PHP", "PHP", "Creditors PHP", 5600, booked_rate=58, payment_rate=4)],
		)
		row = result["allocations"][0]
		self.assertEqual(row["booked_rate"], 1)
		self.assertEqual(row["payment_rate"], 1)
		self.assertEqual(row["payment_amount"], 100)
		self.assertEqual(result["exchange_gain_loss"], 0)
		self.assertEqual(result["accounts"][0]["debit"], 5600)

	def test_over_allocation_is_rejected(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=101),
				[
					_invoice(
						"PINV-USD",
						"USD",
						"Creditors USD",
						101,
						outstanding=100,
						booked_rate=56,
						payment_rate=56,
					)
				],
			)
		self.assertIn("cannot be greater than outstanding 100", str(caught.exception))

	def test_duplicate_invoice_is_rejected(self):
		row = _invoice(
			"PINV-USD", "USD", "Creditors USD", 10, outstanding=20, booked_rate=56, payment_rate=56
		)
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(_payment(paid_amount=20), [row, dict(row)])
		self.assertIn("already on this payment", str(caught.exception))

	def test_account_currency_must_match_the_invoice(self):
		row = _invoice("PINV-EUR", "EUR", "Creditors PHP", 200, booked_rate=58, payment_rate=60)
		row["account_currency"] = "PHP"
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(_payment(), [row])
		self.assertIn("Creditors PHP is in PHP", str(caught.exception))
		self.assertIn("is in EUR", str(caught.exception))

	def test_short_payment_is_rejected(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=90),
				[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=56, payment_rate=56)],
			)
		self.assertIn("less than the allocated total 100", str(caught.exception))

	def test_advance_account_is_required_when_the_paid_amount_is_higher(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=150),
				[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=56, payment_rate=56)],
			)
		self.assertIn("Choose an advance account", str(caught.exception))

	def test_rate_difference_needs_a_gain_or_loss_account(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=100, gain_loss_account="", cost_center=""),
				[_invoice("PINV-USD", "USD", "Creditors USD", 100, booked_rate=50, payment_rate=56)],
			)
		self.assertIn("exchange gain/loss account", str(caught.exception))

	def test_supplier_cannot_allocate_a_sales_invoice(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=10),
				[
					_invoice(
						"SINV-1",
						"USD",
						"Debtors USD",
						10,
						booked_rate=56,
						payment_rate=56,
						doctype="Sales Invoice",
					)
				],
			)
		self.assertIn("allocates Purchase Invoices", str(caught.exception))

	def test_negative_allocation_is_rejected(self):
		with self.assertRaises(MultiCurrencyPaymentError) as caught:
			prepare_payment(
				_payment(paid_amount=10),
				[
					_invoice(
						"PINV-USD",
						"USD",
						"Creditors USD",
						-10,
						outstanding=10,
						booked_rate=56,
						payment_rate=56,
					)
				],
			)
		self.assertIn("cannot be negative", str(caught.exception))

	def test_payment_type_follows_the_party(self):
		self.assertEqual(payment_type_for(" Customer "), "Receive")
		self.assertEqual(payment_type_for("Supplier"), "Pay")
		with self.assertRaises(MultiCurrencyPaymentError):
			payment_type_for("Employee")

	def test_one_party_account_stays_with_payment_entry(self):
		self.assertFalse(spans_accounts("Creditors USD", ["Creditors USD"]))
		self.assertFalse(spans_accounts("", ["Creditors USD"]))
		self.assertTrue(spans_accounts("Creditors USD", ["Creditors USD", "Creditors PHP"]))
		self.assertTrue(spans_accounts("Creditors PHP", ["Creditors USD"]))
		self.assertEqual(header_account("Creditors PHP", ["Creditors USD", "Creditors PHP"]), "Creditors PHP")
		self.assertEqual(header_account("Creditors PHP", ["Creditors USD", "Creditors EUR"]), "Creditors USD")
		self.assertEqual(header_account("", []), "")
		self.assertEqual(
			party_side_amount(
				"Creditors USD",
				[
					{"account": "Creditors USD", "allocated_amount": 100},
					{"account": "Creditors EUR", "allocated_amount": 50},
				],
				{"account": "Creditors USD", "amount": 20},
			),
			120,
		)
		self.assertEqual(paid_and_received("Pay", 892.86, "USD", "USD", 500), (892.86, 892.86))
		self.assertEqual(paid_and_received("Pay", 892.86, "USD", "PHP", 10000), (892.86, 10000))
		self.assertEqual(paid_and_received("Receive", 892.86, "USD", "EUR", 200), (200, 892.86))

	def test_payment_entry_owns_the_multi_currency_voucher(self):
		hooks = (PACKAGE.parent / "hooks.py").read_text()
		install = (PACKAGE.parent / "install.py").read_text()
		controller = (PACKAGE / "payment_entry.py").read_text()
		script = (PACKAGE.parent / "public" / "js" / "payment_entry_multi.js").read_text()
		self.assertIn('"Payment Entry": "frappehero.finance_desk.payment_entry.PaymentEntry"', hooks)
		self.assertIn("public/js/payment_entry_multi.js", hooks)
		self.assertIn("frappehero.finance_desk.multi_currency_payment.apply_to_payment", hooks)
		self.assertNotIn("Hero Multi Currency Payment", hooks)
		for fieldname in (
			"hero_multi_account",
			"hero_account",
			"hero_account_currency",
			"hero_booked_rate",
			"hero_payment_rate",
			"hero_payment_currency",
			"hero_bank_amount",
		):
			self.assertIn(f'"{fieldname}"', install)
		self.assertIn("Hero Multi Currency Payment", install)
		self.assertIn("def build_gl_map", controller)
		self.assertIn("def make_gl_entries", controller)
		self.assertNotIn("make_exchange_gain_loss_journal(", controller)
		self.assertIn("Get Outstanding Invoices", script)
		self.assertIn("outstanding_invoices", script)
		self.assertFalse((PACKAGE / "doctype" / "hero_multi_currency_payment").exists())
		self.assertFalse((PACKAGE / "doctype" / "hero_multi_currency_allocation").exists())


if __name__ == "__main__":
	unittest.main()
