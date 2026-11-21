# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.ar_ap_account_logic import (
	ArApAccountError,
	check_accounts,
	plan_accounts,
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
		with self.assertRaises(ArApAccountError):
			side_choice("Bank")

	def test_accounts_must_match_the_side_and_can_change_currency(self):
		same = check_accounts(COMPANY, "receivable", OLD_AR, NEW_AR, _accounts())
		self.assertEqual(same, {"from_currency": "PHP", "to_currency": "PHP"})
		self.assertEqual(
			check_accounts(COMPANY, "payable", OLD_AP, NEW_AP, _accounts())["to_currency"], "PHP"
		)
		changed = check_accounts(COMPANY, "receivable", OLD_AR, USD_AR, _accounts())
		self.assertEqual(changed, {"from_currency": "PHP", "to_currency": "USD"})
		with self.assertRaises(ArApAccountError):
			check_accounts(COMPANY, "receivable", OLD_AR, OLD_AP, _accounts())
		with self.assertRaises(ArApAccountError):
			check_accounts(COMPANY, "receivable", OLD_AR, OLD_AR, _accounts())


class TestReclassPlan(unittest.TestCase):
	def test_receipt_keeps_its_bank_amount_and_allocation(self):
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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

	def test_exchange_journal_keeps_the_gain_line_that_names_the_invoice(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1")])],
			[
				_journal(
					"JE-1",
					[
						_line(OLD_AR, "SI-1", debit=20),
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 0,
							"credit": 20,
						},
					],
					voucher_type="Exchange Gain Or Loss",
				)
			],
		)
		journal = plan["journals"][0]
		payment = plan["payments"][0]
		self.assertEqual(journal["action"], "move")
		self.assertEqual(journal["lines"][0]["account"], NEW_AR)
		self.assertEqual(journal["lines"][1]["action"], "keep")
		self.assertEqual(journal["lines"][1]["account"], EXPENSE)
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["keep_exchange_journal"], 1)
		self.assertEqual(plan["signature"]["journals"], ["JE-1"])
		self.assertEqual(plan["chains"], [{"invoices": ["SI-1"], "payments": ["PE-1"], "journals": ["JE-1"]}])

	def test_exchange_journal_moves_the_line_that_names_the_receipt(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1")],
			[_payment("PE-1", [_reference("SI-1")])],
			[
				_journal(
					"JE-1",
					[
						{
							"row_name": "je-party",
							"account": OLD_AR,
							"reference_type": "Payment Entry",
							"reference_name": "PE-1",
							"debit": 15,
							"credit": 0,
						},
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 0,
							"credit": 15,
						},
					],
					voucher_type="Exchange Gain Or Loss",
				)
			],
		)
		journal = plan["journals"][0]
		party = next(row for row in journal["lines"] if row["row_name"] == "je-party")
		gain = next(row for row in journal["lines"] if row["row_name"] == "je-gain")
		self.assertEqual(journal["action"], "move")
		self.assertEqual(party["action"], "move")
		self.assertEqual(party["account"], NEW_AR)
		self.assertEqual(gain["action"], "keep")
		self.assertEqual(gain["account"], EXPENSE)
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(plan["payments"][0]["keep_exchange_journal"], 1)
		self.assertEqual(plan["chains"][0]["journals"], ["JE-1"])
		self.assertEqual(plan["chains"][0]["payments"], ["PE-1"])

	def test_receipt_on_the_current_account_moves_when_its_invoice_is_already_elsewhere(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1", account=OTHER_AR)],
			[_payment("PE-1", [_reference("SI-1", 80)])],
			[
				_journal(
					"JE-1",
					[
						{
							"row_name": "je-party",
							"account": OLD_AR,
							"reference_type": "Payment Entry",
							"reference_name": "PE-1",
							"debit": 10,
							"credit": 0,
							"debit_in_account_currency": 0,
							"exchange_rate": 0,
						},
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Payment Entry",
							"reference_name": "PE-1",
							"debit": 0,
							"credit": 10,
						},
					],
					voucher_type="Exchange Gain Or Loss",
				)
			],
		)
		self.assertEqual(plan["invoices"], [])
		payment = plan["payments"][0]
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["party_account"], NEW_AR)
		self.assertEqual(payment["references"][0]["account"], NEW_AR)
		self.assertEqual(payment["references"][0]["allocated_amount"], 80)
		journal = plan["journals"][0]
		self.assertEqual(journal["action"], "move")
		self.assertEqual(journal["lines"][0]["account"], NEW_AR)
		self.assertNotIn("restate", journal["lines"][0])
		self.assertEqual(journal["lines"][1]["account"], EXPENSE)
		self.assertEqual(payment["keep_exchange_journal"], 1)
		self.assertEqual(plan["signature"], {"invoices": [], "payments": ["PE-1"], "journals": ["JE-1"]})
		self.assertEqual(plan["chains"], [{"invoices": [], "payments": ["PE-1"], "journals": ["JE-1"]}])

	def test_receipt_on_two_other_accounts_moves_as_one(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1", account=OTHER_AR), _invoice("SI-2", account=USD_AR)],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 40), _reference("SI-2", 40)],
					unallocated_amount=20,
				)
			],
			[],
		)
		self.assertEqual(plan["invoices"], [])
		payment = plan["payments"][0]
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], NEW_AR)
		self.assertEqual(payment["unallocated_amount"], 20)
		accounts = {row["reference_name"]: row["account"] for row in payment["references"]}
		self.assertEqual(accounts, {"SI-1": NEW_AR, "SI-2": NEW_AR})
		self.assertEqual(payment["references"][0]["allocated_amount"], 40)
		self.assertEqual(plan["signature"], {"invoices": [], "payments": ["PE-1"], "journals": []})

	def test_journal_on_another_account_holds_the_invoice(self):
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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

	def test_taxes_keep_a_split_receipt_on_one_account(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			OLD_AR,
			NEW_AR,
			[_invoice("SI-1"), _invoice("SI-2", account=OTHER_AR)],
			[_payment("PE-1", [_reference("SI-1", 50), _reference("SI-2", 50)], has_taxes=1)],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], NEW_AR)
		accounts = {row["reference_name"]: row["account"] for row in payment["references"]}
		self.assertEqual(accounts, {"SI-1": NEW_AR, "SI-2": NEW_AR})
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(plan["signature"]["payments"], ["PE-1"])

	def test_taxes_on_one_account_still_move(self):
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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
		plan = plan_accounts(
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


def _currency_plan(invoices, payments, journals, from_account=OLD_AR, to_account=USD_AR):
	return plan_accounts(
		COMPANY,
		"receivable",
		from_account,
		to_account,
		invoices,
		payments,
		journals,
		company_currency="PHP",
		from_currency="PHP" if from_account == OLD_AR else "USD",
		to_currency="USD" if to_account == USD_AR else "PHP",
	)


class TestCurrencyChange(unittest.TestCase):
	def test_usd_invoice_moves_onto_the_usd_receivable(self):
		plan = _currency_plan(
			[_invoice("SI-1", currency="USD", conversion_rate=56, outstanding_amount=5600)],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 5600)],
					paid_amount=5600,
					received_amount=5600,
					base_paid_amount=5600,
				)
			],
			[],
		)
		invoice = plan["invoices"][0]
		payment = plan["payments"][0]
		reference = payment["references"][0]
		self.assertEqual(invoice["action"], "move")
		self.assertEqual(invoice["to_account"], USD_AR)
		self.assertEqual(invoice["account_currency"], "USD")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["restate"], 1)
		self.assertEqual(payment["party_account"], USD_AR)
		self.assertEqual(payment["party_account_currency"], "USD")
		self.assertEqual(payment["party_amount"], 100)
		self.assertEqual(payment["party_exchange_rate"], 56)
		self.assertEqual(payment["base_party_amount"], 5600)
		self.assertEqual(payment["bank_amount"], 5600)
		self.assertEqual(reference["allocated_amount"], 100)
		self.assertEqual(reference["invoice_amount"], 100)
		self.assertEqual(reference["exchange_rate"], 56)
		self.assertEqual(plan["signature"]["invoices"], ["SI-1"])

	def test_company_currency_invoice_stays_when_the_destination_is_foreign(self):
		plan = _currency_plan([_invoice("SI-PHP", currency="PHP")], [], [])
		invoice = plan["invoices"][0]
		self.assertEqual(invoice["action"], "stay")
		self.assertEqual(invoice["to_account"], OLD_AR)
		self.assertEqual(plan["signature"]["invoices"], [])
		self.assertEqual(plan["counts"]["stay_invoices"], 1)

	def test_third_currency_stays(self):
		plan = _currency_plan([_invoice("SI-EUR", currency="EUR", conversion_rate=60)], [], [])
		self.assertEqual(plan["invoices"][0]["action"], "stay")

	def test_mixed_receipt_keeps_the_company_invoice_and_restates_the_usd_invoice(self):
		plan = _currency_plan(
			[
				_invoice("SI-USD", currency="USD", conversion_rate=56, outstanding_amount=5600),
				_invoice("SI-PHP", currency="PHP", outstanding_amount=500),
			],
			[
				_payment(
					"PE-1",
					[_reference("SI-USD", 5600), _reference("SI-PHP", 500)],
					paid_amount=6100,
					received_amount=6100,
					base_paid_amount=6100,
				)
			],
			[],
		)
		payment = plan["payments"][0]
		usd = next(row for row in payment["references"] if row["reference_name"] == "SI-USD")
		php = next(row for row in payment["references"] if row["reference_name"] == "SI-PHP")
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(next(row["action"] for row in plan["invoices"] if row["name"] == "SI-PHP"), "stay")
		self.assertEqual(payment["mode"], "multi")
		self.assertEqual(payment["restate"], 1)
		self.assertEqual(payment["rewrite_party"], 0)
		self.assertEqual(usd["account"], USD_AR)
		self.assertEqual(usd["allocated_amount"], 100)
		self.assertEqual(php["account"], OLD_AR)
		self.assertEqual(php["allocated_amount"], 500)
		self.assertEqual(payment["bank_amount"], 6100)
		self.assertEqual(plan["signature"]["invoices"], ["SI-USD"])

	def test_unallocated_advance_stays_on_the_old_account_when_the_currency_changes(self):
		plan = _currency_plan(
			[_invoice("SI-1", currency="USD", conversion_rate=56)],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 5600)],
					unallocated_amount=560,
					paid_amount=6160,
					received_amount=6160,
					base_paid_amount=6160,
				)
			],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["mode"], "multi")
		self.assertEqual(payment["advance_account"], OLD_AR)
		self.assertEqual(payment["unallocated_amount"], 560)
		self.assertEqual(payment["references"][0]["allocated_amount"], 100)
		self.assertEqual(payment["bank_amount"], 6160)

	def test_taxes_move_with_the_account_currency(self):
		plan = _currency_plan(
			[_invoice("SI-1", currency="USD", conversion_rate=56)],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 5600)],
					has_taxes=1,
					paid_amount=5600,
					received_amount=5600,
					base_paid_amount=5600,
					base_received_amount=5600,
				)
			],
			[],
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], USD_AR)
		self.assertEqual(payment["party_amount"], 100)
		self.assertEqual(payment["party_exchange_rate"], 56)
		self.assertEqual(payment["bank_amount"], 5600)
		self.assertEqual(plan["invoices"][0]["action"], "move")

	def test_taxed_receipt_with_an_advance_moves_onto_the_company_account(self):
		reference = _reference("SI-1", 100)
		reference["exchange_rate"] = 56
		plan = _currency_plan(
			[
				_invoice(
					"SI-1",
					account=USD_AR,
					currency="USD",
					conversion_rate=56,
					party_account_currency="USD",
					outstanding_amount=10,
				)
			],
			[
				_payment(
					"PE-1",
					[reference],
					paid_from=USD_AR,
					paid_from_account_currency="USD",
					paid_amount=120,
					received_amount=6720,
					base_paid_amount=6720,
					base_received_amount=6720,
					unallocated_amount=20,
					has_deductions=1,
				)
			],
			[
				_journal(
					"JE-1",
					[
						_line(USD_AR, "SI-1", debit=560),
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 0,
							"credit": 560,
						},
					],
					voucher_type="Exchange Gain Or Loss",
				)
			],
			from_account=USD_AR,
			to_account=OLD_AR,
		)
		payment = plan["payments"][0]
		self.assertEqual(payment["action"], "move")
		self.assertEqual(payment["mode"], "single")
		self.assertEqual(payment["party_account"], OLD_AR)
		self.assertEqual(payment["party_amount"], 6720)
		self.assertEqual(payment["unallocated_amount"], 1120)
		self.assertEqual(payment["references"][0]["allocated_amount"], 5600)
		self.assertEqual(payment["bank_amount"], 6720)
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(plan["journals"][0]["action"], "move")
		self.assertEqual(plan["signature"]["invoices"], ["SI-1"])

	def test_usd_invoice_moves_back_to_the_company_receivable(self):
		plan = _currency_plan(
			[
				_invoice(
					"SI-1",
					account=USD_AR,
					currency="USD",
					conversion_rate=56,
					party_account_currency="USD",
					outstanding_amount=100,
				)
			],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 100)],
					paid_from=USD_AR,
					paid_from_account_currency="USD",
					paid_amount=100,
					received_amount=5600,
					base_paid_amount=5600,
					base_received_amount=5600,
				)
			],
			[],
			from_account=USD_AR,
			to_account=OLD_AR,
		)
		payment = plan["payments"][0]
		self.assertEqual(plan["invoices"][0]["account_currency"], "PHP")
		self.assertEqual(payment["party_account"], OLD_AR)
		self.assertEqual(payment["party_account_currency"], "PHP")
		self.assertEqual(payment["party_amount"], 5600)
		self.assertEqual(payment["party_exchange_rate"], 1)
		self.assertEqual(payment["references"][0]["allocated_amount"], 5600)
		self.assertEqual(payment["bank_amount"], 5600)

	def test_exchange_journal_on_the_company_currency_keeps_the_company_amount(self):
		plan = _currency_plan(
			[
				_invoice(
					"SI-1",
					account=USD_AR,
					currency="USD",
					conversion_rate=56,
					party_account_currency="USD",
				)
			],
			[_payment("PE-1", [_reference("SI-1", 100)], paid_from=USD_AR, paid_from_account_currency="USD")],
			[
				_journal(
					"JE-1",
					[
						{
							"row_name": "je-party",
							"account": USD_AR,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 560,
							"credit": 0,
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 0,
							"exchange_rate": 0,
						},
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 0,
							"credit": 560,
						},
					],
					voucher_type="Exchange Gain Or Loss",
				)
			],
			from_account=USD_AR,
			to_account=OLD_AR,
		)
		moved = next(row for row in plan["journals"][0]["lines"] if row["row_name"] == "je-party")
		self.assertEqual(plan["journals"][0]["action"], "move")
		self.assertEqual(plan["journals"][0]["debit_total"], 560)
		self.assertEqual(moved["account"], OLD_AR)
		self.assertEqual(moved["account_currency"], "PHP")
		self.assertEqual(moved["exchange_rate"], 1)
		self.assertEqual(moved["debit_in_account_currency"], 560)
		self.assertEqual(moved["credit_in_account_currency"], 0)
		self.assertEqual(plan["invoices"][0]["action"], "move")
		self.assertEqual(plan["payments"][0]["action"], "move")

	def test_exchange_line_uses_the_invoice_rate_on_the_new_currency(self):
		plan = _currency_plan(
			[_invoice("SI-1", currency="USD", conversion_rate=56)],
			[],
			[
				_journal(
					"JE-1",
					[
						{
							"row_name": "je-party",
							"account": OLD_AR,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 5600,
							"credit": 0,
							"debit_in_account_currency": 5600,
							"credit_in_account_currency": 0,
							"exchange_rate": 1,
						},
						{
							"row_name": "je-gain",
							"account": EXPENSE,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 0,
							"credit": 5600,
						},
					],
					voucher_type="Exchange Rate Revaluation",
				)
			],
		)
		moved = next(row for row in plan["journals"][0]["lines"] if row["row_name"] == "je-party")
		self.assertEqual(plan["journals"][0]["action"], "move")
		self.assertEqual(moved["account"], USD_AR)
		self.assertEqual(moved["account_currency"], "USD")
		self.assertEqual(moved["exchange_rate"], 56)
		self.assertEqual(moved["debit_in_account_currency"], 100)
		self.assertEqual(plan["journals"][0]["debit_total"], 5600)

	def test_exchange_revaluation_between_two_foreign_currencies_stays(self):
		plan = plan_accounts(
			COMPANY,
			"receivable",
			USD_AR,
			"11213 - Trade Receivables EUR - ATN",
			[_invoice("SI-1", account=OLD_AR, currency="USD", conversion_rate=56)],
			[],
			[
				_journal(
					"JE-1",
					[
						{
							"row_name": "je-party",
							"account": USD_AR,
							"reference_type": "Sales Invoice",
							"reference_name": "SI-1",
							"debit": 5600,
							"credit": 0,
							"debit_in_account_currency": 100,
							"credit_in_account_currency": 0,
							"exchange_rate": 56,
						}
					],
					voucher_type="Exchange Rate Revaluation",
				)
			],
			company_currency="PHP",
			from_currency="USD",
			to_currency="EUR",
		)
		self.assertEqual(plan["journals"][0]["action"], "held")
		self.assertEqual(plan["journals"][0]["lines"][0]["account"], USD_AR)
		self.assertEqual(plan["journals"][0]["lines"][0]["action"], "keep")
		self.assertNotIn("account_currency", plan["journals"][0]["lines"][0])
		self.assertEqual(plan["signature"], {"invoices": [], "payments": [], "journals": []})

	def test_receipt_stays_when_its_invoice_is_elsewhere_and_the_currency_would_change(self):
		plan = _currency_plan(
			[_invoice("SI-1", account=OLD_AR, currency="USD", conversion_rate=56)],
			[
				_payment(
					"PE-1",
					[_reference("SI-1", 100)],
					paid_from=USD_AR,
					paid_from_account_currency="USD",
					paid_amount=100,
					received_amount=5600,
				)
			],
			[],
			from_account=USD_AR,
			to_account=OLD_AR,
		)
		self.assertEqual(plan["payments"][0]["action"], "held")
		self.assertIn(USD_AR, plan["payments"][0]["reason"])
		self.assertEqual(plan["signature"], {"invoices": [], "payments": [], "journals": []})

	def test_journal_keeps_the_company_debit_and_restates_the_account_amount(self):
		plan = _currency_plan(
			[_invoice("SI-1", currency="USD", conversion_rate=56)],
			[],
			[
				_journal(
					"JE-1",
					[_line(OLD_AR, "SI-1", debit=5600), _line(EXPENSE, "EXP", debit=0)],
				)
			],
		)
		journal = plan["journals"][0]
		moved = next(row for row in journal["lines"] if row["row_name"] == "je-SI-1")
		self.assertEqual(journal["action"], "move")
		self.assertEqual(journal["debit_total"], 5600)
		self.assertEqual(moved["account"], USD_AR)
		self.assertEqual(moved["account_currency"], "USD")
		self.assertEqual(moved["exchange_rate"], 56)
		self.assertEqual(moved["debit_in_account_currency"], 100)
		self.assertEqual(moved["restate"], 1)
