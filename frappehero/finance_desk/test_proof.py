# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import unittest

from frappehero.finance_desk.proof_logic import (
	MAX_PROOF_BYTES,
	allocation_currency,
	assignee_names,
	is_pending_proof,
	payment_amount,
	payment_detail,
	payment_name_from_scan,
	pending_card,
	proof_file_error,
	proof_stamp,
	reference_rows,
	upload_allowed,
)


def _receipt(**overrides):
	payment = {
		"name": "ACC-PAY-2026-00001",
		"party_type": "Customer",
		"party": "CUST-1",
		"party_name": "North Store",
		"posting_date": "2026-11-01",
		"payment_type": "Receive",
		"mode_of_payment": "Cash",
		"reference_no": "OR-9",
		"reference_date": "2026-11-01",
		"company": "Hero",
		"docstatus": 1,
		"paid_amount": 900,
		"received_amount": 1000,
		"paid_from_account_currency": "USD",
		"paid_to_account_currency": "PHP",
		"hero_proof_of_payment": "",
		"hero_proof_uploaded_by": "",
		"hero_proof_uploaded_on": "",
	}
	payment.update(overrides)
	return payment


class TestPaymentNameFromScan(unittest.TestCase):
	def test_typed_name_keeps_its_hyphens(self):
		self.assertEqual(payment_name_from_scan("  ACC-PAY-2026-00001  "), "ACC-PAY-2026-00001")

	def test_desk_url_uses_the_last_segment(self):
		scanned = "https://erp.example.com/app/payment-entry/ACC-PAY-2026-00001?sid=1"
		self.assertEqual(payment_name_from_scan(scanned), "ACC-PAY-2026-00001")

	def test_the_segment_after_the_route_is_the_name(self):
		self.assertEqual(
			payment_name_from_scan("https://erp.example.com/app/payment-entry/ACC-PAY-2026-00001/edit"),
			"ACC-PAY-2026-00001",
		)
		self.assertEqual(payment_name_from_scan("MY-payment-entry-1"), "MY-payment-entry-1")

	def test_path_with_a_trailing_slash_uses_the_name(self):
		self.assertEqual(
			payment_name_from_scan("/app/payment-entry/ACC-PAY-2026-00001/"),
			"ACC-PAY-2026-00001",
		)

	def test_encoded_name_is_decoded(self):
		self.assertEqual(
			payment_name_from_scan("/app/payment-entry/ACC-PAY-2026-00001%2Fextra"),
			"",
		)
		self.assertEqual(
			payment_name_from_scan("/app/payment-entry/PE%2D1"),
			"PE-1",
		)

	def test_blank_spaces_and_a_long_token_are_rejected(self):
		self.assertEqual(payment_name_from_scan(""), "")
		self.assertEqual(payment_name_from_scan("   "), "")
		self.assertEqual(payment_name_from_scan("not a name"), "")
		self.assertEqual(payment_name_from_scan("A" * 141), "")
		self.assertEqual(payment_name_from_scan("https://erp.example.com/app/payment-entry/"), "")


class TestPaymentAmount(unittest.TestCase):
	def test_receipt_uses_the_received_amount(self):
		self.assertEqual(payment_amount(_receipt()), {"amount": 1000.0, "currency": "PHP"})

	def test_zero_received_amount_stays_zero(self):
		amount = payment_amount(_receipt(received_amount=0))
		self.assertEqual(amount["amount"], 0.0)
		self.assertEqual(amount["currency"], "PHP")

	def test_pay_uses_the_paid_amount(self):
		payment = _receipt(
			payment_type="Pay",
			paid_amount=50,
			received_amount=40,
			paid_from_account_currency="USD",
			paid_to_account_currency="PHP",
		)
		self.assertEqual(payment_amount(payment), {"amount": 50.0, "currency": "USD"})

	def test_internal_transfer_uses_the_paid_amount(self):
		payment = _receipt(
			payment_type="Internal Transfer",
			paid_amount=20,
			paid_from_account_currency="EUR",
			paid_to_account_currency="EUR",
		)
		self.assertEqual(payment_amount(payment), {"amount": 20.0, "currency": "EUR"})

	def test_missing_payment_is_zero(self):
		self.assertEqual(payment_amount(None), {"amount": 0.0, "currency": ""})

	def test_allocation_currency_follows_the_party_account(self):
		self.assertEqual(allocation_currency(_receipt()), "USD")
		self.assertEqual(allocation_currency(_receipt(payment_type="Pay")), "PHP")


