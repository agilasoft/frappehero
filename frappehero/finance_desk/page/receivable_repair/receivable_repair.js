// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["receivable-repair"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Receivable Repair"),
		single_column: true,
	});
	wrapper.receivableRepair = new frappehero.ReceivableRepair(page);
};

frappehero.ReceivableRepair = class ReceivableRepair {
	constructor(page) {
		this.page = page;
		this.preview = null;
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<p class="fh-muted">${__("Submitted sales invoices move off the wrong receivable. USD invoices use the USD receivable. Every other currency uses the other receivable. Receipts move with the invoices. Nothing is cancelled.")}</p>
				<div class="fh-filters">
					<div class="fh-company"></div>
					<div class="fh-wrong"></div>
					<div class="fh-usd"></div>
					<div class="fh-other"></div>
					<button type="button" class="fh-btn" data-action="preview">${__("Preview")}</button>
					<button type="button" class="fh-btn" data-action="apply" disabled>${__("Apply")}</button>
					<button type="button" class="fh-btn-quiet" data-action="defaults">${__("Set company default")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-note"></div>
				<div class="fh-split">
					<div class="fh-detail fh-invoices"></div>
					<div class="fh-detail fh-payments"></div>
				</div>
			</div>
		`);
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
							account_type: "Receivable",
						},
					}),
				},
				render_input: true,
			});
		this.companyControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-company"),
			df: { fieldtype: "Link", fieldname: "company", options: "Company", label: __("Company") },
			render_input: true,
		});
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		this.wrongControl = account(this.page.main.find(".fh-wrong"), "wrong_account", "Receivable to leave");
		this.usdControl = account(this.page.main.find(".fh-usd"), "usd_account", "USD receivable");
		this.otherControl = account(this.page.main.find(".fh-other"), "other_account", "Other currencies");
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", () => this.clearPreview());
	}

	args() {
		return {
			company: this.companyControl.get_value(),
			wrong_account: this.wrongControl.get_value(),
			usd_account: this.usdControl.get_value(),
			other_account: this.otherControl.get_value(),
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
		if (button.dataset.action === "defaults") {
			await this.applyDefaults();
		}
	}

	async load() {
		const args = this.args();
		if (!args.company || !args.wrong_account || !args.usd_account || !args.other_account) {
			frappe.msgprint(__("Choose the company and the three receivables."));
			return;
		}
		this.preview = await frappehero.call("frappehero.finance_desk.api.preview_receivable_repair", args);
		this.render();
	}

	render() {
		const state = this.preview || {};
		const counts = state.counts || {};
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${counts.move_invoices || 0}</b><span>${__("Invoices to move")}</span></div>
			<div class="fh-stat"><b>${counts.move_payments || 0}</b><span>${__("Receipts to move")}</span></div>
			<div class="fh-stat"><b>${counts.held_invoices || 0}</b><span>${__("Invoices held")}</span></div>
			<div class="fh-stat"><b>${counts.held_payments || 0}</b><span>${__("Receipts held")}</span></div>
		`);
		const notes = [];
		if (state.blocked) {
			notes.push(`<p>${frappehero.esc(state.blocked)}</p>`);
		}
		if (state.multi_ready === false) {
			notes.push(`<p>${__("Migrate Frappe Hero before a receipt can use more than one receivable.")}</p>`);
		}
		const defaults = state.defaults || {};
		const parties = defaults.parties || [];
		notes.push(
			`<p class="fh-muted">${frappehero.esc(
				__("Company default becomes {0}. {1} customer or group accounts that still name the old receivable will change. Cancelled documents stay as they are. A receipt that does not allocate these invoices stays on the old receivable.", [
					defaults.company_default || "",
					parties.length,
				])
			)}</p>`
		);
		this.page.main.find(".fh-note").html(notes.join(""));
		this.page.main.find(".fh-invoices").html(this.table(
			__("Sales invoices"),
			[__("Invoice"), __("Currency"), __("Outstanding"), __("To"), __("Status")],
			(state.invoices || []).map((row) => [
				row.name,
				row.currency,
				row.outstanding_amount,
				row.action === "move" ? row.to_account : row.reason,
				row.action,
			])
		));
		this.page.main.find(".fh-payments").html(this.table(
			__("Receipts"),
			[__("Receipt"), __("Bank amount"), __("Receivable"), __("Status")],
			(state.payments || []).map((row) => [
				row.name,
				row.bank_amount,
				row.action === "move" ? row.party_account || row.advance_account : row.reason,
				row.action === "move" ? row.mode : row.action,
			])
		));
		const canApply = state.signature && !state.blocked && (counts.move_invoices || counts.move_payments) && state.multi_ready !== false;
		this.page.main.find('[data-action="apply"]').prop("disabled", !canApply);
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
		const args = this.args();
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(
				__("Update these submitted invoices and receipts in place? Nothing is cancelled."),
				() => resolve(true),
				() => resolve(false)
			);
		});
		if (!confirmed) {
			return;
		}
		const result = await frappehero.call("frappehero.finance_desk.api.apply_receivable_repair", {
			...args,
			signature: this.preview.signature,
		});
		const failed = (result.chains || []).filter((row) => row.status !== "applied");
		frappe.msgprint(
			failed.length
				? __("Moved {0} invoices and {1} receipts. {2} chains were left unchanged.", [
					result.applied_invoices || 0,
					result.applied_payments || 0,
					failed.length,
				])
				: __("Moved {0} invoices and {1} receipts.", [result.applied_invoices || 0, result.applied_payments || 0])
		);
		await this.load();
	}

	async applyDefaults() {
		const args = this.args();
		if (!args.company || !args.wrong_account || !args.usd_account || !args.other_account) {
			frappe.msgprint(__("Choose the company and the three receivables."));
			return;
		}
		const plan = await frappehero.call("frappehero.finance_desk.api.preview_receivable_defaults", args);
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(
				__("Set the company default receivable to {0}, and update {1} party accounts that still use the old receivable?", [
					plan.company_default,
					(plan.parties || []).length,
				]),
				() => resolve(true),
				() => resolve(false)
			);
		});
		if (!confirmed) {
			return;
		}
		await frappehero.call("frappehero.finance_desk.api.apply_receivable_defaults", args);
		frappe.msgprint(__("Company default receivable updated."));
		if (this.preview) {
			await this.load();
		}
	}
};
