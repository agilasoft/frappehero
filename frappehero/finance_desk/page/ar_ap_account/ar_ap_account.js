// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["ar-ap-account"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("AR/AP Account"),
		single_column: true,
	});
	wrapper.arApAccount = new frappehero.ArApAccount(page);
};

frappehero.ArApAccount = class ArApAccount {
	constructor(page) {
		this.page = page;
		this.preview = null;
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<p class="fh-muted">${__("Change the receivable or payable GL account on submitted sales or purchase invoices. Receipts and journals that post those invoices change with them. An exchange gain or loss journal changes its receivable or payable line, and the gain or loss account stays. A receipt that still posts to the current GL account changes too. A receipt with taxes or deductions stays on one GL account, and the tax amount stays as submitted. The new GL account can use a different currency. The company-currency amount and the bank amount stay as submitted. Nothing is cancelled.")}</p>
				<div class="fh-filters">
					<div class="fh-company"></div>
					<div class="fh-side"></div>
					<div class="fh-from"></div>
					<div class="fh-to"></div>
					<button type="button" class="fh-btn" data-action="preview">${__("Preview")}</button>
					<button type="button" class="fh-btn" data-action="apply" disabled>${__("Apply")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-note"></div>
				<div class="fh-split">
					<div class="fh-detail fh-invoices"></div>
					<div class="fh-detail fh-payments"></div>
				</div>
				<div class="fh-detail fh-journals"></div>
			</div>
		`);
		this.companyControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-company"),
			df: { fieldtype: "Link", fieldname: "company", options: "Company", label: __("Company") },
			render_input: true,
		});
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		this.sideControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-side"),
			df: {
				fieldtype: "Select",
				fieldname: "side",
				label: __("Account type"),
				options: ["Receivable", "Payable"],
			},
			render_input: true,
		});
		this.sideControl.set_value("Receivable");
		const account = (parent, fieldname, label) =>
			frappe.ui.form.make_control({
				parent,
				df: {
					fieldtype: "Link",
					fieldname,
					options: "Account",
					label: __(label),
					ignore_user_permissions: 1,
					get_query: () => ({
						filters: {
							company: this.companyControl.get_value(),
							is_group: 0,
							account_type: this.sideControl.get_value() || "Receivable",
						},
					}),
				},
				render_input: true,
			});
		this.fromControl = account(this.page.main.find(".fh-from"), "from_account", "Current GL account");
		this.toControl = account(this.page.main.find(".fh-to"), "to_account", "New GL account");
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", () => this.clearPreview());
	}

	args() {
		return {
			company: this.companyControl.get_value(),
			side: this.sideControl.get_value(),
			from_account: this.fromControl.get_value(),
			to_account: this.toControl.get_value(),
		};
	}

	clearPreview() {
		this.preview = null;
		this.page.main.find('[data-action="apply"]').prop("disabled", true);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "preview") {
			await this.load();
		}
		if (button.dataset.action === "apply") {
			await this.apply();
		}
	}

	async load() {
		const args = this.args();
		if (!args.company || !args.side || !args.from_account || !args.to_account) {
			frappe.msgprint(__("Choose the company, Receivable or Payable, and both GL accounts."));
			return;
		}
		this.preview = await frappehero.call("frappehero.finance_desk.api.preview_ar_ap_account", args);
		this.render();
	}

	render() {
		const state = this.preview || {};
		const counts = state.counts || {};
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${counts.move_invoices || 0}</b><span>${__("Invoices to change")}</span></div>
			<div class="fh-stat"><b>${counts.move_payments || 0}</b><span>${__("Payments to change")}</span></div>
			<div class="fh-stat"><b>${counts.move_journals || 0}</b><span>${__("Journals to change")}</span></div>
			<div class="fh-stat"><b>${counts.stay_invoices || 0}</b><span>${__("Invoices staying")}</span></div>
			<div class="fh-stat"><b>${counts.held_invoices || 0}</b><span>${__("Invoices held")}</span></div>
		`);
		const notes = [];
		if (state.blocked) {
			notes.push(`<p>${frappehero.esc(state.blocked)}</p>`);
		}
		if (state.multi_ready === false) {
			notes.push(`<p>${__("Migrate Frappe Hero before changing a payment that uses more than one GL account.")}</p>`);
		}
		notes.push(
			`<p class="fh-muted">${__(
				"An invoice in another currency stays on its current GL account. When the currency changes, an unallocated advance stays on its current GL account. Customer and supplier records stay as they are. Cancelled documents stay as they are."
			)}</p>`
		);
		this.page.main.find(".fh-note").html(notes.join(""));
		const invoiceLabel = state.doctype === "Purchase Invoice" ? __("Purchase invoices") : __("Sales invoices");
		const partyLabel = state.doctype === "Purchase Invoice" ? __("Supplier") : __("Customer");
		this.page.main.find(".fh-invoices").html(this.table(
			invoiceLabel,
			[__("Invoice"), partyLabel, __("Outstanding"), __("New GL account"), __("Status")],
			(state.invoices || []).map((row) => [
				row.name,
				row.party,
				row.outstanding_amount,
				row.action === "move" ? row.to_account : row.reason,
				this.statusLabel(row.action),
			])
		));
		this.page.main.find(".fh-payments").html(this.table(
			__("Payments"),
			[__("Payment"), __("Bank amount"), __("GL account"), __("Status")],
			(state.payments || []).map((row) => [
				row.name,
				row.bank_amount,
				row.action === "move" ? row.party_account || row.advance_account : row.reason,
				this.statusLabel(row.action),
			])
		));
		this.page.main.find(".fh-journals").html(this.table(
			__("Journals"),
			[__("Journal"), __("Debit total"), __("Status")],
			(state.journals || []).map((row) => [
				row.name,
				row.debit_total,
				row.action === "move" ? this.statusLabel(row.action) : row.reason,
			])
		));
		const canApply =
			state.signature &&
			!state.blocked &&
			(counts.move_invoices || counts.move_payments || counts.move_journals) &&
			state.multi_ready !== false;
		this.page.main.find('[data-action="apply"]').prop("disabled", !canApply);
	}

	statusLabel(action) {
		if (action === "move") {
			return __("Change");
		}
		if (action === "stay") {
			return __("Stays");
		}
		if (action === "held") {
			return __("Held");
		}
		return action || "";
	}

	table(title, headings, rows) {
		const head = headings.map((label) => `<th>${frappehero.esc(label)}</th>`).join("");
		const body = rows
			.map((row) => `<tr>${row.map((cell) => `<td>${frappehero.esc(cell)}</td>`).join("")}</tr>`)
			.join("");
		return `<h3>${frappehero.esc(title)}</h3><table class="table table-bordered"><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${headings.length}">${__("Nothing in this list.")}</td></tr>`}</tbody></table>`;
	}

	async apply() {
		if (!this.preview || !this.preview.signature) {
			return;
		}
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(
				__("Change the GL account on these submitted invoices, receipts, and journals? Nothing is cancelled."),
				() => resolve(true),
				() => resolve(false)
			);
		});
		if (!confirmed) {
			return;
		}
		const result = await frappehero.call("frappehero.finance_desk.api.apply_ar_ap_account", {
			...this.args(),
			signature: this.preview.signature,
		});
		const failed = (result.chains || []).filter((row) => row.status !== "applied");
		const summary = __("Changed the GL account on {0} invoices, {1} payments, and {2} journals.", [
			result.applied_invoices || 0,
			result.applied_payments || 0,
			result.applied_journals || 0,
		]);
		const reasons = failed
			.map((row) => row.reason)
			.filter(Boolean)
			.slice(0, 8)
			.map((reason) => `<p>${frappehero.esc(reason)}</p>`)
			.join("");
		frappe.msgprint(
			failed.length
				? `${frappehero.esc(summary)}<p>${frappehero.esc(
					__("{0} chains were left unchanged.", [failed.length])
				)}</p>${reasons}`
				: summary
		);
		await this.load();
	}
};
