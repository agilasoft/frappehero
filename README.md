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

**Frappe Hero** is an icon on the desktop and opens at `/desk/frappe-hero`. The dock lists Frappe Hero, Permission Studio, Accounts Mapping, Access Desk, Finance Desk, Dispute Desk, and Collections Desk. System Manager can use every module. Accounts Manager can use Account Mapper, the unmapped report, the finance desk, the dispute desk, and the collections desk. Accounts User can log collection calls, send a statement, raise a claim or incident, and draft a receipt.

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

Invoice Type stores Sales, Purchase, Credit Note, and Debit Note on the field itself. The desk script also adds the two notes when the dropdown is drawn, so a cached Sales and Purchase list cannot leave them out. After updating Frappe Hero, run `bench build --app frappehero` and `bench --site <site-name> migrate`, then reload the Opening Invoice Creation Tool.

**Receivable Repair** moves submitted sales invoices off the wrong receivable without cancelling them. USD invoices go to the USD receivable. Every other currency goes to the company-currency receivable. Credit notes keep the invoice they return against. A receipt moves with the invoices it settles, and its bank amount stays the same. A receipt that settled both a USD invoice and another currency stays one document, with each row on that invoice's receivable. An unallocated advance stays on the old account. A receipt with taxes or other deductions that would have to split, or that would change currency, is held, and so are the invoices it settles. Cancelled documents stay as they are. Preview lists the chains. Apply writes the new receivable onto the submitted documents and rebuilds each voucher's ledger. If the outstanding amount or the bank amount would change, that chain is left as it was. **Set company default** points the company receivable at the non-USD account and replaces a customer or customer-group account that still names the old receivable. A customer whose open invoices are all USD is pointed at the USD receivable. One customer account cannot vary by currency, so a customer with both currencies keeps the non-USD account. For a company whose opening invoices were posted to `11220.20.30 - Cash Advance on Behalf of Shipper - ATN`, the USD receivable is `11210.10.10 - Trade Receivables (USD) - ATN` and the other receivable is `11210.10.00 - Trade Receivables - ATN`. After updating Frappe Hero, run `bench build --app frappehero` and `bench --site <site-name> migrate`, then open Receivable Repair.

**BSP Rates** reads the Bangko Sentral ng Pilipinas daily reference bulletin and writes Currency Exchange rows. The rate is pesos per one unit of the foreign currency. USD uses the BSP reference rate. Other currencies use the peso equivalent on the bulletin. SDR and metals are left out. A rate typed by hand for that date and pair stays as it is. **Write inverse** also stores PHP to the foreign currency, because ERPNext does not turn a pair around on its own. The daily job fills bulletins in the lookback window that are not already stored. Turn that job off on BSP Settings. Preview a range of up to 31 days, then apply it.

**Cheque Leaf** is the set of cheque numbers for one company bank account. Set a range, with an optional prefix and zero-padding, paste extra numbers, or edit the rows. Saving adds the range to the set. **Rebuild available numbers** replaces the free numbers from that range. Spoil a spare number by marking it Cancelled. Assigned and used numbers stay put. One active leaf per bank account can be the default. **Cheque Leaf** on the Finance Desk shows how many numbers are still free.

On **Mode of Payment**, tick **Uses Cheque Leaf**, or name the mode cheque or check. A Payment Entry with Payment Type **Pay** and that mode takes the next available number from the bank account's active leaf and writes it to Cheque/Reference No. When the reference date is still empty, the posting date is used. Saving a draft reserves the number. Submitting marks it used. Cancelling the payment voids that leaf, so the number is issued once. Deleting the draft puts the number back. **Assign Cheque Number** picks a specific free number. A bank account with no active leaf leaves the reference number to be typed by hand. Accounts User can pay with a leaf. Accounts Manager sets the leaves up.

**Payment References** shows **Invoice Currency** and **Invoice Currency Amount**. The amount is the referenced document's rounded total, or its grand total when the rounded total is zero. Grand Total, Outstanding, and Allocated stay in the party account currency, and the allocated amount is unchanged. A sales invoice, purchase invoice, sales order, purchase order, or expense claim uses its own currency. A journal entry sums the party lines for this payment's party, in that account's currency. A dunning contributes a currency when the document has one. Saving or submitting a draft stores the columns, and opening the payment shows them again. After updating Frappe Hero, run `bench --site <site-name> migrate` and reload Payment Entry.

**Proof of Payment** is a mobile web app at `/proof-of-payment`, outside the desk. Scan the Payment Entry, or type its name. The page shows the party, the amount, and each reference. Take a photo or choose a JPEG, PNG, WebP, or PDF up to 10 MB. The file is stored on the payment, and a second file replaces it. **Pending upload** lists payments assigned to you that are not cancelled and still have no file. Assign the payment from the Payment Entry form. Finance Desk opens the same address, and the old desk page redirects there. Accounts User can open it. A guest is sent to log in. A cancelled payment can be viewed and cannot take a file. After updating Frappe Hero, run `bench build --app frappehero` and `bench --site <site-name> migrate`.

