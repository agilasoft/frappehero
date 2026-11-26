# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Share a document with the people it is assigned to.

Every DocType uses the same ToDo row for an assignment. Creating that row shares
the document with the assignee: read, write, and share, plus submit when the
DocType can be submitted. Frappe's assign step may afterwards save a read-only
share for someone who could not already open the document. The DocShare hook
puts the assignment rights back before that save is written. A later edit of
the share is left as it is.
"""

import frappe

from frappehero.access_desk.logic import assignment_share, missing_share_rights
from frappehero.flags import as_flag, clean_text


def share_assignment(doc, method=None):
	"""Share the referenced document when an assignment is created."""
	if _skip_request() or frappe.flags.get("hero_assignment_share"):
		return
	if not _sharing_enabled():
		return
	meta = _assignable_meta(doc.get("reference_type"))
	if not meta:
		return
	reference_name = doc.get("reference_name")
	if not reference_name or not frappe.db.exists(meta.name, reference_name):
		return
	rights = assignment_share(
		doc.get("allocated_to"),
		meta.name,
		reference_name,
		doc.get("status"),
		meta.is_submittable,
		sharing_enabled=1,
	)
	if not rights or not frappe.db.exists("User", rights["user"]):
		return
	# Share the document that was assigned. Cleaning is only for the decision
	# above; the stored name is what Frappe will look up afterwards.
	rights["doctype"] = meta.name
	rights["docname"] = reference_name if isinstance(reference_name, str) else str(reference_name)
	_remember(rights)
	current = _current_share(rights)
	if current and not missing_share_rights(current, rights):
		return
	frappe.flags.hero_assignment_share = True
	try:
		_add_share(rights)
	finally:
		frappe.flags.hero_assignment_share = False


def keep_assignment_share(doc, method=None):
	"""Restore assignment rights on a share Frappe is about to save as read-only."""
	if _skip_request() or as_flag(doc.get("everyone")) or not doc.get("user"):
		return
	rights = _remembered(doc.get("share_doctype"), doc.get("share_name"), doc.get("user"))
	if not rights:
		return
	for bit, value in missing_share_rights(doc, rights).items():
		doc.set(bit, value)


def _add_share(rights):
	kwargs = {
		"user": rights["user"],
		"read": 1,
		"write": rights["write"],
		"submit": rights["submit"],
		"share": rights["share"],
		"everyone": 0,
		"flags": {"ignore_share_permission": True},
		"notify": 0,
	}
	# Recent Frappe exposes add_docshare. Older v15 accepts the same arguments
	# on frappe.share.add, including the permission flag.
	add = getattr(frappe.share, "add_docshare", None)
	if add:
		return add(rights["doctype"], rights["docname"], **kwargs)
	return frappe.share.add(rights["doctype"], rights["docname"], **kwargs)


def _current_share(rights):
	return frappe.db.get_value(
		"DocShare",
		{
			"user": rights["user"],
			"share_doctype": rights["doctype"],
			"share_name": rights["docname"],
			"everyone": 0,
		},
		["read", "write", "share", "submit"],
		as_dict=True,
	)


def _remember(rights):
	pending = frappe.flags.get("hero_assigned_shares")
	if not isinstance(pending, dict):
		pending = {}
		frappe.flags.hero_assigned_shares = pending
	pending[_share_key(rights["doctype"], rights["docname"], rights["user"])] = rights


def _remembered(doctype, name, user):
	pending = frappe.flags.get("hero_assigned_shares")
	if not isinstance(pending, dict):
		return None
	return pending.get(_share_key(doctype, name, user))


def _share_key(doctype, name, user):
	return (str(doctype or ""), str(name or ""), clean_text(user))


def _assignable_meta(doctype):
	doctype = str(doctype or "").strip()
	if not doctype or not frappe.db.exists("DocType", doctype):
		return None
	meta = frappe.get_meta(doctype)
	if meta.istable or as_flag(getattr(meta, "is_virtual", 0)):
		return None
	return meta


def _sharing_enabled() -> bool:
	return not as_flag(frappe.get_system_settings("disable_document_sharing"))


def _skip_request() -> bool:
	return bool(frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch)
