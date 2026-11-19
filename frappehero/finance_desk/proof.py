# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Upload a proof file onto a Payment Entry from the phone page."""

import base64
import binascii

import frappe
from frappe import _
from frappe.utils.file_manager import save_file

from frappehero.finance_desk.proof_logic import (
	clean_proof_filename,
	payment_detail,
	payment_name_from_scan,
	pending_card,
	proof_file_error,
	proof_stamp,
	upload_allowed,
)
from frappehero.flags import clean_text

_PROOF_ROLES = ("System Manager", "Accounts Manager", "Accounts User")
_MANAGER_ROLES = {"System Manager", "Accounts Manager"}


def stamp_proof(doc, method=None):
	"""Set who uploaded the proof, and when, whenever that file changes.

	The phone page writes the same stamp itself. This covers a file chosen on
	the Payment Entry form. Removing the file clears the stamp.
	"""
	if not _fields_ready():
		return
	previous_url = ""
	previous_by = ""
	previous_on = None
	if not doc.get("__islocal") and doc.name and frappe.db.exists("Payment Entry", doc.name):
		row = frappe.db.get_value(
			"Payment Entry",
			doc.name,
			["hero_proof_of_payment", "hero_proof_uploaded_by", "hero_proof_uploaded_on"],
			as_dict=True,
		)
		if row:
			previous_url = row.hero_proof_of_payment
			previous_by = row.hero_proof_uploaded_by
			previous_on = row.hero_proof_uploaded_on
	stamp = proof_stamp(
		previous_url,
		doc.get("hero_proof_of_payment"),
		previous_by,
		previous_on,
		frappe.session.user,
		frappe.utils.now(),
	)
	doc.hero_proof_uploaded_by = stamp["hero_proof_uploaded_by"]
	doc.hero_proof_uploaded_on = stamp["hero_proof_uploaded_on"]


@frappe.whitelist()
def list_pending() -> list:
	"""Payment Entries assigned to the signed-in user that still need a file."""
	_proof_user()
	_require_fields()
	names = _assigned_names(frappe.session.user)
	if not names:
		return []
	payments = frappe.get_list(
		"Payment Entry",
		filters={"name": ["in", names], "docstatus": ["!=", 2]},
		fields=[
			"name",
			"party",
			"party_name",
			"posting_date",
			"payment_type",
			"paid_amount",
			"received_amount",
			"paid_from_account_currency",
			"paid_to_account_currency",
			"hero_proof_of_payment",
		],
		order_by="posting_date desc, name desc",
		limit_page_length=0,
	)
	cards = []
	for payment in payments:
		if clean_text(payment.hero_proof_of_payment):
			continue
		cards.append(pending_card(payment))
	return cards


@frappe.whitelist()
def get_payment(name: str | None = None) -> dict:
	"""Basic details for one Payment Entry, including amount and references."""
	_proof_user()
	_require_fields()
	name = payment_name_from_scan(name)
	if not name:
		frappe.throw(_("Enter a Payment Entry."))
	if not frappe.db.exists("Payment Entry", name):
		frappe.throw(_("Payment Entry {0} was not found.").format(name))
	if not frappe.has_permission("Payment Entry", ptype="read", doc=name):
		frappe.throw(_("Not permitted to read this payment."), frappe.PermissionError)
	return _detail(name)


