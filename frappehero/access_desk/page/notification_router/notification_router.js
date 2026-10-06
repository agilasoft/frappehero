// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["notification-router"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Notification Router"),
		single_column: true,
	});
	wrapper.router = new frappehero.NotificationRouter(page);
};

frappe.pages["notification-router"].on_page_show = function (wrapper) {
	if (wrapper.router) {
		wrapper.router.refresh();
	}
};

frappehero.NotificationRouter = class NotificationRouter {
	constructor(page) {
		this.page = page;
		this.routes = [];
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-form">
					<label>${__("Route name")}<input type="text" class="fh-name"></label>
					<label>${__("Event")}
						<select class="fh-event">
							<option value="Unmapped Accounts">${__("Unmapped Accounts")}</option>
							<option value="Users Without a Group">${__("Users Without a Group")}</option>
							<option value="Open Access Reviews">${__("Open Access Reviews")}</option>
						</select>
					</label>
					<div class="fh-group"></div>
					<div class="fh-map"></div>
					<div class="fh-actions"><button type="button" class="fh-btn" data-action="save">${__("Save route")}</button></div>
				</div>
				<div class="fh-list"></div>
			</div>
		`);
		this.groupControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-group"),
			df: { fieldtype: "Link", fieldname: "permission_group", options: "Hero Permission Group", label: __("Permission Group"), reqd: 1 },
			render_input: true,
		});
		this.mapControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-map"),
			df: { fieldtype: "Link", fieldname: "account_map", options: "Hero Account Map", label: __("Account Map") },
			render_input: true,
		});
		this.listEl = this.page.main.find(".fh-list");
		this.page.main.find(".fh-event").on("change", () => this.toggleMap());
		this.page.main.find(".fh-app").get(0).addEventListener("click", (event) => this.onClick(event));
		this.toggleMap();
		this.refresh();
	}

	toggleMap() {
		const show = this.page.main.find(".fh-event").val() === "Unmapped Accounts";
		this.page.main.find(".fh-map").toggle(show);
	}

	async refresh() {
		this.routes = await frappehero.call("frappehero.access_desk.api.list_routes");
		this.listEl.html(
			(this.routes || [])
				.map(
					(row) => `
					<article class="fh-idea">
						<h3>${frappehero.esc(row.name)} <span class="fh-muted">${frappehero.esc(row.event)}</span></h3>
						<p>${frappehero.esc(row.permission_group)} · ${__("Recipients {0}", [String(row.recipients || 0)])}</p>
						<p class="fh-muted">${__("Last sent")} ${frappehero.esc(row.last_sent || __("never"))}${row.last_summary ? ` · ${frappehero.esc(row.last_summary)}` : ""}</p>
						<button type="button" class="fh-btn" data-action="send" data-name="${frappehero.esc(row.name)}">${__("Send Now")}</button>
					</article>`
				)
				.join("") || `<div class="fh-empty">${__("No routes yet.")}</div>`
		);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "save") {
			await frappehero.call("frappehero.access_desk.api.save_route", {
				route_name: this.page.main.find(".fh-name").val(),
				event: this.page.main.find(".fh-event").val(),
				permission_group: this.groupControl.get_value(),
				account_map: this.page.main.find(".fh-event").val() === "Unmapped Accounts" ? this.mapControl.get_value() : null,
				enabled: 1,
			});
			frappe.show_alert({ message: __("Route saved"), indicator: "green" });
			this.refresh();
		}
		if (button.dataset.action === "send") {
			const result = await frappehero.call("frappehero.access_desk.api.send_now", { route: button.dataset.name });
			frappe.msgprint(result.sent ? __("Sent.") : result.reason || __("Not sent."));
			this.refresh();
		}
	}
};
