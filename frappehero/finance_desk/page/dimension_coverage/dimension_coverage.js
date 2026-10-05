// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["dimension-coverage"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Dimension Coverage"),
		single_column: true,
	});
	wrapper.coverage = new frappehero.DimensionCoverage(page);
};

frappehero.DimensionCoverage = class DimensionCoverage {
	constructor(page) {
		this.page = page;
		this.dimension = "Cost Center";
		this.status = "all";
		this.search = "";
		this.state = null;
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-filters">
					<div class="fh-company"></div>
					<select class="fh-dimension">
						<option value="Cost Center">${__("Cost Center")}</option>
						<option value="Project">${__("Project")}</option>
						<option value="Branch">${__("Branch")}</option>
					</select>
					<select class="fh-status">
						<option value="all">${__("All statuses")}</option>
						<option value="missing">${__("Missing")}</option>
						<option value="partial">${__("Partial")}</option>
						<option value="complete">${__("Complete")}</option>
						<option value="empty">${__("No entries")}</option>
					</select>
					<input type="search" class="fh-search" placeholder="${__("Search accounts")}">
					<button type="button" class="fh-btn" data-action="load">${__("Show coverage")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-banner" hidden></div>
				<div class="fh-matrix-wrap"></div>
			</div>
		`);
		this.companyControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-company"),
			df: { fieldtype: "Link", fieldname: "company", options: "Company", label: __("Company") },
			render_input: true,
		});
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => {
			if (event.target.classList.contains("fh-dimension")) {
				this.dimension = event.target.value;
			}
			if (event.target.classList.contains("fh-status")) {
				this.status = event.target.value;
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

	async load() {
		const company = this.companyControl.get_value();
		if (!company) {
			frappe.msgprint(__("Choose a company."));
			return;
		}
		this.state = await frappehero.call("frappehero.finance_desk.api.get_dimension_coverage", {
			company,
			dimension: this.dimension,
			status: "all",
		});
		this.render();
	}

	rows() {
		const query = (this.search || "").toLowerCase();
		return ((this.state && this.state.rows) || []).filter((row) => {
			if (this.status !== "all" && row.status !== this.status) {
				return false;
			}
			if (!query) {
				return true;
			}
			return `${row.account} ${row.account_name || ""} ${row.account_number || ""}`.toLowerCase().includes(query);
		});
	}

	render() {
		const banner = this.page.main.find(".fh-banner");
		if (this.state && this.state.supported === false) {
			banner.removeAttr("hidden").text(__("This site has no {0} field on GL Entry.", [this.dimension]));
		} else {
			banner.attr("hidden", "hidden").text("");
		}
		const overall = (this.state && this.state.overall) || { total: 0, missing: 0, percent: 0, status: "empty" };
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${overall.percent || 0}%</b><span>${__("Filled")}</span></div>
			<div class="fh-stat"><b>${overall.missing || 0}</b><span>${__("Entries missing {0}", [this.dimension])}</span></div>
			<div class="fh-stat"><b>${overall.total || 0}</b><span>${__("GL entries")}</span></div>
			<div class="fh-stat"><b>${frappehero.esc(overall.status)}</b><span>${__("Overall")}</span></div>
		`);
		const body = this.rows()
			.map((row) => {
				const preset = row.default || {};
				return `<tr>
					<td>${frappehero.esc(row.account_name || row.account)}<div class="fh-muted">${frappehero.esc(row.account_number || row.account)}</div></td>
					<td><span class="fh-pill">${frappehero.esc(row.status)}</span> ${row.missing || 0}/${row.total || 0}</td>
					<td>${frappehero.esc(preset.default_value || "")}</td>
					<td class="fh-actions">
						<button type="button" class="fh-btn" data-action="set" data-account="${frappehero.esc(row.account)}">${__("Set default")}</button>
						${preset.name ? `<button type="button" class="fh-btn-quiet" data-action="clear" data-name="${frappehero.esc(preset.name)}">${__("Clear")}</button>` : ""}
					</td>
				</tr>`;
			})
			.join("");
		this.page.main.find(".fh-matrix-wrap").html(
			`<table class="fh-matrix"><thead><tr><th>${__("Account")}</th><th>${__("Coverage")}</th><th>${__("Default")}</th><th></th></tr></thead><tbody>${body || `<tr><td>${__("No accounts match.")}</td></tr>`}</tbody></table>`
		);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "load") {
			await this.load();
		}
		if (button.dataset.action === "clear") {
			await frappehero.call("frappehero.finance_desk.api.clear_dimension_default", { name: button.dataset.name });
			await this.load();
		}
		if (button.dataset.action === "set") {
			this.setDefault(button.dataset.account);
		}
	}

	setDefault(account) {
		const company = this.companyControl.get_value();
		const dimension = this.dimension;
		frappe.prompt(
			[
				{
					fieldname: "default_value",
					fieldtype: "Link",
					options: dimension,
					label: dimension,
					reqd: 1,
					ignore_user_permissions: 1,
					get_query: () => {
						const filters = { company };
						if (dimension === "Cost Center") {
							filters.is_group = 0;
						}
						return { filters };
					},
				},
				{ fieldname: "apply_on_new_entries", fieldtype: "Check", label: __("Apply when a new GL Entry leaves this empty") },
			],
			async (values) => {
				await frappehero.call("frappehero.finance_desk.api.set_dimension_default", {
					company,
					dimension,
					account,
					default_value: values.default_value,
					apply_on_new_entries: values.apply_on_new_entries,
				});
				this.load();
			},
			__("Default for {0}", [account]),
			__("Save")
		);
	}
};
