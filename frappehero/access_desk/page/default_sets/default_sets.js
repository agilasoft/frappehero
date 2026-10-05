// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["default-sets"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Default Value Sets"),
		single_column: true,
	});
	wrapper.defaults = new frappehero.DefaultSets(page);
};

frappe.pages["default-sets"].on_page_show = function (wrapper) {
	if (wrapper.defaults) {
		wrapper.defaults.refresh();
	}
};

frappehero.DefaultSets = class DefaultSets {
	constructor(page) {
		this.page = page;
		this.sets = [];
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("New Set"), () => this.createSet(), "add");
		this.page.main.html(`<div class="fh-app"><div class="fh-body"><aside class="fh-list"></aside><section class="fh-detail"></section></div></div>`);
		this.listEl = this.page.main.find(".fh-list");
		this.detailEl = this.page.main.find(".fh-detail");
		this.page.main.find(".fh-app").get(0).addEventListener("click", (event) => this.onClick(event));
		this.refresh();
	}

	async refresh() {
		this.sets = await frappehero.call("frappehero.access_desk.api.list_default_sets");
		const names = (this.sets || []).map((row) => row.name);
		if (!names.includes(this.selected)) {
			this.selected = names[0] || null;
		}
		this.render();
	}

	current() {
		return (this.sets || []).find((row) => row.name === this.selected) || null;
	}

	render() {
		this.listEl.html(
			(this.sets || [])
				.map(
					(row) => `
					<button type="button" class="fh-card ${row.name === this.selected ? "fh-selected" : ""}" data-action="open" data-name="${frappehero.esc(row.name)}">
						<span class="fh-card-text"><strong>${frappehero.esc(row.name)}</strong><span class="fh-muted">${frappehero.esc(row.permission_group || "")}</span></span>
						<span class="fh-pill ${row.conflict_count ? "fh-pill-attention" : ""}">${row.conflict_count || 0}</span>
					</button>`
				)
				.join("") || `<div class="fh-empty">${__("No default sets yet.")}</div>`
		);
		const set = this.current();
		if (!set) {
			this.detailEl.html(`<div class="fh-empty">${__("A set gives every member of a permission group the same defaults.")}</div>`);
			return;
		}
		const values = (set.values || [])
			.map(
				(row, index) => `
				<div class="fh-rule">
					<span>${frappehero.esc(row.default_key)} · ${frappehero.esc(row.default_value)}</span>
					<button type="button" class="fh-btn-danger" data-action="remove" data-index="${index}">${__("Remove")}</button>
				</div>`
			)
			.join("");
		const conflicts = (set.conflicts || [])
			.filter((row) => row.conflict)
			.map(
				(row) =>
					`<tr class="fh-bad"><td>${frappehero.esc(row.user)}</td><td>${frappehero.esc(row.key)}</td><td>${frappehero.esc(row.current)}</td><td>${frappehero.esc(row.wanted)}</td></tr>`
			)
			.join("");
		this.detailEl.html(`
			<div class="fh-detail-head">
				<div><h2>${frappehero.esc(set.name)}</h2><div class="fh-muted">${frappehero.esc(set.permission_group || "")}</div></div>
				<div class="fh-actions">
					<button type="button" class="fh-btn" data-action="add">${__("Add default")}</button>
					<button type="button" class="fh-btn" data-action="apply">${__("Apply to members")}</button>
				</div>
			</div>
			${values || `<div class="fh-empty">${__("No defaults yet.")}</div>`}
			<h3>${__("Disagreeing defaults")}</h3>
			<p class="fh-muted">${__("An empty default is not a conflict. A different value is.")}</p>
			<table class="fh-matrix"><thead><tr><th>${__("User")}</th><th>${__("DocType")}</th><th>${__("Current")}</th><th>${__("Set")}</th></tr></thead><tbody>${conflicts || `<tr><td class="fh-ok">${__("No conflicts")}</td></tr>`}</tbody></table>
		`);
	}

	onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "open") {
			this.selected = button.dataset.name;
			this.render();
		}
		if (button.dataset.action === "add") {
			this.addValue();
		}
		if (button.dataset.action === "remove") {
			this.removeValue(Number(button.dataset.index));
		}
		if (button.dataset.action === "apply") {
			this.apply();
		}
	}

	createSet() {
		frappe.prompt(
			[
				{ fieldname: "set_name", fieldtype: "Data", label: __("Set Name"), reqd: 1 },
				{ fieldname: "permission_group", fieldtype: "Link", options: "Hero Permission Group", label: __("Permission Group"), reqd: 1 },
			],
			async (values) => {
				const saved = await frappehero.call("frappehero.access_desk.api.save_default_set", {
					set_name: values.set_name,
					permission_group: values.permission_group,
					values: [],
					enabled: 1,
				});
				this.selected = saved.name;
				this.refresh();
			},
			__("New Default Set"),
			__("Create")
		);
	}

	addValue() {
		const set = this.current();
		if (!set) {
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Add default"),
			fields: [
				{ fieldname: "default_key", fieldtype: "Link", options: "DocType", label: __("DocType"), reqd: 1 },
				{
					fieldname: "default_value",
					fieldtype: "Dynamic Link",
					options: "default_key",
					label: __("Value"),
					reqd: 1,
					ignore_user_permissions: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				const next = (set.values || []).concat([values]);
				await this.save(set, next);
				dialog.hide();
			},
		});
		dialog.show();
	}

	async removeValue(index) {
		const set = this.current();
		if (!set) {
			return;
		}
		const next = (set.values || []).filter((_, item) => item !== index);
		await this.save(set, next);
	}

	async save(set, values) {
		const saved = await frappehero.call("frappehero.access_desk.api.save_default_set", {
			set_name: set.name,
			permission_group: set.permission_group,
			values,
			enabled: set.enabled,
		});
		this.selected = saved.name;
		await this.refresh();
	}

	async apply() {
		if (!this.selected) {
			return;
		}
		const result = await frappehero.call("frappehero.access_desk.api.apply_default_set", { name: this.selected });
		frappe.show_alert({ message: __("Applied {0} defaults", [String(result.applied || 0)]), indicator: "green" });
		this.refresh();
	}
};
