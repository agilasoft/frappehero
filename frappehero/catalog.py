# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Modules suggested after Permission Studio and Account Mapper.

The desk page and the README both describe this list. Keep the records
self-contained so the page can render them without a database.
"""

MODULE_IDEAS = [
	{
		"name": "Role Composer",
		"area": "Permissions",
		"summary": "Compare roles, clone them, and see which DocTypes nobody can read.",
		"problem": (
			"Role Permission Manager edits one DocType at a time. Overlapping roles "
			"and DocTypes with no read permission stay hidden until someone is blocked."
		),
		"shape": (
			"A matrix of roles by DocTypes, with filters for module and permission bit. "
			"Clone a role, diff two roles, and highlight DocTypes where no role has read."
		),
		"builds_on": (
			"Permission Studio restricts which records a person can open. Roles decide "
			"which actions exist at all. The two belong on one review screen."
		),
	},
	{
		"name": "Access Review",
		"area": "Permissions",
		"summary": "Ask group owners to confirm, on a schedule, that access is still right.",
		"problem": (
			"People change teams and leave, while User Permissions and manual exceptions "
			"stay behind. There is no sign-off that the access still matches the job."
		),
		"shape": (
			"A monthly review per permission group: confirm members, confirm permitted "
			"values, and list manual User Permissions that no group explains. Export the "
			"sign-off for an auditor."
		),
		"builds_on": "Permission Studio already knows the groups, the grants, and the manual overlaps.",
	},
	{
		"name": "Default Value Sets",
		"area": "Permissions",
		"summary": "Give a whole group the same company, warehouse, cost center, and letter head.",
		"problem": (
			"Defaults are set one user at a time. A new teammate gets the right records "
			"and still types the wrong company on the next invoice."
		),
		"shape": (
			"Reuse a permission group as the audience. Pick field defaults, apply them "
			"to every member, and show users whose current defaults disagree."
		),
		"builds_on": "The groups you maintain for access are the same groups that should share defaults.",
	},
	{
		"name": "Share Desk",
		"area": "Permissions",
		"summary": "See user permissions, roles, and document shares for one record.",
		"problem": (
			"DocShare sits apart from User Permissions, so the question \"who can open "
			"this invoice?\" has no single answer."
		),
		"shape": (
			"Pick a document and see role access, user permissions, and shares together. "
			"Share it with a permission group, and give the share an end date."
		),
		"builds_on": "Permission groups are a ready-made audience for a share.",
	},
	{
		"name": "Dimension Coverage",
		"area": "Accounts",
		"summary": "Find accounts and entries missing Cost Center, Project, or Branch.",
		"problem": (
			"Accounting dimensions are mandatory on some accounts and optional on others. "
			"Missing values show up late, inside a report that will not balance by dimension."
		),
		"shape": (
			"For a company, list accounts and GL entries missing a required dimension. "
			"Map a default dimension per account the same way Account Mapper maps a target."
		),
		"builds_on": "Account Mapper's chart, filters, and unmapped list are the pattern to copy.",
	},
	{
		"name": "Tax Template Mapper",
		"area": "Accounts",
		"summary": "Match item groups and tax categories to tax templates, and list the gaps.",
		"problem": (
			"Item groups and tax categories drift. Invoices then pick the wrong template, "
			"or none, and the mistake is visible only after tax is posted."
		),
		"shape": (
			"A matrix of item tax template by item group and tax category, with unmapped "
			"combinations called out and a bulk assign action."
		),
		"builds_on": "Same mapped, partial, and unmapped states as the account map.",
	},
	{
		"name": "Opening and Reclass Desk",
		"area": "Accounts",
		"summary": "Turn a trial balance into an opening entry, and show what is still unmatched.",
		"problem": (
			"Opening balances and reclasses are journal entries typed by hand. It is hard "
			"to see which accounts have no opening, and easy to post a difference."
		),
		"shape": (
			"Import a trial balance, match lines to accounts with the same suggestions "
			"Account Mapper uses, and create the opening journal only when the difference is zero."
		),
		"builds_on": "Account number and account name suggestions, plus the unmapped report.",
	},
	{
		"name": "Notification Router",
		"area": "Both",
		"summary": "Send an alert to a permission group instead of a hard-coded email list.",
		"problem": (
			"Alerts for overdue invoices, low stock, and unmapped accounts are pinned to "
			"people. The list goes stale as soon as the team changes."
		),
		"shape": (
			"Pick a permission group as the audience. The recipients update when the group "
			"does. Start with unmapped accounts and users who belong to no group."
		),
		"builds_on": "Permission groups are already a living list of people with a job to do.",
	},
]


def ideas_for(area=None, text=None):
	"""Filter module ideas by area and a case-insensitive search string."""
	query = " ".join(str(text or "").casefold().split())
	area_name = (area or "").strip()
	matched = []
	for idea in MODULE_IDEAS:
		if area_name and area_name not in ("All", idea["area"]):
			continue
		if query:
			haystack = " ".join(
				[
					idea["name"],
					idea["area"],
					idea["summary"],
					idea["problem"],
					idea["shape"],
					idea["builds_on"],
				]
			).casefold()
			if query not in haystack:
				continue
		matched.append(idea)
	return matched
