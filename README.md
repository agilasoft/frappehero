# Frappe Hero

Desk tools for the awkward admin jobs in Frappe and ERPNext: who may use which records, which accounts still have nowhere to go, and which invoices are in dispute.

Requires Frappe 15 or newer and ERPNext. Permission Studio writes real [User Permissions](https://docs.frappe.io/erpnext/user-permissions). Account Mapper reads the chart of accounts.

## Install

```bash
cd ~/frappe-bench
bench get-app https://github.com/agilasoft/frappehero.git
bench --site your-site install-app frappehero
bench --site your-site migrate
```

**Frappe Hero** is an icon on the desktop and opens at `/desk/frappe-hero`. The dock lists Frappe Hero, Permission Studio, Accounts Mapping, Access Desk, Finance Desk, and Dispute Desk. System Manager can use every module. Accounts Manager can use Account Mapper, the unmapped report, the finance desk, and the dispute desk.

## Permission Studio

User Permissions are one row per user, per document, per value. Permission Studio starts from the team instead.

1. Create a group, for example "North sales" or "Warehouse A". Edit the group name in the header and save. The rename follows the group into User Permissions, reviews, and shares.
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

**Invoice Creation Tool** is ERPNext's Opening Invoice Creation Tool. Finance Desk links it for System Manager, which is the role ERPNext grants on that screen. Invoice Type gains **Credit Note** and **Debit Note** beside Sales and Purchase. A credit note uploads as a return Sales Invoice. A debit note uploads as a return Purchase Invoice. Both stay opening entries, posted to the temporary opening account, with a negative quantity and a positive rate, so the party balance goes down. Enter the note amount as a positive Outstanding Amount. A negative amount in the file is accepted and still reduces the balance.

**Against Invoice** is on the upload template for a credit note or a debit note. When that number is a submitted sales invoice (credit note) or purchase invoice (debit note) in the same company, the note is linked and reduces that invoice. Any other number is stored on the note, and the note keeps the balance itself. Choose the type, download the table template, fill it in, and upload it. Sales still uploads a Sales Invoice. Purchase still uploads a Purchase Invoice.

**BSP Rates** reads the Bangko Sentral ng Pilipinas daily reference bulletin and writes Currency Exchange rows. The rate is pesos per one unit of the foreign currency. USD uses the BSP reference rate. Other currencies use the peso equivalent on the bulletin. SDR and metals are left out. A rate typed by hand for that date and pair stays as it is. **Write inverse** also stores PHP to the foreign currency, because ERPNext does not turn a pair around on its own. The daily job fills bulletins in the lookback window that are not already stored. Turn that job off on BSP Settings. Preview a range of up to 31 days, then apply it.

**Cheque Leaf** is the set of cheque numbers for one company bank account. Set a range, with an optional prefix and zero-padding, paste extra numbers, or edit the rows. Saving adds the range to the set. **Rebuild available numbers** replaces the free numbers from that range. Spoil a spare number by marking it Cancelled. Assigned and used numbers stay put. One active leaf per bank account can be the default. **Cheque Leaf** on the Finance Desk shows how many numbers are still free.

On **Mode of Payment**, tick **Uses Cheque Leaf**, or name the mode cheque or check. A Payment Entry with Payment Type **Pay** and that mode takes the next available number from the bank account's active leaf and writes it to Cheque/Reference No. When the reference date is still empty, the posting date is used. Saving a draft reserves the number. Submitting marks it used. Cancelling the payment voids that leaf, so the number is issued once. Deleting the draft puts the number back. **Assign Cheque Number** picks a specific free number. A bank account with no active leaf leaves the reference number to be typed by hand. Accounts User can pay with a leaf. Accounts Manager sets the leaves up.

## Dispute Desk

System Manager and Accounts Manager.

A dispute always points at one sales invoice. The document that raised it can be that invoice, or a record from logistics, ERPNext, or another app. **Dispute Desk** asks for the source DocType, the source document, and the invoice. Sales Invoice has **Raise Dispute** under the Dispute menu. Other modules call `frappehero.dispute_desk.api.raise_dispute`.

Opening the dispute releases every active action on that invoice. Hold, Collection, and Dunning are the usual kinds. A module can register any other kind on **Hero Invoice Action** with `register_invoice_action`. Released actions stay released after the dispute is resolved or cancelled. A second open dispute for the same invoice is rejected.

**Dispute Desk** filters by company, customer, sales invoice, status, dispute date, and a search across the invoice, customer, source, and reason.

**Statement of Account** and **Receivables Aging** leave an open dispute out of the amount due and the aging buckets. The on-screen table is only the invoices still due. **Disputed Transactions** is a section on the printout. Resolving or cancelling the dispute moves the invoice back into the table.

On a site, an open ERPNext Dunning that names the invoice is marked Resolved. Draft dunning is left alone, and nothing is cancelled. A Sales Invoice hold (`on_hold` or `is_on_hold`) is cleared when that field exists.

## Tests

The rules for grants, conflicts, the account tree, role diffs, reviews, dimensions, tax inheritance, opening journals, opening credit and debit notes, and cheque leaves run without a site:

```bash
python -m unittest discover -s frappehero -p "test_*.py"
```

Desk behavior needs a bench. These tests do not start one.
