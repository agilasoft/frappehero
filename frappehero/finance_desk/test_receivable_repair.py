# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.receivable_repair_logic import (
	ReceivableRepairError,
	account_for_currency,
	check_accounts,
	outstanding_matches,
	party_account_choice,
	plan_repair,
	selection_matches,
)

COMPANY = "ATN"
WRONG = "11220.20.30 - Cash Advance on Behalf of Shipper - ATN"
USD_ACCOUNT = "11210.10.10 - Trade Receivables (USD) - ATN"
OTHER = "11210.10.00 - Trade Receivables - ATN"
BANK = "Bank - ATN"


def _accounts():
	return {
		WRONG: {"company": COMPANY, "account_type": "Receivable", "account_currency": "PHP", "is_group": 0},
		USD_ACCOUNT: {
			"company": COMPANY,
			"account_type": "Receivable",
			"account_currency": "USD",
			"is_group": 0,
		},
		OTHER: {"company": COMPANY, "account_type": "Receivable", "account_currency": "PHP", "is_group": 0},
	}


def _invoice(name, currency, outstanding=100, rate=1, debit_to=WRONG, **extra):
	row = {
		"name": name,
		"company": COMPANY,
		"docstatus": 1,
		"currency": currency,
		"debit_to": debit_to,
		"outstanding_amount": outstanding,
		"conversion_rate": rate,
		"party_account_currency": "PHP",
		"customer": "Acme",
		"posting_date": "2026-01-01",
		"is_return": 0,
		"return_against": "",
	}
	row.update(extra)
	return row


def _payment(name, references, **extra):
	row = {
		"name": name,
		"company": COMPANY,
		"docstatus": 1,
		"payment_type": "Receive",
		"party": "Acme",
		"paid_from": WRONG,
		"paid_from_account_currency": "PHP",
		"paid_to": BANK,
		"paid_to_account_currency": "PHP",
		"paid_amount": 100,
		"received_amount": 100,
		"base_paid_amount": 100,
		"base_received_amount": 100,
		"source_exchange_rate": 1,
		"unallocated_amount": 0,
		"posting_date": "2026-02-01",
		"references": references,
	}
	row.update(extra)
	return row


def _reference(name, allocated, rate=1, hero=None, doctype="Sales Invoice"):
	return {
		"row_name": f"row-{name}",
		"reference_doctype": doctype,
		"reference_name": name,
		"allocated_amount": allocated,
		"exchange_rate": rate,
		"hero_allocated_invoice_amount": hero,
	}


class TestAccountChoice(unittest.TestCase):
	def test_usd_and_other_currencies(self):
		self.assertEqual(account_for_currency("USD", USD_ACCOUNT, OTHER), USD_ACCOUNT)
		self.assertEqual(account_for_currency(" usd ", USD_ACCOUNT, OTHER), USD_ACCOUNT)
		self.assertEqual(account_for_currency("PHP", USD_ACCOUNT, OTHER), OTHER)
		self.assertEqual(account_for_currency("EUR", USD_ACCOUNT, OTHER), OTHER)

	def test_party_account_follows_open_invoice_currencies(self):
		self.assertEqual(party_account_choice("Customer", ["USD", "USD"], USD_ACCOUNT, OTHER), USD_ACCOUNT)
		self.assertEqual(party_account_choice("Customer", ["USD", "PHP"], USD_ACCOUNT, OTHER), OTHER)
		self.assertEqual(party_account_choice("Customer", [], USD_ACCOUNT, OTHER), OTHER)
		self.assertEqual(party_account_choice("Customer Group", ["USD"], USD_ACCOUNT, OTHER), OTHER)

	def test_destinations_must_be_receivables_in_the_company_currency(self):
		check_accounts(COMPANY, "PHP", WRONG, USD_ACCOUNT, OTHER, _accounts())
		broken = _accounts()
		broken[USD_ACCOUNT] = dict(broken[USD_ACCOUNT], account_currency="PHP")
		with self.assertRaises(ReceivableRepairError):
			check_accounts(COMPANY, "PHP", WRONG, USD_ACCOUNT, OTHER, broken)
		broken = _accounts()
		broken[OTHER] = dict(broken[OTHER], account_type="Cash", account_currency="PHP")
		with self.assertRaises(ReceivableRepairError):
			check_accounts(COMPANY, "PHP", WRONG, USD_ACCOUNT, OTHER, broken)
		with self.assertRaises(ReceivableRepairError):
			check_accounts(COMPANY, "PHP", WRONG, USD_ACCOUNT, USD_ACCOUNT, _accounts())