**Multi Currency Payment** is part of Payment Entry. One Pay or Receive voucher can leave a single bank and clear invoices that sit on different receivable or payable accounts and currencies. A supplier payment can leave a USD bank and clear a USD invoice, a PHP invoice, and a EUR invoice on the same Payment Entry. **Get Outstanding Invoices** loads every open sales or purchase invoice for that party, including invoices on another account. Each row keeps that invoice's account. Enter **Allocated (Invoice Currency)** for the part of the invoice you are paying. Outstanding is in that same currency. **Allocated (Account Currency)** is calculated from that amount and the invoice conversion rate, including when the account currency differs from the invoice currency. Bank Amount is that row's share of the bank. The party line posts at the invoice conversion rate, and the difference from the rate on the posting date goes to the company's exchange gain or loss account, on this Payment Entry. Leave the bank amount blank to use the allocated total. An amount above that total is an advance on the party account shown in the header. A customer receipt posts the other way: the bank is debited and the receivables are credited. A payment whose rows stay on the header party account submits exactly as ERPNext would, including Cheque Leaf. Deductions and taxes stay on a payment that uses one account. After updating Frappe Hero, run `bench --site <site-name> migrate` and reload Payment Entry.

## Dispute Desk

System Manager and Accounts Manager.

A dispute always points at one sales invoice. The document that raised it can be that invoice, or a record from logistics, ERPNext, or another app. **Dispute Desk** asks for the source DocType, the source document, and the invoice. Sales Invoice has **Raise Dispute** under the Dispute menu. Other modules call `frappehero.dispute_desk.api.raise_dispute`.

On Sales Invoice, dispute, credit, and holds sit on their own **Dispute** tab, after the other tabs. The invoice header is three columns: the customer, the dates, and the credit-note checks. A Customize Form field order that still has the Dispute section in that header is rewritten on migrate, and the form script moves the section onto the tab when the saved order has not caught up. **Credit** shows the customer credit limit for the company, the outstanding balance, and credit notes raised against the invoice. A credit note invoice also shows the invoice it was raised against. **Holds** lists an invoice hold (`on_hold` or `is_on_hold`) and any Hold action, including a hold this dispute has already released. When nothing is on hold, the tab says so.

Opening the dispute releases every active action on that invoice. Hold, Collection, and Dunning are the usual kinds. A module can register any other kind on **Hero Invoice Action** with `register_invoice_action`. Released actions stay released after the dispute is resolved or cancelled. A second open dispute for the same invoice is rejected.

**Dispute Desk** filters by company, customer, sales invoice, status, dispute date, and a search across the invoice, customer, source, and reason.

**Statement of Account** and **Receivables Aging** leave an open dispute out of the amount due and the aging buckets. The on-screen table is only the invoices still due. **Disputed Transactions** is a section on the printout. Resolving or cancelling the dispute moves the invoice back into the table.

On a site, an open ERPNext Dunning that names the invoice is marked Resolved. Draft dunning is left alone, and nothing is cancelled. A Sales Invoice hold (`on_hold` or `is_on_hold`) is cleared when that field exists.

## Collections Desk

System Manager, Accounts Manager, and Accounts User.

**Collection Call** is the collections cockpit. The queue is every customer in the company with an open sales invoice, plus anyone whose follow-up date has arrived. Follow-ups come first, then the oldest invoice. Filter to overdue balances, follow-ups that are due, or the calls you logged. Search covers the customer, the group, the territory, and the last outcome. The totals for the queue sit above it.

The customer name stays pinned. Under that are the group, the territory, the tax id, the credit limit, the aging, and the amount still due. Open disputes stay out of the amount due the same way the statement does. The phone is a `tel:` link. The call strip is next: direction, time, number, person reached, outcome, promise, follow-up, and notes. Open invoices sit under the strip, and receipts, disputes, earlier calls, and claims sit in two columns beside each other.

**Create** and **Open** are the desk's own menu buttons, in the filter bar:

- **Create call** writes a **Hero Collection Call**. A promise needs an amount and a date. No Answer, Busy, Wrong Number, and Voicemail cannot carry a promise. A callback needs a follow-up date.
- **Create statement** previews the statement and opens Statement of Account for that company and customer.
- **Send statement** emails that statement to the address they confirm, and stores the address and the time on the open call.
- **Create claim** and **Create incident** each create a **Hero Collection Report**. A claim that names one sales invoice can also open a dispute, which releases hold, collection, and dunning. Raising a dispute stays with Accounts Manager and System Manager.
- **Create payment** drafts a Receive Payment Entry for the ticked invoices, oldest due first, and opens it. The amount cannot exceed those invoices, and the invoices must share a receivable account and the company currency. Submit, cheque leaf, multi-currency, and proof of payment stay on Payment Entry. The company needs a default bank or cash account.
- **Create dispute** opens a dispute for the one invoice that is ticked.

**Open** reaches Statement of Account, the collection call list, and the claims and incidents list. The page does not place the call.

## Tests

The rules for grants, conflicts, the account tree, role diffs, reviews, dimensions, tax inheritance, opening journals, opening credit and debit notes, receivable repair, cheque leaves, multi-currency payments, proof of payment, and collection calls run without a site:

```bash
python -m unittest discover -s frappehero -p "test_*.py"
```

Desk behavior needs a bench. These tests do not start one.
