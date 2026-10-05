// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["share-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Share Desk"),
		single_column: true,
	});
	wrapper.shareDesk = new frappehero.ShareDesk(page);
};

frappehero.ShareDesk = class ShareDesk {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-filters">
					<div class="fh-doctype"></div>
					<div class="fh-document"></div>
					<button type="button" class="fh-btn" data-action="inspect">${__("Show access")}</button>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-thirds">
					<div class="fh-detail fh-roles"></div>
					<div class="fh-detail fh-perms"></div>
					<div class="fh-detail fh-shares"></div>
				</div>
				<div class="fh-coverage">
					<div class="fh-inline">
						<div class="fh-group"></div>
						<label>${__("Expires")}<input type="date" class="fh-expires"></label>
						<label class="fh-check"><input type="checkbox" class="fh-write"> ${__("Write")}</label>
						<label class="fh-check"><input type="checkbox" class="fh-submit"> ${__("Submit")}</label>
						<button type="button" class="fh-btn" data-action="share">${__("Share with group")}</button>
					</div>
				</div>
			</div>
		`);
		this.doctypeControl = this.control(".fh-doctype", {
			fieldtype: "Link",
			fieldname: "share_doctype",
			options: "DocType",
			label: __("DocType"),
		});
		this.doctypeControl.$input.on("change", () => this.mountDocument());
		this.doctypeControl.df.onchange = () => this.mountDocument();
		this.groupControl = this.control(".fh-group", {
			fieldtype: "Link",
			fieldname: "permission_group",
			options: "Hero Permission Group",
			label: __("Permission Group"),
		});
		this.mountDocument();
		this.page.main.find(".fh-app").get(0).addEventListener("click", (event) => this.onClick(event));
	}

	control(selector, df) {
		const control = frappe.ui.form.make_control({ parent: this.page.main.find(selector), df, render_input: true });
		return control;
	}

	mountDocument() {
		const parent = this.page.main.find(".fh-document");
		parent.empty();
		const options = this.doctypeControl.get_value();
		if (!options) {
			this.documentControl = null;
			return;
		}
		this.documentControl = this.control(".fh-document", {
			fieldtype: "Link",
			fieldname: "share_name",
			options,
			label: __("Document"),
			ignore_user_permissions: 1,
		});
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		const doctype = this.doctypeControl.get_value();
		const docname = this.documentControl ? this.documentControl.get_value() : "";
		if (!doctype || !docname) {
			frappe.msgprint(__("Choose a document."));
			return;
		}
		if (button.dataset.action === "inspect") {
			this.state = await frappehero.call("frappehero.access_desk.api.inspect_document", { doctype, docname });
			this.render();
		}
		if (button.dataset.action === "share") {
			const group = this.groupControl.get_value();
			if (!group) {
				frappe.msgprint(__("Choose a permission group."));
				return;
			}
			const result = await frappehero.call("frappehero.access_desk.api.share_with_group", {
				doctype,
				docname,
				permission_group: group,
				expires_on: this.page.main.find(".fh-expires").val() || null,
				read: 1,
				write: this.page.main.find(".fh-write").prop("checked") ? 1 : 0,
				submit: this.page.main.find(".fh-submit").prop("checked") ? 1 : 0,
			});
			frappe.show_alert({
				message: __("Shared with {0}. {1} already had it.", [String((result.created || []).length), String((result.already || []).length)]),
				indicator: "green",
			});
			this.state = await frappehero.call("frappehero.access_desk.api.inspect_document", { doctype, docname });
			this.render();
		}
	}

	render() {
		const state = this.state || { roles: [], user_permissions: [], shares: [] };
		this.page.main.find(".fh-stats").html(`
			<div class="fh-stat"><b>${state.roles.length}</b><span>${__("Roles with read")}</span></div>
			<div class="fh-stat"><b>${state.user_permissions.length}</b><span>${__("User Permissions")}</span></div>
			<div class="fh-stat"><b>${state.shares.length}</b><span>${__("Shares")}</span></div>
		`);
		const roles = state.roles
			.map((row) => `<div class="fh-rule"><span>${frappehero.esc(row.role)}</span><span class="fh-muted">${row.if_owner ? __("If owner") : __("Read")}</span></div>`)
			.join("");
		const perms = state.user_permissions
			.map((row) => `<div class="fh-rule"><span>${frappehero.esc(row.user)}</span><span class="fh-muted">${frappehero.esc(row.allow)} ${frappehero.esc(row.for_value)}</span></div>`)
			.join("");
		const shares = state.shares
			.map(
				(row) =>
					`<div class="fh-rule"><span>${frappehero.esc(row.user || __("Everyone"))}</span><span class="fh-muted">${frappehero.esc(row.hero_expires_on || __("No end date"))}</span></div>`
			)
			.join("");
		this.page.main.find(".fh-roles").html(`<h3>${__("Roles")}</h3>${roles || `<div class="fh-empty">${__("No role can read this.")}</div>`}`);
		this.page.main.find(".fh-perms").html(`<h3>${__("User Permissions")}</h3>${perms || `<div class="fh-empty">${__("No user permission names this record.")}</div>`}`);
		this.page.main.find(".fh-shares").html(`<h3>${__("Shares")}</h3>${shares || `<div class="fh-empty">${__("Not shared.")}</div>`}`);
	}
};
