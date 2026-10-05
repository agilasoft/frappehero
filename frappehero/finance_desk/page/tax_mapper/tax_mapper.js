// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["tax-mapper"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Tax Template Mapper"),
		single_column: true,
	});
	wrapper.taxMapper = new frappehero.TaxMapper(page);
};

frappehero.TaxMapper = class TaxMapper {
	constructor(page) {
		this.page = page;
		this.search = "";
		this.checked = new Set();
		this.state = { groups: [], items: [], templates: [] };
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-filters">
					<div class="fh-company"></div>
					<input type="search" class="fh-search" placeholder="${__("Search item groups and items")}">
					<button type="button" class="fh-btn" data-action="load">${__("Show gaps")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-coverage">
					<div class="fh-inline">
						<div class="fh-template"></div>
						<button type="button" class="fh-btn" data-action="assign">${__("Assign to selected groups")}</button>
					</div>
				</div>
				<div class="fh-split">
					<div class="fh-detail fh-groups"></div>
					<div class="fh-detail fh-items"></div>
				</div>
			</div>
		`);
		this.companyControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-company"),
			df: { fieldtype: "Link", fieldname: "company", options: "Company", label: __("Company") },
			render_input: true,
		});
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		this.templateControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-template"),
			df: {
				fieldtype: "Link",
				fieldname: "item_tax_template",
				options: "Item Tax Template",
				label: __("Item Tax Template"),
				ignore_user_permissions: 1,
				get_query: () => ({ filters: { company: this.companyControl.get_value() } }),
			},
			render_input: true,
		});
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => this.onChange(event));
		root.addEventListener("input", (event) => {
			if (!event.target.classList.contains("fh-search")) {
				return;
			}
			clearTimeout(this.timer);
			this.timer = setTimeout(() => {
				this.search = event.target.value || "";
				if (this.companyControl.get_value()) {
					this.load();
				}
			}, 250);
		});
	}

	async load() {
		const company = this.companyControl.get_value();
		if (!company) {
			frappe.msgprint(__("Choose a company."));
			return;
		}
		this.state = await frappehero.call("frappehero.finance_desk.api.get_tax_state", { company, search: this.search });
		this.render();
	}

	render() {
		const state = this.state || {};
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${state.mapped_groups || 0}</b><span>${__("Mapped groups")}</span></div>
			<div class="fh-stat"><b>${state.unmapped_groups || 0}</b><span>${__("Unmapped groups")}</span></div>
			<div class="fh-stat"><b>${(state.items || []).length}</b><span>${__("Items still without tax")}</span></div>
			<div class="fh-stat"><b>${(state.templates || []).length}</b><span>${__("Templates")}</span></div>
		`);
		const groups = (state.groups || [])
			.map((row) => {
				const note = row.inherited_from ? __("From {0}", [row.inherited_from]) : row.own_template || "";
				return `<div class="fh-pick">
					<label class="fh-check"><input type="checkbox" data-group="${frappehero.esc(row.name)}" ${this.checked.has(row.name) ? "checked" : ""}> <span><strong>${frappehero.esc(row.name)}</strong><div class="fh-muted">${frappehero.esc(row.status)} ${frappehero.esc(row.template || "")} ${frappehero.esc(note)}</div></span></label>
					${row.own_template ? `<button type="button" class="fh-btn-quiet" data-action="clear" data-group="${frappehero.esc(row.name)}">${__("Clear")}</button>` : ""}
				</div>`;
			})
			.join("");
		const items = (state.items || [])
			.map((row) => `<div class="fh-rule"><span>${frappehero.esc(row.item_name || row.name)}</span><span class="fh-muted">${frappehero.esc(row.item_group)}</span></div>`)
			.join("");
		this.page.main.find(".fh-groups").html(`<h3>${__("Item groups")}</h3>${groups || `<div class="fh-empty">${__("No groups match.")}</div>`}`);
		this.page.main.find(".fh-items").html(`<h3>${__("Items without a template")}</h3><p class="fh-muted">${__("An item is listed when neither it nor its item group has a template for this company.")}</p>${items || `<div class="fh-empty">${__("Every item inherits a template.")}</div>`}`);
	}

	onChange(event) {
		const group = event.target.getAttribute("data-group");
		if (!group || event.target.type !== "checkbox") {
			return;
		}
		if (event.target.checked) {
			this.checked.add(group);
		} else {
			this.checked.delete(group);
		}
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "load") {
			await this.load();
		}
		if (button.dataset.action === "assign") {
			const template = this.templateControl.get_value();
			if (!template || !this.checked.size) {
				frappe.msgprint(__("Choose a template and at least one item group."));
				return;
			}
			await frappehero.call("frappehero.finance_desk.api.assign_group_templates", {
				item_groups: Array.from(this.checked),
				item_tax_template: template,
			});
			this.checked.clear();
			await this.load();
		}
		if (button.dataset.action === "clear") {
			await frappehero.call("frappehero.finance_desk.api.clear_group_template", {
				item_group: button.dataset.group,
				company: this.companyControl.get_value(),
			});
			await this.load();
		}
	}
};
