# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Cheque number sets and the Pay assignment rules.

Pure functions. The desk and Payment Entry call these, and the tests run
without a site.
"""

import re

from frappehero.flags import as_flag, clean_text

MAX_SPAN = 500
LEAF_STATUSES = ("Draft", "Active", "Closed")
NUMBER_STATUSES = ("Available", "Assigned", "Used", "Cancelled")
HELD_STATUSES = ("Assigned", "Used")
_CHEQUE_MODE = re.compile(r"\b(cheque|check)s?\b", re.IGNORECASE)


class ChequeError(ValueError):
	"""A cheque set or assignment breaks a rule."""


def mode_uses_cheque_leaf(mode_name, flagged=0) -> bool:
	"""True when Pay entries with this mode draw a number from a Cheque Leaf.

	The mode name counts when it says cheque or check. A tick on the mode
	covers every other name a company uses for the same instrument.
	"""
	if as_flag(flagged):
		return True
	return bool(_CHEQUE_MODE.search(clean_text(mode_name)))


def generate_range(prefix, start, end, padding) -> list[str]:
	"""Build the inclusive number set. A blank range returns an empty list."""
	prefix = clean_text(prefix)
	start_blank = _blank_bound(start)
	end_blank = _blank_bound(end)
	if start_blank and end_blank:
		return []
	if start_blank or end_blank:
		raise ChequeError("Set both the first and last cheque number, or leave the range blank.")
	try:
		start_n = int(start)
		end_n = int(end)
		pad = int(padding or 0)
	except (TypeError, ValueError) as exc:
		raise ChequeError("The first and last cheque numbers are whole numbers.") from exc
	if start_n < 1 or end_n < 1:
		raise ChequeError("Cheque numbers start at 1.")
	if end_n < start_n:
		raise ChequeError("The last cheque number is lower than the first.")
	span = end_n - start_n + 1
	if span > MAX_SPAN:
		raise ChequeError(f"A Cheque Leaf holds up to {MAX_SPAN} numbers. Split the book.")
	if pad < 0 or pad > 12:
		raise ChequeError("Padding is a whole number from 0 to 12.")
	numbers = []
	for number in range(start_n, end_n + 1):
		body = str(number).zfill(pad) if pad else str(number)
		numbers.append(f"{prefix}{body}")
	return numbers


def parse_extra_numbers(text) -> list[str]:
	"""One cheque number per line. Blank lines and repeats are skipped."""
	found = []
	seen = set()
	for line in str(text or "").splitlines():
		number = clean_text(line)
		if not number or number in seen:
			continue
		seen.add(number)
		found.append(number)
	return found


def compose_numbers(existing, range_numbers, extra_numbers, replace_available=0) -> list[dict]:
	"""Return the configured set.

	The range and the pasted lines are added to the rows already on the leaf.
	Assigned, used, and cancelled rows stay. Replacing available numbers drops
	the available rows and rebuilds those from the range and the pasted lines.
	"""
	current = [_copy_row(row) for row in existing or [] if clean_text(row.get("cheque_number"))]
	wanted = []
	seen = set()
	for number in list(range_numbers or []) + list(extra_numbers or []):
		number = clean_text(number)
		if not number or number in seen:
			continue
		seen.add(number)
		wanted.append(number)
	if as_flag(replace_available):
		kept = [row for row in current if row["status"] in ("Assigned", "Used", "Cancelled")]
		kept_numbers = {row["cheque_number"] for row in kept}
		for number in wanted:
			if number in kept_numbers:
				continue
			kept.append(_available_row(number))
			kept_numbers.add(number)
		return kept
	have = {row["cheque_number"] for row in current}
	for number in wanted:
		if number in have:
			continue
		current.append(_available_row(number))
		have.add(number)
	return current


def validate_leaf_shape(leaf, numbers) -> list[str]:
	"""Structural problems with one leaf and its number set."""
	errors = []
	status = clean_text(leaf.get("status"))
	if status not in LEAF_STATUSES:
		errors.append("Status is Draft, Active, or Closed.")
	if not clean_text(leaf.get("bank_account")):
		errors.append("Bank Account is required.")
	if status == "Active" and not numbers:
		errors.append("An active Cheque Leaf needs at least one cheque number.")
	seen = set()
	for row in numbers or []:
		number = clean_text(row.get("cheque_number"))
		if not number:
			errors.append("Each cheque number is required.")
			continue
		if number in seen:
			errors.append(f"{number} is listed twice on this Cheque Leaf.")
		seen.add(number)
		if clean_text(row.get("status")) not in NUMBER_STATUSES:
			errors.append(f"{number} has a status this leaf does not use.")
	return errors


def validate_number_changes(previous, current) -> list[str]:
	"""Reject edits that rewrite a cheque already handed to a payment."""
	prev_list = [_copy_row(row) for row in previous or []]
	curr_list = [_copy_row(row) for row in current or []]
	errors = []
	seen = set()
	for row in curr_list:
		if not row["cheque_number"]:
			errors.append("Each cheque number is required.")
			continue
		if row["cheque_number"] in seen:
			errors.append(f"{row['cheque_number']} is listed twice on this Cheque Leaf.")
		seen.add(row["cheque_number"])
		if row["status"] not in NUMBER_STATUSES:
			errors.append(f"{row['cheque_number']} has a status this leaf does not use.")
	prev_by_name = {row["name"]: row for row in prev_list if row["name"]}
	matched = set()
	for row in curr_list:
		prev = prev_by_name.get(row["name"]) if row["name"] else None
		if prev is None:
			prev = _unmatched_by_number(prev_list, matched, row["cheque_number"])
		if prev is None:
			errors.extend(_new_row_errors(row))
			continue
		matched.add(id(prev))
		errors.extend(_change_errors(prev, row))
	for prev in prev_list:
		if id(prev) in matched:
			continue
		if prev["status"] in HELD_STATUSES:
			errors.append(f"Cheque {prev['cheque_number']} stays on the leaf while it is {prev['status'].lower()}.")
	return _unique(errors)


def conflicting_numbers(numbers, other_leaves) -> list[dict]:
	"""Numbers that already belong to another leaf of the same bank account."""
	wanted = []
	seen = set()
	for number in numbers or []:
		cleaned = clean_text(number)
		if cleaned and cleaned not in seen:
			seen.add(cleaned)
			wanted.append(cleaned)
	found = []
	for leaf in other_leaves or []:
		theirs = {clean_text(number) for number in leaf.get("numbers") or []}
		for number in wanted:
			if number in theirs:
				found.append({"cheque_number": number, "leaf": leaf.get("name") or ""})
	return found


def summarize_numbers(rows) -> dict:
	"""Count the set and say whether any cheque is still free."""
	counts = {status: 0 for status in NUMBER_STATUSES}
	for row in rows or []:
		status = clean_text(row.get("status"))
		if status in counts:
			counts[status] += 1
	total = sum(counts.values())
	if total == 0:
		usage = "empty"
	elif counts["Available"] == 0:
		usage = "exhausted"
	else:
		usage = "open"
	return {
		"available": counts["Available"],
		"assigned": counts["Assigned"],
		"used": counts["Used"],
		"cancelled": counts["Cancelled"],
		"total": total,
		"usage": usage,
	}


def summarize_book(leaves) -> dict:
	"""Totals across the leaves currently on screen."""
	keys = ("available", "assigned", "used", "cancelled")
	totals = {key: 0 for key in keys}
	for leaf in leaves or []:
		for key in keys:
			totals[key] += int(leaf.get(key) or 0)
	totals["leaves"] = len(leaves or [])
	return totals


def filter_leaves(leaves, company="", bank_account="", status="", usage="", text="") -> list[dict]:
	"""Filter an already summarized leaf list."""
	company = clean_text(company)
	bank_account = clean_text(bank_account)
	status = clean_text(status)
	usage = clean_text(usage).casefold()
	query = " ".join(str(text or "").casefold().split())
	matched = []
	for leaf in leaves or []:
		if company and clean_text(leaf.get("company")) != company:
			continue
		if bank_account and clean_text(leaf.get("bank_account")) != bank_account:
			continue
		if status and status.casefold() != "all" and clean_text(leaf.get("status")) != status:
			continue
		if usage and usage != "all" and clean_text(leaf.get("usage")).casefold() != usage:
			continue
		if query:
			haystack = " ".join(
				[
					str(leaf.get("name") or ""),
					str(leaf.get("bank_account") or ""),
					str(leaf.get("company") or ""),
					str(leaf.get("bank") or ""),
				]
			).casefold()
			if query not in haystack:
				continue
		matched.append(leaf)
	return matched


def preview_cheque(
	leaves,
	numbers_by_leaf,
	bank_account,
	company="",
	selected="",
	mode_uses_cheque=False,
) -> dict:
	"""The leaf and next free number a Pay form can offer. Nothing is reserved."""
	leaf_name, error = resolve_leaf(
		leaves,
		bank_account=bank_account,
		company=company,
		selected=selected,
		mode_uses_cheque=mode_uses_cheque,
		previous_leaf="",
	)
	rows = (numbers_by_leaf or {}).get(leaf_name) or []
	available = [row["cheque_number"] for row in rows if clean_text(row.get("status")) == "Available"]
	if leaf_name and not available and not error:
		error = "This Cheque Leaf has no available cheque numbers."
	return {
		"leaf": leaf_name,
		"cheque_number": available[0] if available and not error else "",
		"available": available,
		"error": error,
		"uses_cheque": bool(mode_uses_cheque),
	}


def plan_payment_cheque(
	*,
	action,
	payment_type,
	bank_account,
	company="",
	mode_uses_cheque=False,
	selected_leaf="",
	requested_number="",
	payment_name="",
	previous_leaf="",
	previous_number="",
	reference_no="",
	docstatus=0,
	leaves=None,
	numbers_by_leaf=None,
) -> dict:
	"""Decide which cheque a Payment Entry holds, and which rows change.

	``save`` reserves the number (Assigned). ``submit`` marks it Used.
	``cancel`` voids a used cheque. ``trash`` returns a draft reservation
	to the set. Updates are applied only when ``error`` is empty.
	"""
	action = clean_text(action).casefold()
	payment_type = clean_text(payment_type)
	payment_name = clean_text(payment_name)
	previous_leaf = clean_text(previous_leaf)
	previous_number = clean_text(previous_number)
	leaves = list(leaves or [])
	numbers_by_leaf = numbers_by_leaf or {}
	if action not in ("save", "submit", "cancel", "trash"):
		return _result(error="Cheque assignment supports save, submit, cancel, and trash.")
	if action == "save" and int(docstatus or 0) >= 1:
		return _result(leaf=previous_leaf, cheque_number=previous_number, state="Used")
	if action in ("cancel", "trash"):
		return _finish_payment(
			action,
			payment_name,
			previous_leaf,
			previous_number,
			numbers_by_leaf,
		)
	if payment_type != "Pay":
		updates, cleared = _release_held(previous_leaf, previous_number, payment_name, numbers_by_leaf)
		return _result(
			updates=updates,
			clear_reference_no=cleared and clean_text(reference_no) == previous_number,
		)
	if not clean_text(bank_account) and (clean_text(selected_leaf) or mode_uses_cheque):
		return _result(error="Set the company bank account before assigning a cheque number.")
	if not clean_text(bank_account):
		updates, cleared = _release_held(previous_leaf, previous_number, payment_name, numbers_by_leaf)
		return _result(
			updates=updates,
			clear_reference_no=cleared and clean_text(reference_no) == previous_number,
		)
	leaf_name, error = resolve_leaf(
		leaves,
		bank_account=bank_account,
		company=company,
		selected=selected_leaf,
		mode_uses_cheque=mode_uses_cheque,
		previous_leaf=previous_leaf,
	)
	if error:
		return _result(error=error)
	if not leaf_name:
		updates, cleared = _release_held(previous_leaf, previous_number, payment_name, numbers_by_leaf)
		return _result(
			updates=updates,
			clear_reference_no=cleared and clean_text(reference_no) == previous_number,
		)
	if not payment_name:
		return _result(error="Save the payment before assigning a cheque number.")
	target = "Used" if action == "submit" else "Assigned"
	rows = list(numbers_by_leaf.get(leaf_name) or [])
	requested = clean_text(requested_number)
	held_here = previous_number if previous_leaf == leaf_name else ""
	chosen = requested or held_here or _next_available(rows)
	if not chosen:
		return _result(error="This Cheque Leaf has no available cheque numbers.")
	updates = {}
	if previous_leaf and previous_number and (previous_leaf != leaf_name or previous_number != chosen):
		released, _cleared = _release_held(previous_leaf, previous_number, payment_name, numbers_by_leaf)
		updates.update(released)
		if previous_leaf == leaf_name:
			rows = _apply_local(rows, released.get(leaf_name) or [])
	change, take_error = _take_update(rows, chosen, payment_name, target)
	if take_error:
		return _result(error=take_error)
	if change:
		updates.setdefault(leaf_name, []).append(change)
	return _result(
		leaf=leaf_name,
		cheque_number=chosen,
		state=target,
		set_reference_no=True,
		updates=updates,
	)


def resolve_leaf(
	leaves,
	bank_account,
	company="",
	selected="",
	mode_uses_cheque=False,
	previous_leaf="",
) -> tuple[str, str | None]:
	"""Pick the active leaf for this bank account, or explain why none fits."""
	selected = clean_text(selected)
	bank_account = clean_text(bank_account)
	company = clean_text(company)
	previous_leaf = clean_text(previous_leaf)
	known = list(leaves or [])
	bank_leaves = [
		leaf
		for leaf in known
		if clean_text(leaf.get("bank_account")) == bank_account and _same_company(leaf, company)
	]
	if selected:
		match = next((leaf for leaf in known if clean_text(leaf.get("name")) == selected), None)
		if match is None:
			return "", f"Cheque Leaf {selected} does not exist."
		owner = clean_text(match.get("bank_account"))
		if owner != bank_account:
			return "", f"Cheque Leaf {selected} belongs to bank account {owner}."
		if clean_text(match.get("status")) != "Active":
			return "", f"Cheque Leaf {selected} is {clean_text(match.get('status'))}. Choose an active leaf."
		leaf_company = clean_text(match.get("company"))
		if company and leaf_company and leaf_company != company:
			return "", f"Cheque Leaf {selected} belongs to company {leaf_company}."
		return selected, None
	if not mode_uses_cheque:
		return "", None
	if previous_leaf:
		previous = next(
			(
				leaf
				for leaf in bank_leaves
				if clean_text(leaf.get("name")) == previous_leaf and clean_text(leaf.get("status")) == "Active"
			),
			None,
		)
		if previous is not None:
			return previous_leaf, None
	active = [leaf for leaf in bank_leaves if clean_text(leaf.get("status")) == "Active"]
	defaults = [leaf for leaf in active if as_flag(leaf.get("is_default"))]
	if len(defaults) == 1:
		return clean_text(defaults[0].get("name")), None
	if len(active) == 1:
		return clean_text(active[0].get("name")), None
	if not active:
		return "", f"Add an active Cheque Leaf for {bank_account} before paying by cheque."
	return "", f"Choose a Cheque Leaf for {bank_account}. More than one active set is available."


def _finish_payment(action, payment_name, previous_leaf, previous_number, numbers_by_leaf) -> dict:
	if not previous_leaf or not previous_number:
		state = "Cancelled" if action == "cancel" else ""
		return _result(state=state)
	rows = list(numbers_by_leaf.get(previous_leaf) or [])
	row = _find_row(rows, previous_number)
	if row is None:
		return _result(leaf=previous_leaf, cheque_number=previous_number, state="Cancelled" if action == "cancel" else "")
	owner = clean_text(row.get("payment_entry"))
	if owner and owner != payment_name:
		if action == "trash":
			return _result()
		return _result(
			error=f"Cheque {previous_number} is already {clean_text(row.get('status')).lower()} on {owner}."
		)
	status = clean_text(row.get("status"))
	if action == "trash" or status == "Assigned":
		if status == "Assigned":
			return _result(
				state="",
				updates={
					previous_leaf: [
						{"cheque_number": previous_number, "status": "Available", "payment_entry": ""},
					]
				},
			)
		return _result(leaf=previous_leaf, cheque_number=previous_number, state=status)
	if status == "Used":
		return _result(
			leaf=previous_leaf,
			cheque_number=previous_number,
			state="Cancelled",
			updates={
				previous_leaf: [
					{"cheque_number": previous_number, "status": "Cancelled", "payment_entry": payment_name},
				]
			},
		)
	return _result(leaf=previous_leaf, cheque_number=previous_number, state=status)


def _release_held(leaf_name, number, payment_name, numbers_by_leaf):
	leaf_name = clean_text(leaf_name)
	number = clean_text(number)
	if not leaf_name or not number:
		return {}, False
	row = _find_row(numbers_by_leaf.get(leaf_name) or [], number)
	if row is None:
		return {}, False
	owner = clean_text(row.get("payment_entry"))
	if owner and owner != payment_name:
		return {}, False
	if clean_text(row.get("status")) != "Assigned":
		return {}, False
	return {leaf_name: [{"cheque_number": number, "status": "Available", "payment_entry": ""}]}, True


def _take_update(rows, number, payment_name, target):
	row = _find_row(rows, number)
	if row is None:
		return None, f"Cheque {number} is not on this Cheque Leaf."
	status = clean_text(row.get("status"))
	owner = clean_text(row.get("payment_entry"))
	if status == "Cancelled":
		return None, f"Cheque {number} is cancelled on this Cheque Leaf."
	if owner and owner != payment_name and status in HELD_STATUSES:
		return None, f"Cheque {number} is already {status.lower()} on {owner}."
	if status == "Used" and owner == payment_name:
		if target == "Used":
			return None, None
		return None, f"Cheque {number} is already used on this payment."
	if status == target and owner == payment_name:
		return None, None
	if status == "Available" or (status == "Assigned" and owner in ("", payment_name)):
		return {"cheque_number": number, "status": target, "payment_entry": payment_name}, None
	return None, f"Cheque {number} is {status.lower()}."


def _next_available(rows):
	for row in rows or []:
		if clean_text(row.get("status")) == "Available":
			return clean_text(row.get("cheque_number"))
	return ""


def _apply_local(rows, changes):
	by_number = {clean_text(row.get("cheque_number")): _copy_row(row) for row in rows}
	for change in changes:
		current = by_number.get(clean_text(change.get("cheque_number")))
		if current is None:
			continue
		current["status"] = change["status"]
		current["payment_entry"] = clean_text(change.get("payment_entry"))
	ordered = []
	seen = set()
	for row in rows:
		number = clean_text(row.get("cheque_number"))
		if not number or number in seen:
			continue
		seen.add(number)
		ordered.append(by_number[number])
	return ordered


def _same_company(leaf, company) -> bool:
	if not company:
		return True
	leaf_company = clean_text(leaf.get("company"))
	return not leaf_company or leaf_company == company


def _find_row(rows, number):
	number = clean_text(number)
	for row in rows or []:
		if clean_text(row.get("cheque_number")) == number:
			return row
	return None


def _result(
	*,
	error=None,
	leaf="",
	cheque_number="",
	state="",
	set_reference_no=False,
	clear_reference_no=False,
	updates=None,
) -> dict:
	return {
		"error": error,
		"leaf": leaf or "",
		"cheque_number": cheque_number or "",
		"state": state or "",
		"set_reference_no": bool(set_reference_no),
		"clear_reference_no": bool(clear_reference_no),
		"updates": updates or {},
	}


def _blank_bound(value) -> bool:
	if value is None or value is False:
		return True
	if isinstance(value, str) and not value.strip():
		return True
	try:
		return int(value) == 0
	except (TypeError, ValueError):
		return False


def _copy_row(row) -> dict:
	status = clean_text(row.get("status")) or "Available"
	return {
		"name": clean_text(row.get("name")),
		"cheque_number": clean_text(row.get("cheque_number")),
		"status": status,
		"payment_entry": clean_text(row.get("payment_entry")),
		"party": clean_text(row.get("party")),
		"posting_date": row.get("posting_date") or None,
		"remarks": row.get("remarks") or "",
	}


def _available_row(number) -> dict:
	return {
		"name": "",
		"cheque_number": number,
		"status": "Available",
		"payment_entry": "",
		"party": "",
		"posting_date": None,
		"remarks": "",
	}


def _new_row_errors(row) -> list[str]:
	if not row["cheque_number"]:
		return []
	errors = []
	if row["status"] not in ("Available", "Cancelled"):
		errors.append(f"{row['cheque_number']} is a new row, so its status is Available or Cancelled.")
	if row["payment_entry"]:
		errors.append(f"{row['cheque_number']} is a new row, so it has no payment entry yet.")
	return errors


def _change_errors(prev, row) -> list[str]:
	errors = []
	if prev["cheque_number"] != row["cheque_number"] and prev["status"] != "Available":
		errors.append(f"Cheque {prev['cheque_number']} is {prev['status'].lower()}, so the number stays {prev['cheque_number']}.")
	pair = (prev["status"], row["status"])
	allowed = {
		("Available", "Available"),
		("Available", "Assigned"),
		("Available", "Used"),
		("Available", "Cancelled"),
		("Assigned", "Assigned"),
		("Assigned", "Used"),
		("Assigned", "Available"),
		("Used", "Used"),
		("Used", "Cancelled"),
		("Cancelled", "Cancelled"),
		("Cancelled", "Available"),
	}
	if pair not in allowed:
		errors.append(f"Cheque {row['cheque_number']} is {prev['status']}. From there it can become {_next_states(prev['status'])}.")
	if row["status"] in HELD_STATUSES and not row["payment_entry"]:
		errors.append(f"Cheque {row['cheque_number']} needs the payment entry that holds it.")
	if row["status"] == "Available" and row["payment_entry"]:
		errors.append(f"Cheque {row['cheque_number']} is available, so the payment entry is blank.")
	if pair == ("Cancelled", "Available") and prev["payment_entry"]:
		errors.append(f"Cheque {row['cheque_number']} was issued, so it stays cancelled.")
	if prev["status"] in HELD_STATUSES and row["status"] in HELD_STATUSES:
		if row["payment_entry"] != prev["payment_entry"]:
			errors.append(f"Cheque {row['cheque_number']} stays on {prev['payment_entry']}.")
	if pair == ("Used", "Cancelled") and row["payment_entry"] != prev["payment_entry"]:
		errors.append(f"Cheque {row['cheque_number']} stays on {prev['payment_entry']}.")
	if pair == ("Cancelled", "Cancelled") and row["payment_entry"] != prev["payment_entry"]:
		errors.append(f"Cheque {row['cheque_number']} stays on {prev['payment_entry'] or 'the leaf'}.")
	return errors


def _next_states(status) -> str:
	return {
		"Available": "Assigned, Used, or Cancelled",
		"Assigned": "Used or Available",
		"Used": "Cancelled",
		"Cancelled": "Available when it was never issued",
	}.get(status, "its current status")


def _unmatched_by_number(prev_list, matched, number):
	if not number:
		return None
	for prev in prev_list:
		if id(prev) in matched:
			continue
		if prev["cheque_number"] == number:
			return prev
	return None


def _unique(messages) -> list[str]:
	found = []
	seen = set()
	for message in messages:
		if message in seen:
			continue
		seen.add(message)
		found.append(message)
	return found
