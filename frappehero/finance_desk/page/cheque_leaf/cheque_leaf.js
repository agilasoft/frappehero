// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["cheque-leaf"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Cheque Leaf"),
		single_column: true,
	});
	wrapper.chequeLeaf = new frappehero.ChequeLeaf(page);
};

frappe.pages["cheque-leaf"].on_page_show = function (wrapper) {
	if (wrapper.chequeLeaf && wrapper.chequeLeaf.loaded) {
		wrapper.chequeLeaf.load();
	}
};

frappehero.ChequeLeaf = class ChequeLeaf {
	constructor(page) {
		this.page = page;
		this.status = "all";
		this.usage = "all";
		this.search = "";
		this.state = null;
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<p class="fh-muted">${__("Each leaf is the set of cheque numbers for one bank account. A Pay entry with a cheque mode takes the next available number.")}</p>
				<div class="fh-filters">
					<div class="fh-company"></div>
					<div class="fh-bank"></div>
					<select class="fh-status">
						<option value="all">${__("All statuses")}</option>
						<option value="Active">${__("Active")}</option>
						<option value="Draft">${__("Draft")}</option>
						<option value="Closed">${__("Closed")}</option>
					</select>
					<select class="fh-usage">
						<option value="all">${__("All sets")}</option>
						<option value="open">${__("Numbers left")}</option>
						<option value="exhausted">${__("Exhausted")}</option>
						<option value="empty">${__("Empty")}</option>
					</select>
					<input type="search" class="fh-search" placeholder="${__("Search leaves")}">
					<button type="button" class="fh-btn" data-action="load">${__("Show leaves")}</button>
					<button type="button" class="fh-btn" data-action="new">${__("New leaf")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-matrix-wrap"></div>
			</div>
		`);
		this.companyControl = this.control(".fh-company", {
			fieldtype: "Link",
			fieldname: "company",
			options: "Company",
			label: __("Company"),
		});
		this.bankControl = this.control(".fh-bank", {
			fieldtype: "Link",
			fieldname: "bank_account",
			options: "Bank Account",
			label: __("Bank Account"),
			get_query: () => {
				const filters = { is_company_account: 1 };
				const company = this.companyControl.get_value();
				if (company) {
					filters.company = company;
				}
				return { filters };
			},
		});
		this.loaded = false;
		Promise.resolve(this.companyControl.set_value(frappe.defaults.get_user_default("Company"))).then(() => {
			this.loaded = true;
			this.load();
		});
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => {
			if (event.target.classList.contains("fh-status")) {
				this.status = event.target.value;
				this.render();
			}
			if (event.target.classList.contains("fh-usage")) {
				this.usage = event.target.value;
				this.render();
			}
		});
		root.addEventListener("input", (event) => {
			if (!event.target.classList.contains("fh-search")) {
				return;
			}
			clearTimeout(this.timer);
			this.timer = setTimeout(() => {
				this.search = event.target.value || "";
				this.render();
			}, 200);
		});
	}

	control(selector, df) {
		return frappe.ui.form.make_control({
			parent: this.page.main.find(selector),
			df,
			render_input: true,
		});
	}

	async load() {
		this.state = await frappehero.call("frappehero.finance_desk.cheque.list_cheque_leaves", {
			company: this.companyControl.get_value() || "",
			bank_account: this.bankControl.get_value() || "",
			status: "all",
			usage: "all",
			text: "",
		});
		this.render();
	}

	rows() {
		const query = (this.search || "").toLowerCase();
		return ((this.state && this.state.leaves) || []).filter((row) => {
			if (this.status !== "all" && row.status !== this.status) {
				return false;
			}
			if (this.usage !== "all" && row.usage !== this.usage) {
				return false;
			}
			if (!query) {
				return true;
			}
			return `${row.name} ${row.bank_account || ""} ${row.bank || ""} ${row.company || ""}`
				.toLowerCase()
				.includes(query);
		});
	}

	render() {
		const rows = this.rows();
		const totals = rows.reduce(
			(sum, row) => {
				sum.leaves += 1;
				sum.available += row.available || 0;
				sum.assigned += row.assigned || 0;
				sum.used += row.used || 0;
				sum.cancelled += row.cancelled || 0;
				return sum;
			},
			{ leaves: 0, available: 0, assigned: 0, used: 0, cancelled: 0 }
		);
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${totals.leaves}</b><span>${__("Leaves")}</span></div>
			<div class="fh-stat"><b>${totals.available}</b><span>${__("Available")}</span></div>
			<div class="fh-stat"><b>${totals.assigned}</b><span>${__("Assigned")}</span></div>
			<div class="fh-stat"><b>${totals.used}</b><span>${__("Used")}</span></div>
			<div class="fh-stat"><b>${totals.cancelled}</b><span>${__("Cancelled")}</span></div>
		`);
		const body = rows
			.map(
				(row) => `<tr>
				<td><button type="button" class="fh-btn-quiet" data-action="open" data-name="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</button></td>
				<td>${frappehero.esc(row.bank_account || "")}<div class="fh-muted">${frappehero.esc(row.company || "")}</div></td>
				<td>${frappehero.esc(row.status)} ${row.is_default ? `<span class="fh-muted">${__("Default")}</span>` : ""}</td>
				<td>${row.available || 0}</td>
				<td>${row.assigned || 0}</td>
				<td>${row.used || 0}</td>
				<td>${row.cancelled || 0}</td>
			</tr>`
			)
			.join("");
		this.page.main.find(".fh-matrix-wrap").html(
			`<table class="fh-matrix"><thead><tr><th>${__("Leaf")}</th><th>${__("Bank Account")}</th><th>${__("Status")}</th><th>${__("Available")}</th><th>${__("Assigned")}</th><th>${__("Used")}</th><th>${__("Cancelled")}</th></tr></thead><tbody>${body || `<tr><td>${__("No cheque leaves match.")}</td></tr>`}</tbody></table>`
		);
	}

	onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "load") {
			this.load();
		} else if (button.dataset.action === "open") {
			frappe.set_route("Form", "Hero Cheque Leaf", button.dataset.name);
		} else if (button.dataset.action === "new") {
			frappe.new_doc("Hero Cheque Leaf", {
				company: this.companyControl.get_value() || "",
				bank_account: this.bankControl.get_value() || "",
			});
		}
	}
};
