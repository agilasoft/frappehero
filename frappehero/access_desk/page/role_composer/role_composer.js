// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["role-composer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Role Composer"),
		single_column: true,
	});
	wrapper.composer = new frappehero.RoleComposer(page);
};

frappe.pages["role-composer"].on_page_show = function (wrapper) {
	if (wrapper.composer) {
		wrapper.composer.refresh();
	}
};

frappehero.RoleComposer = class RoleComposer {
	constructor(page) {
		this.page = page;
		this.filters = { search: "", module: "", bit: "read", missing_read: 0 };
		this.state = { roles: [], rows: [], all_roles: [], modules: [], bits: [] };
		this.diffs = [];
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("Clone Role"), () => this.cloneRole(), "add");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-stats"></div>
				<div class="fh-filters">
					<input type="search" class="fh-search" placeholder="${__("Search DocTypes")}">
					<select class="fh-module"><option value="">${__("All modules")}</option></select>
					<select class="fh-bit"></select>
					<label class="fh-check"><input type="checkbox" class="fh-missing"> ${__("Nobody can read")}</label>
				</div>
				<div class="fh-matrix-wrap"></div>
				<div class="fh-coverage">
					<div class="fh-inline">
						<select class="fh-role-a"><option value="">${__("Role")}</option></select>
						<select class="fh-role-b"><option value="">${__("Role")}</option></select>
						<button type="button" class="fh-btn" data-action="diff">${__("Diff roles")}</button>
					</div>
					<div class="fh-diff"></div>
				</div>
			</div>
		`);
		this.statsEl = this.page.main.find(".fh-stats");
		this.matrixEl = this.page.main.find(".fh-matrix-wrap");
		this.diffEl = this.page.main.find(".fh-diff");
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => this.onChange(event));
		root.addEventListener("input", (event) => this.onInput(event));
		this.refresh();
	}

	async refresh() {
		this.page.main.addClass("fh-loading");
		try {
			this.state = await frappehero.call("frappehero.access_desk.api.get_role_matrix", { filters: this.filters });
			this.render();
		} finally {
			this.page.main.removeClass("fh-loading");
		}
	}

	render() {
		const rows = this.state.rows || [];
		const missing = rows.filter((row) => row.nobody_read).length;
		this.statsEl.html(`
			<div class="fh-stat"><b>${rows.length}</b><span>${__("DocTypes")}</span></div>
			<div class="fh-stat"><b>${(this.state.roles || []).length}</b><span>${__("Roles in view")}</span></div>
			<div class="fh-stat"><b>${missing}</b><span>${__("Nobody can read")}</span></div>
			<div class="fh-stat"><b>${frappehero.esc(this.filters.bit)}</b><span>${__("Permission shown")}</span></div>
		`);
		this.fillSelect(this.page.main.find(".fh-module"), this.state.modules || [], this.filters.module, __("All modules"));
		const bits = this.state.bits && this.state.bits.length ? this.state.bits : ["read"];
		this.fillSelect(this.page.main.find(".fh-bit"), bits, this.filters.bit, "");
		this.fillSelect(this.page.main.find(".fh-role-a"), this.state.all_roles || [], this.page.main.find(".fh-role-a").val(), __("Role"));
		this.fillSelect(this.page.main.find(".fh-role-b"), this.state.all_roles || [], this.page.main.find(".fh-role-b").val(), __("Role"));
		const bit = this.filters.bit || "read";
		const roles = this.state.roles || [];
		const head = roles.map((role) => `<th>${frappehero.esc(role)}</th>`).join("");
		const body = rows
			.map((row) => {
				const cells = roles
					.map((role) => {
						const on = ((row.cells || {})[role] || {})[bit] ? 1 : 0;
						return `<td><button type="button" class="fh-cell ${on ? "fh-on" : ""}" data-action="toggle" data-doctype="${frappehero.esc(row.doctype)}" data-role="${frappehero.esc(role)}" data-value="${on ? 0 : 1}">${on ? "✓" : ""}</button></td>`;
					})
					.join("");
				return `<tr class="${row.nobody_read ? "fh-bad" : ""}"><td>${frappehero.esc(row.doctype)}<div class="fh-muted">${frappehero.esc(row.module || "")}</div></td>${cells}</tr>`;
			})
			.join("");
		this.matrixEl.html(
			`<table class="fh-matrix"><thead><tr><th>${__("DocType")}</th>${head}</tr></thead><tbody>${body || `<tr><td>${__("Nothing matches these filters.")}</td></tr>`}</tbody></table>`
		);
		this.renderDiff();
	}

	renderDiff() {
		if (!this.diffs.length) {
			this.diffEl.html(`<p class="fh-muted">${__("Pick two roles to see bits that differ.")}</p>`);
			return;
		}
		const rows = this.diffs
			.map(
				(row) =>
					`<tr><td>${frappehero.esc(row.doctype)}</td><td>${frappehero.esc(row.bit)}</td><td>${row.left ? "✓" : ""}</td><td>${row.right ? "✓" : ""}</td></tr>`
			)
			.join("");
		this.diffEl.html(
			`<table class="fh-matrix"><thead><tr><th>${__("DocType")}</th><th>${__("Bit")}</th><th>${frappehero.esc(this.roleA || "")}</th><th>${frappehero.esc(this.roleB || "")}</th></tr></thead><tbody>${rows}</tbody></table>`
		);
	}

	fillSelect(element, values, current, placeholder) {
		const signature = `${placeholder}|${values.join("|")}`;
		if (element.attr("data-signature") !== signature) {
			element.attr("data-signature", signature);
			const options = placeholder ? [`<option value="">${frappehero.esc(placeholder)}</option>`] : [];
			values.forEach((value) => options.push(`<option value="${frappehero.esc(value)}">${frappehero.esc(value)}</option>`));
			element.html(options.join(""));
		}
		if (current) {
			element.val(current);
		}
	}

	onChange(event) {
		const target = event.target;
		if (target.classList.contains("fh-module")) {
			this.filters.module = target.value;
			this.refresh();
		} else if (target.classList.contains("fh-bit")) {
			this.filters.bit = target.value || "read";
			this.refresh();
		} else if (target.classList.contains("fh-missing")) {
			this.filters.missing_read = target.checked ? 1 : 0;
			this.refresh();
		}
	}

	onInput(event) {
		if (!event.target.classList.contains("fh-search")) {
			return;
		}
		clearTimeout(this.timer);
		this.timer = setTimeout(() => {
			this.filters.search = event.target.value || "";
			this.refresh();
		}, 250);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "toggle") {
			await frappehero.call("frappehero.access_desk.api.toggle_permission", {
				document_type: button.dataset.doctype,
				role: button.dataset.role,
				bit: this.filters.bit,
				value: button.dataset.value,
			});
			this.refresh();
		}
		if (button.dataset.action === "diff") {
			this.roleA = this.page.main.find(".fh-role-a").val();
			this.roleB = this.page.main.find(".fh-role-b").val();
			if (!this.roleA || !this.roleB) {
				frappe.msgprint(__("Choose two roles."));
				return;
			}
			this.diffs = await frappehero.call("frappehero.access_desk.api.diff_two_roles", {
				role_a: this.roleA,
				role_b: this.roleB,
			});
			this.renderDiff();
		}
	}

	cloneRole() {
		const roles = this.state.all_roles || [];
		frappe.prompt(
			[
				{ fieldname: "source_role", fieldtype: "Select", label: __("Copy from"), options: roles.join("\n"), reqd: 1 },
				{ fieldname: "new_role", fieldtype: "Data", label: __("New role"), reqd: 1 },
			],
			async (values) => {
				const result = await frappehero.call("frappehero.access_desk.api.clone_role", values);
				frappe.show_alert({ message: __("Created {0}", [result.role]), indicator: "green" });
				this.refresh();
			},
			__("Clone Role"),
			__("Create")
		);
	}
};
