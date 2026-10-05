// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["access-review"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Access Review"),
		single_column: true,
	});
	wrapper.review = new frappehero.AccessReview(page);
};

frappe.pages["access-review"].on_page_show = function (wrapper) {
	if (wrapper.review) {
		wrapper.review.refresh();
	}
};

frappehero.AccessReview = class AccessReview {
	constructor(page) {
		this.page = page;
		this.reviews = [];
		this.current = null;
		this.manual = [];
		this.manualQuery = "";
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("New Review"), () => this.createReview(), "add");
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-body">
					<aside class="fh-list"></aside>
					<section class="fh-detail"></section>
				</div>
			</div>
		`);
		this.listEl = this.page.main.find(".fh-list");
		this.detailEl = this.page.main.find(".fh-detail");
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("input", (event) => this.onInput(event));
		this.refresh();
	}

	async refresh() {
		this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
		const names = (this.reviews || []).map((row) => row.name);
		if (!names.includes(this.selected)) {
			this.selected = names[0] || null;
		}
		this.manual = await frappehero.call("frappehero.access_desk.api.manual_permissions", { search: this.manualQuery });
		if (this.selected) {
			this.current = await frappehero.call("frappehero.access_desk.api.refresh_review", { name: this.selected });
			this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
		} else {
			this.current = null;
		}
		this.render();
	}

	render() {
		this.listEl.html(
			(this.reviews || [])
				.map(
					(row) => `
					<button type="button" class="fh-card ${row.name === this.selected ? "fh-selected" : ""}" data-action="open" data-name="${frappehero.esc(row.name)}">
						<span class="fh-card-text">
							<strong>${frappehero.esc(row.name)}</strong>
							<span class="fh-muted">${frappehero.esc(row.review_date || "")} · ${__("Pending {0}", [String(row.pending || 0)])} · ${__("Stale {0}", [String(row.stale || 0)])}</span>
						</span>
						<span class="fh-pill">${frappehero.esc(row.status)}</span>
					</button>`
				)
				.join("") || `<div class="fh-empty">${__("No reviews yet.")}</div>`
		);
		if (!this.current) {
			this.detailEl.html(`<div class="fh-empty">${__("Create a review to confirm each permission group.")}</div>`);
			return;
		}
		const review = this.current;
		const lines = (review.lines || [])
			.map((line) => {
				const members = (line.members || []).map((row) => frappehero.esc(row.full_name || row.user)).join(", ");
				const rules = (line.rules || [])
					.map((row) => `${frappehero.esc(row.reference_doctype)}: ${frappehero.esc(row.for_value)}`)
					.join(", ");
				return `
					<article class="fh-rule">
						<div>
							<strong>${frappehero.esc(line.permission_group)}</strong>
							<div class="fh-muted">${__("Members")}: ${members || __("None")} · ${__("Values")}: ${rules || __("None")}</div>
							<div class="fh-muted">${frappehero.esc(line.reviewer || "")} ${frappehero.esc(line.confirmed_on || "")}</div>
						</div>
						<div class="fh-actions">
							<span class="fh-pill">${frappehero.esc(line.status)}</span>
							<button type="button" class="fh-btn" data-action="status" data-line="${frappehero.esc(line.name)}" data-status="Confirmed">${__("Confirm")}</button>
							<button type="button" class="fh-btn-quiet" data-action="status" data-line="${frappehero.esc(line.name)}" data-status="Exception">${__("Exception")}</button>
						</div>
					</article>`;
			})
			.join("");
		const manual = (this.manual || [])
			.slice(0, 40)
			.map(
				(row) =>
					`<tr><td>${frappehero.esc(row.user)}</td><td>${frappehero.esc(row.allow)}</td><td>${frappehero.esc(row.for_value)}</td><td>${frappehero.esc(row.applicable_for || __("All"))}</td></tr>`
			)
			.join("");
		this.detailEl.html(`
			<div class="fh-detail-head">
				<div>
					<h2>${frappehero.esc(review.review_name)}</h2>
					<div class="fh-muted">${frappehero.esc(review.review_date || "")}</div>
				</div>
				<div class="fh-actions">
					<button type="button" class="fh-btn" data-action="refresh">${__("Refresh")}</button>
					<button type="button" class="fh-btn-quiet" data-action="close">${review.status === "Open" ? __("Close") : __("Reopen")}</button>
				</div>
			</div>
			${lines || `<div class="fh-empty">${__("No enabled permission groups.")}</div>`}
			<h3>${__("Manual User Permissions")}</h3>
			<p class="fh-muted">${__("These rows were not created by a permission group.")}</p>
			<input type="search" class="fh-local-search" placeholder="${__("Search user or value")}" value="${frappehero.esc(this.manualQuery)}">
			<table class="fh-matrix"><thead><tr><th>${__("User")}</th><th>${__("DocType")}</th><th>${__("Value")}</th><th>${__("Applicable For")}</th></tr></thead><tbody>${manual || `<tr><td>${__("None")}</td></tr>`}</tbody></table>
		`);
	}

	onInput(event) {
		if (!event.target.classList.contains("fh-local-search")) {
			return;
		}
		clearTimeout(this.timer);
		this.timer = setTimeout(() => {
			this.manualQuery = event.target.value || "";
			this.refresh();
		}, 250);
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "open") {
			this.selected = button.dataset.name;
			this.current = await frappehero.call("frappehero.access_desk.api.get_review", { name: this.selected });
			this.render();
		}
		if (button.dataset.action === "refresh" && this.selected) {
			this.current = await frappehero.call("frappehero.access_desk.api.refresh_review", { name: this.selected });
			this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
			this.render();
		}
		if (button.dataset.action === "close" && this.current) {
			const status = this.current.status === "Open" ? "Closed" : "Open";
			this.current = await frappehero.call("frappehero.access_desk.api.set_review_status", { name: this.current.name, status });
			this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
			this.render();
		}
		if (button.dataset.action === "status" && this.current) {
			this.current = await frappehero.call("frappehero.access_desk.api.set_line_status", {
				review: this.current.name,
				line_name: button.dataset.line,
				status: button.dataset.status,
			});
			this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
			this.render();
		}
	}

	createReview() {
		frappe.prompt(
			[
				{ fieldname: "review_name", fieldtype: "Data", label: __("Review Name"), reqd: 1 },
				{ fieldname: "review_date", fieldtype: "Date", label: __("Review Date"), default: frappe.datetime.get_today() },
			],
			async (values) => {
				this.current = await frappehero.call("frappehero.access_desk.api.create_review", values);
				this.selected = this.current.name;
				this.reviews = await frappehero.call("frappehero.access_desk.api.list_reviews");
				this.render();
			},
			__("New Review"),
			__("Create")
		);
	}
};