class TestReferenceRows(unittest.TestCase):
	def test_invoice_currency_is_kept_when_present(self):
		rows = reference_rows(
			[
				{
					"reference_doctype": " Sales Invoice ",
					"reference_name": "SINV-1",
					"allocated_amount": "1000.5",
					"hero_invoice_currency": "USD",
					"hero_invoice_amount": 18.5,
				}
			]
		)
		self.assertEqual(
			rows,
			[
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": "SINV-1",
					"allocated_amount": 1000.5,
					"invoice_currency": "USD",
					"invoice_amount": 18.5,
				}
			],
		)

	def test_missing_invoice_currency_is_blank(self):
		rows = reference_rows(
			[
				{"reference_doctype": "Journal Entry", "reference_name": "JV-1", "allocated_amount": 10},
				None,
				"not a row",
			]
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["invoice_currency"], "")
		self.assertEqual(rows[0]["invoice_amount"], 0.0)
		self.assertEqual(reference_rows(None), [])


class TestPendingAndUpload(unittest.TestCase):
	def test_assignees_accept_a_list_or_json(self):
		self.assertEqual(assignee_names([" ada@example.com ", ""]), ["ada@example.com"])
		self.assertEqual(assignee_names('["ada@example.com"]'), ["ada@example.com"])
		self.assertEqual(assignee_names("ada@example.com"), ["ada@example.com"])
		self.assertEqual(assignee_names("["), [])
		self.assertEqual(assignee_names(None), [])

	def test_pending_is_an_open_assignment_without_a_file(self):
		assignees = ["ada@example.com"]
		self.assertTrue(is_pending_proof(1, "", assignees, "ada@example.com"))
		self.assertTrue(is_pending_proof(0, "  ", assignees, "ada@example.com"))
		self.assertTrue(is_pending_proof("1", None, '["ada@example.com"]', "ada@example.com"))

	def test_pending_skips_a_file_a_cancellation_and_someone_else(self):
		assignees = ["ada@example.com"]
		self.assertFalse(is_pending_proof(1, "/private/files/slip.jpg", assignees, "ada@example.com"))
		self.assertFalse(is_pending_proof(2, "", assignees, "ada@example.com"))
		self.assertFalse(is_pending_proof(1, "", assignees, "bo@example.com"))
		self.assertFalse(is_pending_proof(1, "", assignees, ""))

	def test_upload_allows_the_assignee_or_a_manager(self):
		assignees = ["ada@example.com"]
		self.assertTrue(upload_allowed(0, assignees, "ada@example.com", False))
		self.assertTrue(upload_allowed(1, assignees, "ada@example.com", False))
		self.assertTrue(upload_allowed(1, [], "maya@example.com", True))
		self.assertFalse(upload_allowed(1, assignees, "bo@example.com", False))

	def test_a_cancelled_payment_cannot_take_a_file(self):
		self.assertFalse(upload_allowed(2, ["ada@example.com"], "ada@example.com", True))


