# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Rules for the proof-of-payment page.

Pure functions. The desk and Payment Entry call these, and the tests run
without a site.
"""

import json
from urllib.parse import unquote

from frappehero.flags import clean_text

# Ten mebibytes. A phone photo of a slip fits. A larger file is rejected
# before it is stored.
MAX_PROOF_BYTES = 10 * 1024 * 1024

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

# A Payment Entry name is one token. Anything longer is not a name this page
# will look up.
_MAX_NAME_LENGTH = 140


def payment_name_from_scan(text) -> str:
	"""Payment Entry name from a scan, a typed id, or a desk URL.

	Surrounding whitespace is ignored. A URL or path contributes its last
	segment, so a code that contains ``/app/payment-entry/ACC-PAY-2026-00001``
	still yields the name. A blank value, a value with spaces, or a value that
	is too long yields an empty string.
	"""
	raw = str(text or "").strip()
	if not raw:
		return ""
	candidate = raw
	lowered = raw.lower()
	if "://" in raw or raw.startswith("/") or "payment-entry" in lowered:
		candidate = _name_from_path(raw)
	candidate = unquote(candidate).strip()
	if not _looks_like_name(candidate):
		return ""
	return candidate


def payment_amount(payment) -> dict:
	"""The money that moved, and the currency it is counted in.

	A receipt uses the received amount in the bank currency. A payment and an
	internal transfer use the paid amount in the account the money left.
	"""
	if not payment or not hasattr(payment, "get"):
		return {"amount": 0.0, "currency": ""}
	if clean_text(payment.get("payment_type")) == "Receive":
		return {
			"amount": _number(payment.get("received_amount")),
			"currency": clean_text(payment.get("paid_to_account_currency")),
		}
	return {
		"amount": _number(payment.get("paid_amount")),
		"currency": clean_text(payment.get("paid_from_account_currency")),
	}


def allocation_currency(payment) -> str:
	"""Currency of the allocated amounts on the reference rows.

	On a receipt the party account is the account paid from. On a payment it
	is the account paid to.
	"""
	if not payment or not hasattr(payment, "get"):
		return ""
	if clean_text(payment.get("payment_type")) == "Receive":
		return clean_text(payment.get("paid_from_account_currency"))
	return clean_text(payment.get("paid_to_account_currency"))


def reference_rows(references) -> list:
	"""Display rows for the invoices and other documents this payment clears.

	Invoice currency is included when the payment stored one. A row that is
	not a mapping is skipped.
	"""
	rows = []
	for reference in references or []:
		if not hasattr(reference, "get"):
			continue
		currency = clean_text(reference.get("hero_invoice_currency"))
		rows.append(
			{
				"reference_doctype": clean_text(reference.get("reference_doctype")),
				"reference_name": clean_text(reference.get("reference_name")),
				"allocated_amount": _number(reference.get("allocated_amount")),
				"invoice_currency": currency,
				"invoice_amount": _number(reference.get("hero_invoice_amount")) if currency else 0.0,
			}
		)
	return rows


def assignee_names(value) -> list:
	"""User names from a list or from the JSON stored on an assignment."""
	if value is None or value == "":
		return []
	if isinstance(value, str):
		text = value.strip()
		if text.startswith("["):
			try:
				value = json.loads(text)
			except json.JSONDecodeError:
				return []
		else:
			name = clean_text(text)
			return [name] if name else []
	if isinstance(value, (list, tuple, set)):
		return [name for name in (clean_text(item) for item in value) if name]
	return []


def is_pending_proof(docstatus, proof, assignees, user) -> bool:
	"""True when this payment belongs on the user's pending list.

	The list is open work: not cancelled, no proof file yet, and assigned to
	this user. A manager does not see every payment here.
	"""
	if _status(docstatus) == 2:
		return False
	if clean_text(proof):
		return False
	user = clean_text(user)
	if not user:
		return False
	return user in assignee_names(assignees)


def upload_allowed(docstatus, assignees, user, is_manager) -> bool:
	"""True when this person may attach a proof file.

	A cancelled payment never takes a file. An open assignee may upload, and
	so may an Accounts Manager or a System Manager who is helping. A second
	file is allowed: the field is replaced.
	"""
	if _status(docstatus) == 2:
		return False
	if is_manager:
		return True
	user = clean_text(user)
	return bool(user) and user in assignee_names(assignees)


def clean_proof_filename(filename) -> str:
	"""Last path segment of a chosen file, without a directory."""
	name = str(filename or "").replace("\\", "/").split("/")[-1].strip()
	if name in {".", ".."}:
		return ""
	return name


def proof_file_error(filename, size) -> str:
	"""Why this file cannot be stored, or an empty string when it can.

	JPEG, PNG, WebP, and PDF are accepted. The size is the decoded file, not
	the base64 text.
	"""
	name = clean_proof_filename(filename)
	if not name:
		return "Choose a file."
	extension = ""
	if "." in name:
		extension = "." + name.rsplit(".", 1)[-1].lower()
	if extension not in _ALLOWED_EXTENSIONS:
		return "Use a JPEG, PNG, WebP, or PDF."
	try:
		nbytes = int(size)
	except (TypeError, ValueError):
		return "That file is empty."
	if nbytes <= 0:
		return "That file is empty."
	if nbytes > MAX_PROOF_BYTES:
		return "The file must be 10 MB or smaller."
	return ""


def proof_stamp(previous_url, new_url, previous_by, previous_on, user, now) -> dict:
	"""Uploader and time for the proof field.

	A new file and a replaced file take the current user and time. Removing
	the file clears both. An unchanged file keeps the stamp it already has.
	"""
	previous = clean_text(previous_url)
	current = clean_text(new_url)
	if not current:
		return {"hero_proof_uploaded_by": "", "hero_proof_uploaded_on": None}
	if current != previous:
		return {
			"hero_proof_uploaded_by": clean_text(user),
			"hero_proof_uploaded_on": now,
		}
	return {
		"hero_proof_uploaded_by": clean_text(previous_by),
		"hero_proof_uploaded_on": previous_on,
	}


def payment_detail(payment, references, assignees, user) -> dict:
	"""The card the page shows after a scan or a tap on the pending list."""
	amount = payment_amount(payment)
	proof = clean_text((payment or {}).get("hero_proof_of_payment") if hasattr(payment, "get") else "")
	docstatus = _status((payment or {}).get("docstatus") if hasattr(payment, "get") else 0)
	party_name = ""
	if hasattr(payment, "get"):
		party_name = clean_text(payment.get("party_name")) or clean_text(payment.get("party"))
	return {
		"name": clean_text(payment.get("name")) if hasattr(payment, "get") else "",
		"party_type": clean_text(payment.get("party_type")) if hasattr(payment, "get") else "",
		"party": clean_text(payment.get("party")) if hasattr(payment, "get") else "",
		"party_name": party_name,
		"posting_date": (payment.get("posting_date") or "") if hasattr(payment, "get") else "",
		"payment_type": clean_text(payment.get("payment_type")) if hasattr(payment, "get") else "",
		"mode_of_payment": clean_text(payment.get("mode_of_payment")) if hasattr(payment, "get") else "",
		"reference_no": clean_text(payment.get("reference_no")) if hasattr(payment, "get") else "",
		"reference_date": (payment.get("reference_date") or "") if hasattr(payment, "get") else "",
		"company": clean_text(payment.get("company")) if hasattr(payment, "get") else "",
		"docstatus": docstatus,
		"amount": amount["amount"],
		"currency": amount["currency"],
		"allocated_currency": allocation_currency(payment),
		"proof_of_payment": proof,
		"proof_uploaded_by": clean_text(payment.get("hero_proof_uploaded_by")) if hasattr(payment, "get") else "",
		"proof_uploaded_on": (payment.get("hero_proof_uploaded_on") or "") if hasattr(payment, "get") else "",
		"pending": is_pending_proof(docstatus, proof, assignees, user),
		"references": reference_rows(references),
	}


def pending_card(payment) -> dict:
	"""One row of the pending list."""
	amount = payment_amount(payment)
	party = ""
	if hasattr(payment, "get"):
		party = clean_text(payment.get("party_name")) or clean_text(payment.get("party"))
	return {
		"name": clean_text(payment.get("name")) if hasattr(payment, "get") else "",
		"party": party,
		"posting_date": (payment.get("posting_date") or "") if hasattr(payment, "get") else "",
		"amount": amount["amount"],
		"currency": amount["currency"],
	}


def _name_from_path(raw) -> str:
	"""Document name from a URL or path.

	``/app/payment-entry/ACC-PAY-2026-00001`` uses the segment after the route.
	A route with nothing after it is blank. Any other URL uses its last segment.
	"""
	path = str(raw or "").split("?", 1)[0].split("#", 1)[0]
	parts = [unquote(part) for part in path.split("/") if part]
	for index, part in enumerate(parts):
		if part.lower() == "payment-entry":
			if index + 1 >= len(parts):
				return ""
			return parts[index + 1]
	if not parts:
		return ""
	return parts[-1]


def _looks_like_name(name) -> bool:
	if not name or len(name) > _MAX_NAME_LENGTH:
		return False
	if any(character.isspace() for character in name):
		return False
	if "/" in name or "\\" in name:
		return False
	return True


def _status(docstatus) -> int:
	try:
		return int(docstatus or 0)
	except (TypeError, ValueError):
		return 0


def _number(value) -> float:
	if value is None or value is False or value == "":
		return 0.0
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0