class TestRepairPlan(unittest.TestCase):
	def test_usd_receipt_keeps_the_bank_amount(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", outstanding=40, rate=56)],
			[
				_payment(
					"PE-USD",
					[_reference("SI-USD", 3360, rate=56)],
					paid_amount=3360,
					received_amount=3360,
					base_paid_amount=3360,
					base_received_amount=3360,
				)
			],
		)
		invoice = plan["invoices"][0]
		payment = plan["payments"][0]
		self.assertEqual(invoice["action"], "move")
		self.assertEqual(invoice["to_account"], USD_ACCOUNT)
		self.assertEqual(invoice["account_currency"], "USD")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["bank_amount"], 3360)
		self.assertEqual(payment["bank_account"], BANK)
		self.assertEqual(payment["party_account"], USD_ACCOUNT)
		self.assertEqual(payment["party_amount"], 60)
		self.assertEqual(payment["party_exchange_rate"], 56)
		self.assertEqual(payment["references"][0]["allocated_amount"], 60)
		self.assertEqual(payment["references"][0]["invoice_amount"], 60)
		self.assertEqual(payment["references"][0]["exchange_rate"], 56)
		self.assertEqual(payment["keep_amounts"], 0)

	def test_other_currency_changes_the_account_and_keeps_the_amount(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-PHP", "PHP", outstanding=80), _invoice("SI-EUR", "EUR", outstanding=10, rate=60)],
			[_payment("PE-PHP", [_reference("SI-PHP", 20)])],
		)
		by_name = {row["name"]: row for row in plan["invoices"]}
		self.assertEqual(by_name["SI-PHP"]["to_account"], OTHER)
		self.assertEqual(by_name["SI-EUR"]["to_account"], OTHER)
		payment = plan["payments"][0]
		self.assertEqual(payment["party_account"], OTHER)
		self.assertEqual(payment["party_amount"], 20)
		self.assertEqual(payment["bank_amount"], 100)
		self.assertEqual(payment["party_exchange_rate"], 1)
		self.assertEqual(payment["keep_amounts"], 1)
		self.assertEqual(payment["references"][0]["allocated_amount"], 20)

	def test_credit_note_keeps_its_return_link(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[
				_invoice("SI-1", "USD", rate=56),
				_invoice("CN-1", "USD", outstanding=-20, rate=56, is_return=1, return_against="SI-1"),
			],
			[],
		)
		note = next(row for row in plan["invoices"] if row["name"] == "CN-1")
		self.assertEqual(note["is_return"], 1)
		self.assertEqual(note["return_against"], "SI-1")
		self.assertEqual(note["to_account"], USD_ACCOUNT)
		self.assertEqual(plan["chains"], [{"invoices": ["CN-1", "SI-1"], "payments": []}])

	def test_mixed_currencies_stay_on_one_receipt(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", rate=56), _invoice("SI-PHP", "PHP")],
			[
				_payment(
					"PE-MIX",
					[_reference("SI-USD", 5600, rate=56), _reference("SI-PHP", 100)],
					received_amount=5700,
					paid_amount=5700,
					base_paid_amount=5700,
				)
			],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "multi")
		self.assertEqual(payment["bank_amount"], 5700)
		self.assertEqual({row["account"] for row in payment["references"]}, {USD_ACCOUNT, OTHER})
		self.assertEqual(plan["counts"]["move_payments"], 1)

	def test_unallocated_advance_stays_on_the_old_account(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", rate=56)],
			[
				_payment(
					"PE-ADV",
					[_reference("SI-USD", 5600, rate=56)],
					paid_amount=6160,
					received_amount=6160,
					base_paid_amount=6160,
					unallocated_amount=560,
				)
			],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "multi")
		self.assertEqual(payment["advance_account"], WRONG)
		self.assertEqual(payment["bank_amount"], 6160)
		self.assertEqual(payment["references"][0]["account"], USD_ACCOUNT)

	def test_taxes_hold_a_split_receipt_and_its_invoices(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", rate=56), _invoice("SI-PHP", "PHP")],
			[_payment("PE-TAX", [_reference("SI-USD", 56, rate=56), _reference("SI-PHP", 10)], has_taxes=1)],
		)
		self.assertEqual(plan["signature"], {"invoices": [], "payments": []})
		self.assertTrue(all(row["action"] == "held" for row in plan["invoices"]))
		self.assertIn("taxes or deductions", plan["payments"][0]["reason"])
		self.assertIn("PE-TAX", plan["invoices"][0]["reason"])

	def test_taxes_on_one_company_currency_account_still_move(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-PHP", "PHP")],
			[
				_payment(
					"PE-TAX", [_reference("SI-PHP", 100)], has_taxes=1, paid_amount=100, received_amount=100
				)
			],
		)
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(plan["payments"][0]["mode"], "single")
		self.assertEqual(plan["payments"][0]["party_account"], OTHER)

	def test_taxes_hold_a_currency_change(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", rate=56)],
			[_payment("PE-TAX", [_reference("SI-USD", 5600, rate=56)], has_deductions=1)],
		)
		self.assertEqual(plan["invoices"][0]["action"], "held")
		self.assertIn("currency", plan["payments"][0]["reason"])

	def test_a_held_receipt_holds_the_other_receipt_on_the_same_invoice(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-1", "USD", rate=56), _invoice("SI-2", "PHP")],
			[
				_payment("PE-A", [_reference("SI-1", 56, rate=56), _reference("SI-2", 10)], has_taxes=1),
				_payment("PE-B", [_reference("SI-2", 5)]),
			],
		)
		self.assertEqual(plan["signature"]["invoices"], [])
		self.assertEqual(plan["signature"]["payments"], [])
		reasons = {row["name"]: row["reason"] for row in plan["payments"]}
		self.assertIn("SI-2", reasons["PE-B"])

	def test_journal_reference_holds_the_receipt(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-1", "PHP")],
			[_payment("PE-JE", [_reference("SI-1", 10), _reference("JV-1", 5, doctype="Journal Entry")])],
		)
		self.assertEqual(plan["invoices"][0]["action"], "held")
		self.assertIn("not a sales invoice", plan["payments"][0]["reason"])

	def test_cancelled_and_other_accounts_are_left_out(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[
				_invoice("SI-OK", "PHP"),
				_invoice("SI-CANCEL", "PHP", docstatus=2),
				_invoice("SI-OTHER", "USD", debit_to=USD_ACCOUNT),
				_invoice("SI-AWAY", "PHP", company="Other"),
			],
			[
				_payment("PE-OK", [_reference("SI-OK", 10)]),
				_payment("PE-CANCEL", [_reference("SI-OK", 10)], docstatus=2),
				_payment("PE-ADVANCE", [], paid_from=WRONG, unallocated_amount=50),
			],
		)
		self.assertEqual([row["name"] for row in plan["invoices"]], ["SI-OK"])
		self.assertEqual([row["name"] for row in plan["payments"]], ["PE-OK"])

	def test_two_invoices_are_separate_chains(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-A", "PHP"), _invoice("SI-B", "EUR", rate=60)],
			[_payment("PE-B", [_reference("SI-B", 60, rate=60)])],
		)
		self.assertEqual(
			plan["chains"],
			[
				{"invoices": ["SI-A"], "payments": []},
				{"invoices": ["SI-B"], "payments": ["PE-B"]},
			],
		)
		self.assertTrue(selection_matches(plan["signature"], plan))
		self.assertFalse(selection_matches({"invoices": ["SI-A"], "payments": []}, plan))

	def test_a_zero_hero_amount_is_an_empty_field(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", outstanding=40, rate=56)],
			[
				_payment(
					"PE-USD",
					[_reference("SI-USD", 3360, rate=1, hero=0)],
					paid_amount=3360,
					received_amount=3360,
					base_paid_amount=3360,
					base_received_amount=3360,
				)
			],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["party_amount"], 60)
		self.assertEqual(payment["party_exchange_rate"], 56)
		self.assertEqual(payment["references"][0]["allocated_amount"], 60)
		self.assertEqual(payment["references"][0]["invoice_amount"], 60)
		self.assertEqual(payment["base_party_amount"], 3360)

	def test_outstanding_follows_the_invoice_when_the_receivable_currency_changes(self):
		self.assertTrue(outstanding_matches(5600, 100, "PHP", "USD", "USD", 56, "PHP"))
		self.assertTrue(outstanding_matches(0, 0, "PHP", "USD", "USD", 56, "PHP"))
		self.assertTrue(outstanding_matches(100, 100, "PHP", "PHP", "PHP", 1, "PHP"))
		self.assertFalse(outstanding_matches(5600, 100, "PHP", "PHP", "USD", 56, "PHP"))
		self.assertFalse(outstanding_matches(5600, 90, "PHP", "USD", "USD", 56, "PHP"))

	def test_hero_amount_is_the_invoice_allocation(self):
		plan = plan_repair(
			COMPANY,
			WRONG,
			USD_ACCOUNT,
			OTHER,
			"PHP",
			[_invoice("SI-USD", "USD", rate=56)],
			[
				_payment(
					"PE-1",
					[_reference("SI-USD", 3360, rate=1, hero=60)],
					base_paid_amount=3360,
					paid_amount=3360,
					received_amount=3360,
				)
			],
		)
		self.assertEqual(plan["payments"][0]["references"][0]["invoice_amount"], 60)
		self.assertEqual(plan["payments"][0]["party_amount"], 60)
