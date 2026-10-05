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

Open the **Frappe Hero** workspace. System Manager can use both modules. Accounts Manager can use Account Mapper and the unmapped report.

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

## Suggested next modules

These are also listed in the desk under **Next Modules**. Each one continues a module that is already here.

**Role Composer.** Role Permission Manager edits one DocType at a time. A matrix of roles by DocTypes, with clone and diff, shows where nobody has read. User permissions decide which records open. Roles decide which actions exist.

**Access Review.** A scheduled sign-off per permission group: confirm the members, confirm the values, and list manual User Permissions that no group explains.

**Default Value Sets.** Reuse a permission group as the audience for company, warehouse, cost center, and letter head defaults, and show users whose defaults disagree.

**Share Desk.** For one document, show role access, user permissions, and shares together. Share it with a permission group and give the share an end date.

**Dimension Coverage.** Find accounts and GL entries missing Cost Center, Project, or Branch, and map a default dimension the way Account Mapper maps a target.

**Tax Template Mapper.** A matrix of item tax template by item group and tax category, with the unmapped combinations called out.

**Opening and Reclass Desk.** Match an imported trial balance to accounts with the same suggestions Account Mapper uses, and post the opening journal only when the difference is zero.

**Notification Router.** Send alerts for unmapped accounts, or for users in no group, to a permission group instead of a fixed email list.

## Tests

The rules for grants, conflicts, the account tree, and suggestions run without a site:

```bash
python -m unittest discover -s frappehero -p "test_*.py"
```

Desk behavior needs a bench. These tests do not start one.