class TestProofFile(unittest.TestCase):
	def test_photo_and_pdf_names_are_accepted(self):
		self.assertEqual(proof_file_error("slip.JPG", 12), "")
		self.assertEqual(proof_file_error("slip.jpeg", 12), "")
		self.assertEqual(proof_file_error("slip.png", 12), "")
		self.assertEqual(proof_file_error("slip.webp", 12), "")
		self.assertEqual(proof_file_error(r"C:\fakepath\slip.pdf", MAX_PROOF_BYTES), "")

	def test_a_bad_name_or_size_is_rejected(self):
		self.assertEqual(proof_file_error("", 12), "Choose a file.")
		self.assertEqual(proof_file_error("slip.gif", 12), "Use a JPEG, PNG, WebP, or PDF.")
		self.assertEqual(proof_file_error("slip", 12), "Use a JPEG, PNG, WebP, or PDF.")
		self.assertEqual(proof_file_error("slip.pdf", 0), "That file is empty.")
		self.assertEqual(proof_file_error("slip.pdf", -1), "That file is empty.")
		self.assertEqual(proof_file_error("slip.pdf", "nope"), "That file is empty.")
		self.assertEqual(
			proof_file_error("slip.pdf", MAX_PROOF_BYTES + 1),
			"The file must be 10 MB or smaller.",
		)


class TestProofStamp(unittest.TestCase):
	def test_a_new_file_stamps_the_current_user(self):
		self.assertEqual(
			proof_stamp("", "/private/files/slip.jpg", "", None, " ada@example.com ", "2026-11-12 09:00:00"),
			{
				"hero_proof_uploaded_by": "ada@example.com",
				"hero_proof_uploaded_on": "2026-11-12 09:00:00",
			},
		)

	def test_a_replaced_file_takes_a_new_stamp(self):
		stamp = proof_stamp(
			"/private/files/old.jpg",
			"/private/files/new.jpg",
			"ada@example.com",
			"2026-11-01 09:00:00",
			"bo@example.com",
			"2026-11-12 09:00:00",
		)
		self.assertEqual(stamp["hero_proof_uploaded_by"], "bo@example.com")
		self.assertEqual(stamp["hero_proof_uploaded_on"], "2026-11-12 09:00:00")

	def test_an_unchanged_file_keeps_its_stamp(self):
		self.assertEqual(
			proof_stamp(
				"/private/files/slip.jpg",
				"/private/files/slip.jpg",
				"ada@example.com",
				"2026-11-01 09:00:00",
				"bo@example.com",
				"2026-11-12 09:00:00",
			),
			{
				"hero_proof_uploaded_by": "ada@example.com",
				"hero_proof_uploaded_on": "2026-11-01 09:00:00",
			},
		)

	def test_removing_the_file_clears_the_stamp(self):
		self.assertEqual(
			proof_stamp("/private/files/slip.jpg", "  ", "ada@example.com", "2026-11-01 09:00:00", "bo@example.com", "now"),
			{"hero_proof_uploaded_by": "", "hero_proof_uploaded_on": None},
		)


class TestPaymentDetail(unittest.TestCase):
	def test_detail_carries_the_amount_and_references(self):
		detail = payment_detail(
			_receipt(),
			[
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": "SINV-1",
					"allocated_amount": 1000,
					"hero_invoice_currency": "USD",
					"hero_invoice_amount": 18,
				}
			],
			["ada@example.com"],
			"ada@example.com",
		)
		self.assertEqual(detail["name"], "ACC-PAY-2026-00001")
		self.assertEqual(detail["party_name"], "North Store")
		self.assertEqual(detail["amount"], 1000.0)
		self.assertEqual(detail["currency"], "PHP")
		self.assertEqual(detail["allocated_currency"], "USD")
		self.assertTrue(detail["pending"])
		self.assertEqual(detail["references"][0]["reference_name"], "SINV-1")
		self.assertEqual(detail["references"][0]["invoice_amount"], 18.0)

	def test_a_file_removes_the_payment_from_the_pending_list(self):
		detail = payment_detail(
			_receipt(hero_proof_of_payment="/private/files/slip.jpg"),
			[],
			["ada@example.com"],
			"ada@example.com",
		)
		self.assertFalse(detail["pending"])
		self.assertEqual(detail["proof_of_payment"], "/private/files/slip.jpg")

	def test_pending_card_prefers_the_party_name(self):
		self.assertEqual(
			pending_card(_receipt(party_name="", party="CUST-1")),
			{
				"name": "ACC-PAY-2026-00001",
				"party": "CUST-1",
				"posting_date": "2026-11-01",
				"amount": 1000.0,
				"currency": "PHP",
			},
		)
