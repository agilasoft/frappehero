// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["module-ideas"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Next Modules"),
		single_column: true,
	});
	wrapper.ideas = new frappehero.ModuleIdeas(page);
};

frappe.pages["module-ideas"].on_page_show = function (wrapper) {
	if (wrapper.ideas) {
		wrapper.ideas.show();
	}
};

frappehero.ModuleIdeas = class ModuleIdeas {
	constructor(page) {
		this.page = page;
		this.area = "All";
		this.text = "";
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app">
				<p class="fh-muted">${__(
					"Open a module. Search covers the same descriptions as the workspace cards."
				)}</p>
				<div class="fh-filters">
					<input type="search" class="fh-search" placeholder="${__("Search ideas")}">
					<select class="fh-area">
						<option value="All">${__("All")}</option>
						<option value="Permissions">${__("Permissions")}</option>
						<option value="Accounts">${__("Accounts")}</option>
						<option value="Both">${__("Both")}</option>
					</select>
				</div>
				<div class="fh-ideas"></div>
			</div>
		`);
		this.listEl = this.page.main.find(".fh-ideas");
		this.listEl.on("click", "[data-route]", (event) => {
			const route = event.currentTarget.getAttribute("data-route");
			if (route) {
				frappe.set_route(route);
			}
		});
		this.page.main.find(".fh-search").on("input", (event) => {
			clearTimeout(this.timer);
			this.timer = setTimeout(() => {
				this.text = event.target.value || "";
				this.refresh();
			}, 200);
		});
		this.page.main.find(".fh-area").on("change", (event) => {
			this.area = event.target.value;
			this.refresh();
		});
	}

	show() {
		this.refresh();
	}

	async refresh() {
		const ideas = await frappehero.call("frappehero.api.get_module_ideas", {
			area: this.area,
			text: this.text,
		});
		this.listEl.html(
			(ideas || [])
				.map(
					(idea) => `
					<article class="fh-idea">
						<span class="fh-pill">${frappehero.esc(idea.area)}</span>
						<h3>${frappehero.esc(idea.name)}</h3>
						<p><strong>${frappehero.esc(idea.summary)}</strong></p>
						<p>${frappehero.esc(idea.problem)}</p>
						<p>${frappehero.esc(idea.shape)}</p>
						<p class="fh-muted">${frappehero.esc(idea.builds_on)}</p>
						${
							idea.route
								? `<div class="fh-actions"><button type="button" class="fh-btn" data-route="${frappehero.esc(idea.route)}">${__("Open")}</button></div>`
								: ""
						}
					</article>`
				)
				.join("") || `<div class="fh-empty">${__("No ideas match.")}</div>`
		);
	}
};
