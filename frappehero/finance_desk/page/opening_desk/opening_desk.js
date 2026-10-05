// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["opening-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Opening and Reclass Desk"),
		single_column: true,
	});
	wrapper.opening = new frappehero.OpeningDesk(page);
};

frappe.pages["opening-desk"].on_page_show = function (wrapper) {
	if (wrapper.opening) {
		wrapper.opening.refresh();
	}
};

frappehero.OpeningDesk = class OpeningDesk {
	constructor(page) {
		this.page = page;
		this.batches = [];
		this.current = null;
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("New Batch"), () => this.createBatch(), "add");
		this.page.main.html(`<div class="fh-app"><div class="fh-body"><aside class="fh-list"></aside><section class="fh-detail"></section></div></div>`);
		this.listEl = this.page.main.find(".fh-list");
		this.detailEl = this.page.main.find(".fh-detail");
		this.page.main.find(".fh-app").get(0).addEventListener("click", (event) => this.onClick(event));
		this.refresh();
	}

	async refresh() {
		this.batches = await frappehero.call("frappehero.finance_desk.api.list_opening_batches");
		const names = (this.batches || []).map((row) => row.name);
		if (this.selected && names.includes(this.selected)) {
			this.current = await frappehero.call("frappehero.finance_desk.api.get_opening_batch", { name: this.selected });
		} else {
			this.selected = names[0] || null;
			this.current = this.selected
				? await frappehero.call("frappehero.finance_desk.api.get_opening_batch", { name: this.selected })
				: null;
		}
		this.render();
	}

	render() {
		this.listEl.html(
			(this.batches || [])
				.map(
					(row) => `
					<button type="button" class="fh-card ${row.name === this.selected ? "fh-selected" : ""}" data-action="open" data-name="${frappehero.esc(row.name)}">
						<span class="fh-card-text"><strong>${frappehero.esc(row.name)}</strong><span class="fh-muted">${frappehero.esc(row.company || "")} · ${frappehero.esc(row.purpose || "")}</span></span>
						<span class="fh-pill">${frappehero.esc(row.status)}</span>
					</button>`
				)
				.join("") || `<div class="fh-empty">${__("No batches yet.")}</div>`
		);
		const batch = this.current;
		if (!batch) {
			this.detailEl.html(`<div class="fh-empty">${__("Paste a trial balance. The journal is created as a draft only when every line matches and the difference is zero.")}</div>`);
			return;
		}
		const lines = (batch.lines || [])
			.map((line) => {
				const tone = line.match_status === "Matched" ? "fh-ok" : "";
				return `<tr class="${line.match_status === "Ambiguous" ? "fh-bad" : ""}">
					<td>${frappehero.esc(line.account_number || "")}</td>
					<td>${frappehero.esc(line.account_name || "")}</td>
					<td>${frappehero.esc(line.debit)}</td>
					<td>${frappehero.esc(line.credit)}</td>
					<td class="${tone}">${frappehero.esc(line.match_status)}<div class="fh-muted">${frappehero.esc(line.matched_account || line.match_reason || "")}</div></td>
					<td>${batch.journal_entry ? "" : `<button type="button" class="fh-btn-quiet" data-action="match" data-line="${frappehero.esc(line.name)}">${__("Match")}</button>`}</td>
				</tr>`;
			})
			.join("");
		this.detailEl.html(`
			<div class="fh-detail-head">
				<div>
					<h2>${frappehero.esc(batch.name)}</h2>
					<div class="fh-muted">${frappehero.esc(batch.company)} · ${frappehero.esc(batch.posting_date)} · ${frappehero.esc(batch.purpose)}</div>
				</div>
				<div class="fh-actions">
					${batch.journal_entry ? `<a class="fh-btn" href="/app/journal-entry/${encodeURIComponent(batch.journal_entry)}">${frappehero.esc(batch.journal_entry)}</a>` : `<button type="button" class="fh-btn" data-action="journal" ${batch.can_create ? "" : "disabled"}>${__("Create draft journal")}</button>`}
				</div>
			</div>
			<div class="fh-stats">
				<div class="fh-stat"><b>${batch.debit_total || 0}</b><span>${__("Debit")}</span></div>
				<div class="fh-stat"><b>${batch.credit_total || 0}</b><span>${__("Credit")}</span></div>
				<div class="fh-stat"><b>${batch.difference || 0}</b><span>${__("Difference")}</span></div>
				<div class="fh-stat"><b>${batch.unmatched || 0}</b><span>${__("Unmatched")}</span></div>
			</div>
			${batch.journal_entry ? "" : `<label>${__("Trial balance")}<textarea class="fh-wide fh-paste" placeholder="${__("Account number, account name, debit, credit")}"></textarea></label>
			<div class="fh-actions"><button type="button" class="fh-btn" data-action="import">${__("Import and match")}</button></div>`}
			<table class="fh-matrix"><thead><tr><th>${__("Number")}</th><th>${__("Name")}</th><th>${__("Debit")}</th><th>${__("Credit")}</th><th>${__("Match")}</th><th></th></tr></thead><tbody>${lines || `<tr><td>${__("Paste a trial balance to add lines.")}</td></tr>`}</tbody></table>
		`);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "open") {
			this.selected = button.dataset.name;
			this.current = await frappehero.call("frappehero.finance_desk.api.get_opening_batch", { name: this.selected });
			this.render();
		}
		if (button.dataset.action === "import" && this.current) {
			this.current = await frappehero.call("frappehero.finance_desk.api.import_opening_text", {
				batch: this.current.name,
				text: this.detailEl.find(".fh-paste").val() || "",
			});
			this.batches = await frappehero.call("frappehero.finance_desk.api.list_opening_batches");
			this.render();
		}
		if (button.dataset.action === "match" && this.current) {
			this.matchLine(button.dataset.line);
		}
		if (button.dataset.action === "journal" && this.current) {
			const result = await frappehero.call("frappehero.finance_desk.api.create_opening_journal", { batch: this.current.name });
			this.current = result.batch;
			this.batches = await frappehero.call("frappehero.finance_desk.api.list_opening_batches");
			frappe.show_alert({ message: __("Draft {0} created", [result.journal_entry]), indicator: "green" });
			this.render();
		}
	}

	matchLine(lineName) {
		const company = this.current.company;
		frappe.prompt(
			[
				{
					fieldname: "account",
					fieldtype: "Link",
					options: "Account",
					label: __("Ledger Account"),
					ignore_user_permissions: 1,
					get_query: () => ({ filters: { company, is_group: 0 } }),
				},
			],
			async (values) => {
				this.current = await frappehero.call("frappehero.finance_desk.api.set_opening_match", {
					batch: this.current.name,
					line_name: lineName,
					account: values.account || "",
				});
				this.render();
			},
			__("Match line"),
			__("Save")
		);
	}

	createBatch() {
		frappe.prompt(
			[
				{ fieldname: "batch_name", fieldtype: "Data", label: __("Batch Name"), reqd: 1 },
				{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1, default: frappe.defaults.get_user_default("Company") },
				{ fieldname: "posting_date", fieldtype: "Date", label: __("Posting Date"), reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: "purpose", fieldtype: "Select", label: __("Purpose"), options: "Opening Entry\nReclass", default: "Opening Entry" },
			],
			async (values) => {
				this.current = await frappehero.call("frappehero.finance_desk.api.create_opening_batch", values);
				this.selected = this.current.name;
				this.batches = await frappehero.call("frappehero.finance_desk.api.list_opening_batches");
				this.render();
			},
			__("New Batch"),
			__("Create")
		);
	}
};
