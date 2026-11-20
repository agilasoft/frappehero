# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.party_reclass_logic import (
	PartyReclassError,
	check_accounts,
	plan_reclass,
	selection_matches,
	side_choice,
)

COMPANY = "ATN"
OLD_AR = "11220 - Cash Advance - ATN"
NEW_AR = "11210 - Trade Receivables - ATN"
USD_AR = "11211 - Trade Receivables USD - ATN"
OTHER_AR = "11212 - Other Receivable - ATN"
OLD_AP = "21110 - Trade Payables - ATN"
NEW_AP = "21120 - Other Payables - ATN"
BANK = "Bank - ATN"
EXPENSE = "Expense - ATN"


def _accounts():
	return {
		OLD_AR: {"company": COMPANY, "account_type": "Receivable", "account_currency": "PHP", "is_group": 0},
		NEW_AR: {"company": COMPANY, "account_type": "Receivable", "account_currency": "PHP", "is_group": 0},
		USD_AR: {"company": COMPANY, "account_type": "Receivable", "account_currency": "USD", "is_group": 0},
		OTHER_AR: {
			"company": COMPANY,
			"account_type": "Receivable",
			"account_currency": "PHP",
			"is_group": 0,
		},
		OLD_AP: {"company": COMPANY, "account_type": "Payable", "account_currency": "PHP", "is_group": 0},
		NEW_AP: {"company": COMPANY, "account_type": "Payable", "account_currency": "PHP", "is_group": 0},
	}


def _invoice(name, account=OLD_AR, doctype="Sales Invoice", **extra):
	row = {
		"name": name,
		"company": COMPANY,
		"docstatus": 1,
		"doctype": doctype,
		"currency": "PHP",
		"account": account,
		"outstanding_amount": 80,
		"party_account_currency": "PHP",
		"party": "Acme",
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
		"paid_from": OLD_AR,
		"paid_from_account_currency": "PHP",
		"paid_to": BANK,
		"paid_to_account_currency": "PHP",
		"paid_amount": 100,
		"received_amount": 100,
		"unallocated_amount": 0,
		"posting_date": "2026-02-01",
		"references": references,
	}
	row.update(extra)
	return row


def _reference(name, allocated=20, doctype="Sales Invoice"):
	return {
		"row_name": f"row-{name}",
		"reference_doctype": doctype,
		"reference_name": name,
		"allocated_amount": allocated,
	}


def _journal(name, lines, **extra):
	row = {
		"name": name,
		"company": COMPANY,
		"docstatus": 1,
		"posting_date": "2026-03-01",
		"voucher_type": "Journal Entry",
		"lines": lines,
	}
	row.update(extra)
	return row


def _line(account, reference, debit=20, doctype="Sales Invoice"):
	return {
		"row_name": f"je-{reference}",
		"account": account,
		"reference_type": doctype,
		"reference_name": reference,
		"debit": debit,
		"credit": 0,
	}


class TestAccountChoice(unittest.TestCase):
	def test_side_selects_the_invoice_and_the_account_type(self):
		sales = side_choice("Receivable")
		self.assertEqual(sales["doctype"], "Sales Invoice")
		self.assertEqual(sales["account_field"], "debit_to")
		purchase = side_choice("payable")
		self.assertEqual(purchase["doctype"], "Purchase Invoice")
		self.assertEqual(purchase["account_field"], "credit_to")
		with self.assertRaises(PartyReclassError):
			side_choice("Bank")

	def test_accounts_must_match_the_side_and_the_currency(self):
		self.assertEqual(check_accounts(COMPANY, "receivable", OLD_AR, NEW_AR, _accounts()), "PHP")
		self.assertEqual(check_accounts(COMPANY, "payable", OLD_AP, NEW_AP, _accounts()), "PHP")
		with self.assertRaises(PartyReclassError):
			check_accounts(COMPANY, "receivable", OLD_AR, USD_AR, _accounts())
		with self.assertRaises(PartyReclassError):
			check_accounts(COMPANY, "receivable", OLD_AR, OLD_AP, _accounts())
		with self.assertRaises(PartyReclassError):
			check_accounts(COMPANY, "receivable", OLD_AR, OLD_AR, _accounts())