@frappe.whitelist()
def attach_proof(name: str | None = None, filename: str | None = None, filedata: str | None = None) -> dict:
	"""Store a proof file on the Payment Entry and return the updated details.

	The file is private. A second upload replaces the field. The previous file
	stays attached to the payment.
	"""
	_proof_user()
	_require_fields()
	name = payment_name_from_scan(name)
	if not name:
		frappe.throw(_("Enter a Payment Entry."))
	content = _decode_file(filedata)
	if content is None:
		frappe.throw(_("That file could not be read."))
	error = proof_file_error(filename, len(content))
	if error:
		frappe.throw(_(error))
	if not frappe.db.exists("Payment Entry", name):
		frappe.throw(_("Payment Entry {0} was not found.").format(name))
	if not frappe.has_permission("Payment Entry", ptype="read", doc=name):
		frappe.throw(_("Not permitted to read this payment."), frappe.PermissionError)
	docstatus = frappe.db.get_value("Payment Entry", name, "docstatus")
	assignees = _open_assignees(name)
	if not frappe.has_permission("Payment Entry", ptype="write", doc=name) or not upload_allowed(
		docstatus, assignees, frappe.session.user, _is_manager()
	):
		if int(docstatus or 0) == 2:
			frappe.throw(_("A cancelled payment cannot take a proof."))
		frappe.throw(_("Not permitted to upload a proof for this payment."), frappe.PermissionError)
	stored = save_file(
		clean_proof_filename(filename),
		content,
		"Payment Entry",
		name,
		decode=False,
		is_private=1,
		df="hero_proof_of_payment",
	)
	previous = frappe.db.get_value(
		"Payment Entry",
		name,
		["hero_proof_of_payment", "hero_proof_uploaded_by", "hero_proof_uploaded_on"],
		as_dict=True,
	)
	stamp = proof_stamp(
		previous.hero_proof_of_payment if previous else "",
		stored.file_url,
		previous.hero_proof_uploaded_by if previous else "",
		previous.hero_proof_uploaded_on if previous else None,
		frappe.session.user,
		frappe.utils.now(),
	)
	# set_value writes the file onto a submitted payment without reopening the
	# voucher. The stamp matches the validate hook used by the form.
	frappe.db.set_value(
		"Payment Entry",
		name,
		{
			"hero_proof_of_payment": stored.file_url,
			"hero_proof_uploaded_by": stamp["hero_proof_uploaded_by"],
			"hero_proof_uploaded_on": stamp["hero_proof_uploaded_on"],
		},
	)
	return _detail(name)


def _detail(name) -> dict:
	doc = frappe.get_doc("Payment Entry", name)
	assignees = _open_assignees(name)
	detail = payment_detail(doc, doc.get("references") or [], assignees, frappe.session.user)
	detail["can_upload"] = bool(
		frappe.has_permission("Payment Entry", ptype="write", doc=doc)
		and upload_allowed(doc.docstatus, assignees, frappe.session.user, _is_manager())
	)
	return detail


def _assigned_names(user) -> list:
	if not frappe.db.table_exists("ToDo"):
		return []
	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "Payment Entry",
			"allocated_to": user,
			"status": "Open",
		},
		pluck="reference_name",
		limit_page_length=0,
	)
	names = []
	seen = set()
	for name in rows:
		name = clean_text(name)
		if not name or name in seen:
			continue
		seen.add(name)
		names.append(name)
	return names


def _open_assignees(name) -> list:
	if not frappe.db.table_exists("ToDo"):
		return []
	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "Payment Entry",
			"reference_name": name,
			"status": "Open",
		},
		pluck="allocated_to",
		limit_page_length=0,
	)
	return [clean_text(user) for user in rows if clean_text(user)]


def _decode_file(filedata):
	if filedata is None:
		return b""
	if isinstance(filedata, bytes):
		text = filedata.strip()
	else:
		text = str(filedata).strip().encode("utf-8")
	if text.lower().startswith(b"data:") and b"," in text:
		text = text.split(b",", 1)[1]
	text = b"".join(text.split())
	if not text:
		return b""
	try:
		return base64.b64decode(text, validate=True)
	except (binascii.Error, ValueError):
		return None


def _fields_ready() -> bool:
	return bool(
		frappe.db.exists("DocType", "Payment Entry")
		and frappe.get_meta("Payment Entry").has_field("hero_proof_of_payment")
	)


def _require_fields():
	if not _fields_ready():
		frappe.throw(_("Proof of Payment is not on Payment Entry yet. Run migrate."))


def _proof_user():
	frappe.only_for(list(_PROOF_ROLES))


def _is_manager() -> bool:
	return bool(set(frappe.get_roles()).intersection(_MANAGER_ROLES))
