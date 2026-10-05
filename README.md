# Frappe Hero

Desk tools for the awkward admin jobs in Frappe and ERPNext: who may use which records, and which accounts still have nowhere to go.

Requires Frappe 15 or newer and ERPNext. Permission Studio writes real [User Permissions](https://docs.frappe.io/erpnext/user-permissions). Account Mapper reads the chart of accounts.

## Install

```bash
cd ~/frappe-bench
bench get-app https://github.com/agilasoft/frappehero.git
bench --site your-site install-app frappehero
bench --site your-site migrate
```

Open the **Frappe Hero** workspace. System Manager can use every module. Accounts Manager can use Account Mapper, the unmapped report, and the finance desk.

## Permission Studio

User Permissions are one row per user, per document, per value. Permission Studio starts from the team instead.

1. Create a group, for example "North sales" or "Warehouse A".
2. Add users. Filter the picker by role, user type, and whether the user is enabled. People who already belong to a group are marked.
3. Add permitted values. Pick a DocType, tick the records (companies, territories, branches, warehouses), and choose:
   - **Apply to all document types**, or limit the rule with **Applicable For**
   - **Use as default**, so new documents start on that value
   - **Hide descendants**, for tree DocTypes such as Territory
4. Save. The app creates one User Permission for every member and every value.

The page shows a coverage bar, a member and value list, and a grid of who can use what. Filters cover group name, user, role, DocType, enabled state, and groups that disagree.

What the sync will and will not do:

- Groups that are disabled grant nothing.
- The same value granted by two groups becomes one User Permission, owned by both.
- A User Permission someone created by hand is left in place. The group is marked **Needs Attention**.
- Two defaults for the same user and DocType are rejected when the scopes overlap. Frappe only allows one default in that case.
- Administrator and Guest cannot be members.
- Deleting a group removes only the User Permissions that no other group still grants.

**Permission Coverage** lists enabled users, the groups they belong to, and how many manual User Permissions they still have.

The Permission Group form is still there for import and for people who prefer a grid. **Open Permission Studio** jumps back to the group.

## Account Mapper

An account map sends each ledger account somewhere else.

| Mapping type | What you fill in |
| --- | --- |
| Another Company | A ledger in the target company. Used for consolidation or a parallel chart. |
| External Code | A code and name from a bank, statutory file, or other system. |
| Reporting Group | A label such as the account type, for statements that are not the chart itself. |

The page opens on **unmapped** ledger accounts. Group accounts stay visible as folders so the chart still reads as a tree. The coverage bar is the whole chart, not just the filtered rows.

Filters: company, map, search, root type, account type, mapped / partial / unmapped, and disabled accounts. Tick several ledgers to give them the same target. **Suggest matches** proposes:

- the same account number, when exactly one target ledger has it
- otherwise the same account name, when exactly one target matches
- the account number as the external code
- the account type, or the root type, as the reporting group

Ambiguous matches are skipped rather than guessed. **Unmapped Accounts** is the same list as a report.

## Access Desk

System Manager tools that sit next to Permission Studio. **Next Modules** opens each one.

**Role Composer** is a grid of roles by DocType for one permission bit at a time (read, write, submit, and the rest). Filter by module, search, or "nobody can read". Click a cell to turn that bit on or off. Changes go through Custom DocPerm, so standard DocPerm rows shipped with an app stay untouched. Clone copies a role into a new one. Diff lists the bits where two roles disagree.

**Access Review** starts a sign-off for every enabled permission group. Confirm the members and values, or mark an exception. If the group changes after that, the line becomes Stale until someone confirms it again. The same page lists User Permissions that no group explains.

**Default Value Sets** reuse a permission group as the audience for company, warehouse, cost center, letter head, and any other DocType default. A blank current default is ready to fill. A different value is a conflict. Apply writes `frappe.defaults` for each member.

**Share Desk** picks one document and shows roles with read, User Permissions that name it, and DocShares. Share it with a permission group. An end date is stored on the share; the daily job deletes shares after that date.

**Notification Router** emails a permission group for unmapped accounts, users who are in no group, or open access reviews. The daily job and Send Now both skip a route that already went out today.

## Finance Desk

System Manager and Accounts Manager.

**Dimension Coverage** picks a company and Cost Center, Project, or Branch. Each ledger shows whether its GL entries are complete, partial, missing, or empty. Set a default per account. Opt in if new GL entries should receive that value when the dimension is still empty. A value already on the entry is left alone. Branch is hidden when the GL Entry has no Branch field.

**Tax Template Mapper** walks item groups for one company. A group is mapped when it, or an ancestor, has an item tax template for that company. Items with no template of their own appear only when their group is unmapped. Assign a template to the groups you tick, or clear the templates for that company.

**Opening and Reclass Desk** pastes a trial balance. Lines match with the same rules as Account Mapper: one account number, otherwise one account name. An ambiguous number stays unmatched. The desk creates a draft Journal Entry when every line is matched and debit minus credit is about zero.

## Tests

The rules for grants, conflicts, the account tree, role diffs, reviews, dimensions, tax inheritance, and opening journals run without a site:

```bash
python -m unittest discover -s frappehero -p "test_*.py"
```

Desk behavior needs a bench. These tests do not start one.