class TestReclassPlan(unittest.TestCase):
	def test_receipt_keeps_its_bank_amount_and_allocation(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1", 100)], received_amount=100, paid_amount=100)],
			[],
		)
		invoice = plan["invoices"][0]
		payment = plan["payments"][0]
		self.assertEqual(invoice["action"], "move")
		self.assertEqual(invoice["to_account"], NEW_AR)
		self.assertEqual(invoice["account_field"], "debit_to")
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], NEW_AR)
		self.assertEqual(payment["rewrite_party"], 1)
		self.assertEqual(payment["bank_amount"], 100)
		self.assertEqual(payment["references"][0]["allocated_amount"], 100)
		self.assertEqual(payment["references"][0]["account"], NEW_AR)
		self.assertEqual(plan["chains"], [{"invoices": ["SI-1"], "payments": ["PE-1"], "journals": []}])

	def test_unallocated_advance_moves_with_the_same_receipt(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1", 80)], unallocated_amount=20, received_amount=100)],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], NEW_AR)
		self.assertEqual(payment["unallocated_amount"], 20)
		self.assertEqual(payment["bank_amount"], 100)

	def test_supplier_payment_uses_the_payable(self):
		plan = plan_reclass(
			COMPANY,
			"payable",
			OLD_AP,
			NEW_AP,
			[_invoice("PI-1", account=OLD_AP, doctype="Purchase Invoice")],
			[
				_payment(
					"PE-1",
					[_reference("PI-1", 40, doctype="Purchase Invoice")],
					payment_type="Pay",
					paid_from=BANK,
					paid_to=OLD_AP,
					paid_to_account_currency="PHP",
					paid_amount=40,
					received_amount=40,
				)
			],
			[],
		)
		self.assertEqual(plan["doctype"], "Purchase Invoice")
		self.assertEqual(plan["invoices"][0]["account_field"], "credit_to")
		payment = plan["payments"][0]
		self.assertEqual(payment["party_account"], NEW_AP)
		self.assertEqual(payment["party_account_field"], "paid_to")
		self.assertEqual(payment["bank_amount"], 40)
		self.assertEqual(payment["bank_account"], BANK)

	def test_credit_note_stays_with_its_invoice(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[
				_invoice("SI-1"),
				_invoice("CN-1", outstanding=-20, is_return=1, return_against="SI-1"),
			],
			[],
			[],
		)
		self.assertEqual(plan["chains"], [{"invoices": ["CN-1", "SI-1"], "payments": [], "journals": []}])

	def test_journal_line_moves_and_the_other_line_stays(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[],
			[
				_journal(
					"JE-1",
					[
						_line(OLD_AR, "SI-1", debit=20),
						{
							"row_name": "je-expense",
							"account": EXPENSE,
							"reference_type": "",
							"reference_name": "",
							"debit": 0,
							"credit": 20,
						},
					],
				)
			],
		)
		journal = plan["journals"][0]
		self.assertEqual(journal["action"], "move")
		self.assertEqual(journal["lines"][0]["action"], "move")
		self.assertEqual(journal["lines"][0]["account"], NEW_AR)
		self.assertEqual(journal["lines"][1]["action"], "keep")
		self.assertEqual(journal["lines"][1]["account"], EXPENSE)
		self.assertEqual(plan["chains"][0]["journals"], ["JE-1"])

	def test_journal_on_another_account_holds_the_invoice(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[],
			[_journal("JE-1", [_line(OTHER_AR, "SI-1")])],
		)
		self.assertEqual(plan["signature"], {"invoices": [], "payments": [], "journals": []})
		self.assertEqual(plan["invoices"][0]["action"], "held")
		self.assertEqual(plan["invoices"][0]["to_account"], OLD_AR)
		self.assertIn(OTHER_AR, plan["journals"][0]["reason"])

	def test_payment_on_another_account_holds_the_invoice(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1")], paid_from=OTHER_AR)],
			[],
		)
		self.assertEqual(plan["invoices"][0]["action"], "held")
		self.assertIn(OTHER_AR, plan["payments"][0]["reason"])

	def test_split_receipt_stays_one_document(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1"), _invoice("SI-2", account=OTHER_AR)],
			[_payment("PE-1", [_reference("SI-1", 50), _reference("SI-2", 50)])],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "multi")
		self.assertEqual(payment["rewrite_party"], 0)
		accounts = {row["reference_name"]: row["account"] for row in payment["references"]}
		self.assertEqual(accounts, {"SI-1": NEW_AR, "SI-2": OTHER_AR})
		self.assertEqual(payment["references"][0]["allocated_amount"], 50)

	def test_taxes_hold_a_split_receipt(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1"), _invoice("SI-2", account=OTHER_AR)],
			[_payment("PE-1", [_reference("SI-1"), _reference("SI-2")], has_taxes=1)],
			[],
		)
		self.assertEqual(plan["signature"], {"invoices": [], "payments": [], "journals": []})
		self.assertTrue(all(row["action"] == "held" for row in plan["invoices"]))

	def test_taxes_on_one_account_still_move(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1")], has_taxes=1)],
			[],
		)
		self.assertEqual(plan["payments"][0]["action"], "move")
		self.assertEqual(plan["payments"][0]["mode"], "single")

	def test_another_document_on_one_account_follows_the_receipt(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1", 80), _reference("JE-9", 20, doctype="Journal Entry")])],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "single")
		other = next(row for row in payment["references"] if row["reference_name"] == "JE-9")
		self.assertEqual(other["account"], NEW_AR)

	def test_cancelled_and_other_accounts_are_left_out(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[
				_invoice("SI-1"),
				_invoice("SI-CANCEL", docstatus=2),
				_invoice("SI-OTHER", account=NEW_AR),
			],
			[],
			[],
		)
		self.assertEqual([row["name"] for row in plan["invoices"]], ["SI-1"])

	def test_two_invoices_are_separate_chains(self):
		plan = plan_reclass(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1"), _invoice("SI-2")],
			[],
			[],
		)
		self.assertEqual(len(plan["chains"]), 2)
		self.assertTrue(selection_matches(plan["signature"], plan))
		self.assertFalse(selection_matches({"invoices": ["SI-1"], "payments": [], "journals": []}, plan))
