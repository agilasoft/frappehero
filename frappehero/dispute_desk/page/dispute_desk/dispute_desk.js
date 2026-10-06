// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["dispute-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Dispute Desk"),
		single_column: true,
	});
	wrapper.disputes = new frappehero.DisputeDesk(page);
};

frappe.pages["dispute-desk"].on_page_show = function (wrapper) {
	if (wrapper.disputes) {
		wrapper.disputes.refresh();
	}
};

frappehero.DisputeDesk = class DisputeDesk {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.current = null;
		this.filters = { text: "", status: "All", from_date: "", to_date: "" };
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("New Dispute"), () => this.createDispute(), "add");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-filters">
					<input type="search" class="fh-search" placeholder="${__("Search invoice, customer, source, reason")}">
					<div class="fh-company"></div>
					<div class="fh-customer"></div>
					<div class="fh-invoice"></div>
					<select class="fh-status">
						<option value="All">${__("All statuses")}</option>
						<option value="Open">${__("Open")}</option>
						<option value="Resolved">${__("Resolved")}</option>
						<option value="Cancelled">${__("Cancelled")}</option>
					</select>
					<input type="date" class="fh-from" aria-label="${__("From date")}">
					<input type="date" class="fh-to" aria-label="${__("To date")}">
				</div>
				<div class="fh-body"><aside class="fh-list"></aside><section class="fh-detail"></section></div>
			</div>
		`);
		this.listEl = this.page.main.find(".fh-list");
		this.detailEl = this.page.main.find(".fh-detail");
		this.companyControl = this.linkControl(".fh-company", "Company", __("Company"));
		this.customerControl = this.linkControl(".fh-customer", "Customer", __("Customer"));
		this.invoiceControl = this.linkControl(".fh-invoice", "Sales Invoice", __("Sales Invoice"));
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		this.companyControl.df.onchange = () => this.refresh();
		this.customerControl.df.onchange = () => this.refresh();
		this.invoiceControl.df.onchange = () => this.refresh();
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => this.onFilterChange(event));
		root.addEventListener("input", (event) => this.onFilterInput(event));
		this.refresh();
	}

	linkControl(selector, options, label) {
		return frappe.ui.form.make_control({
			parent: this.page.main.find(selector),
			df: { fieldtype: "Link", options, label },
			render_input: true,
		});
	}

	onFilterChange(event) {
		const target = event.target;
		if (target.classList.contains("fh-status")) {
			this.filters.status = target.value;
			this.refresh();
		}
		if (target.classList.contains("fh-from") || target.classList.contains("fh-to")) {
			this.filters.from_date = this.page.main.find(".fh-from").val() || "";
			this.filters.to_date = this.page.main.find(".fh-to").val() || "";
			this.refresh();
		}
	}

	onFilterInput(event) {
		if (!event.target.classList.contains("fh-search")) {
			return;
		}
		clearTimeout(this.timer);
		this.timer = setTimeout(() => {
			this.filters.text = event.target.value || "";
			this.refresh();
		}, 200);
	}

	filterArgs() {
		return {
			company: this.companyControl.get_value() || "",
			customer: this.customerControl.get_value() || "",
			sales_invoice: this.invoiceControl.get_value() || "",
			status: this.filters.status,
			text: this.filters.text,
			from_date: this.filters.from_date,
			to_date: this.filters.to_date,
		};
	}

	async refresh() {
		const request = (this.request = (this.request || 0) + 1);
		const rows = await frappehero.call("frappehero.dispute_desk.api.list_disputes", this.filterArgs());
		if (request !== this.request) {
			return;
		}
		const names = (rows || []).map((row) => row.name);
		let current = null;
		if (this.selected && names.includes(this.selected)) {
			current = await frappehero.call("frappehero.dispute_desk.api.get_dispute", { name: this.selected });
		} else {
			this.selected = names[0] || null;
			current = this.selected
				? await frappehero.call("frappehero.dispute_desk.api.get_dispute", { name: this.selected })
				: null;
		}
		if (request !== this.request) {
			return;
		}
		this.rows = rows || [];
		this.current = current;
		this.render();
	}

	render() {
		this.listEl.html(
			(this.rows || [])
				.map(
					(row) => `
					<button type="button" class="fh-card ${row.name === this.selected ? "fh-selected" : ""}" data-action="open" data-name="${frappehero.esc(row.name)}">
						<span class="fh-card-text"><strong>${frappehero.esc(row.sales_invoice)}</strong><span class="fh-muted">${frappehero.esc(row.customer || "")} · ${frappehero.esc(row.reference_doctype || "")}</span></span>
						<span class="fh-pill">${frappehero.esc(row.status)}</span>
					</button>`
				)
				.join("") || `<div class="fh-empty">${__("No disputes match these filters.")}</div>`
		);
		const dispute = this.current;
		if (!dispute) {
			this.detailEl.html(
				`<div class="fh-empty">${__("Raise a dispute from a logistics document, an ERPNext document, or any other source. The sales invoice leaves hold, collection, and dunning, and stays under Disputed Transactions on the statement and the aging.")}</div>`
			);
			return;
		}
		const releases = (dispute.releases || [])
			.map(
				(row) => `<tr>
					<td>${frappehero.esc(row.action_kind)}</td>
					<td>${frappehero.esc(row.source_doctype || "")}</td>
					<td>${frappehero.esc(row.source_name || "")}</td>
					<td>${frappehero.esc(row.previous_state || "")}</td>
				</tr>`
			)
			.join("");
		const open = dispute.status === "Open";
		this.detailEl.html(`
			<div class="fh-detail-head">
				<div>
					<h2>${frappehero.esc(dispute.sales_invoice)}</h2>
					<div class="fh-muted">${frappehero.esc(dispute.customer)} · ${frappehero.esc(dispute.company)} · ${frappehero.esc(dispute.dispute_date)}</div>
				</div>
				<div class="fh-actions">
					${open ? `<button type="button" class="fh-btn" data-action="resolve">${__("Resolve")}</button><button type="button" class="fh-btn" data-action="cancel">${__("Cancel")}</button>` : ""}
				</div>
			</div>
			<div class="fh-stats">
				<div class="fh-stat"><b>${frappehero.esc(dispute.status)}</b><span>${__("Status")}</span></div>
				<div class="fh-stat"><b>${dispute.release_count || 0}</b><span>${__("Released")}</span></div>
				<div class="fh-stat"><b>${frappehero.esc(dispute.source_module || dispute.reference_doctype || "")}</b><span>${__("Source")}</span></div>
				<div class="fh-stat"><b>${frappehero.esc(dispute.reference_name || "")}</b><span>${frappehero.esc(dispute.reference_doctype || "")}</span></div>
			</div>
			<p>${frappehero.esc(dispute.reason || "")}</p>
			<table class="fh-matrix"><thead><tr><th>${__("Action")}</th><th>${__("Source DocType")}</th><th>${__("Source")}</th><th>${__("Previous State")}</th></tr></thead><tbody>${releases || `<tr><td colspan="4">${__("No hold, collection, dunning, or other action was active.")}</td></tr>`}</tbody></table>
		`);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "open") {
			this.selected = button.dataset.name;
			this.current = await frappehero.call("frappehero.dispute_desk.api.get_dispute", { name: this.selected });
			this.render();
		}
		if (button.dataset.action === "resolve" && this.current) {
			await this.setStatus("Resolved");
		}
		if (button.dataset.action === "cancel" && this.current) {
			await this.setStatus("Cancelled");
		}
	}

	async setStatus(status) {
		this.current = await frappehero.call("frappehero.dispute_desk.api.set_dispute_status", {
			name: this.current.name,
			status,
		});
		this.rows = await frappehero.call("frappehero.dispute_desk.api.list_disputes", this.filterArgs());
		this.render();
	}

	createDispute() {
		let dialog;
		const fields = [
			{
				fieldname: "reference_doctype",
				fieldtype: "Link",
				options: "DocType",
				label: __("Source DocType"),
				reqd: 1,
				default: "Sales Invoice",
			},
			{
				fieldname: "reference_name",
				fieldtype: "Dynamic Link",
				options: "reference_doctype",
				label: __("Source Document"),
				reqd: 1,
			},
			{
				fieldname: "sales_invoice",
				fieldtype: "Link",
				options: "Sales Invoice",
				label: __("Sales Invoice"),
				description: __("Leave this blank when the source document is the sales invoice."),
				get_query: () => {
					const filters = { docstatus: 1 };
					if (!dialog) {
						return { filters };
					}
					const company = dialog.get_value("company");
					const customer = dialog.get_value("customer");
					if (company) {
						filters.company = company;
					}
					if (customer) {
						filters.customer = customer;
					}
					return { filters };
				},
			},
			{
				fieldname: "company",
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				reqd: 1,
				default: frappe.defaults.get_user_default("Company"),
			},
			{
				fieldname: "customer",
				fieldtype: "Link",
				options: "Customer",
				label: __("Customer"),
				reqd: 1,
			},
			{
				fieldname: "dispute_date",
				fieldtype: "Date",
				label: __("Dispute Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "source_module",
				fieldtype: "Data",
				label: __("Source Module"),
				description: __("Logistics, ERPNext, or the other module that raised this."),
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				reqd: 1,
			},
		];
		dialog = frappe.prompt(
			fields,
			async (values) => {
				this.current = await frappehero.call("frappehero.dispute_desk.api.raise_dispute", values);
				this.selected = this.current.name;
				this.rows = await frappehero.call("frappehero.dispute_desk.api.list_disputes", this.filterArgs());
				this.render();
			},
			__("New Dispute"),
			__("Raise")
		);
		return dialog;
	}
};
