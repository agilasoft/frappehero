// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["bsp-rates"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("BSP Rates"),
		single_column: true,
	});
	wrapper.bspRates = new frappehero.BspRates(page);
};

frappe.pages["bsp-rates"].on_page_show = function (wrapper) {
	if (wrapper.bspRates) {
		wrapper.bspRates.refresh();
	}
};

frappehero.BspRates = class BspRates {
	constructor(page) {
		this.page = page;
		this.state = null;
		this.applied = false;
		this.datesReady = false;
		this.filter = "all";
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app fh-bsp">
				<p class="fh-bsp-lead">${__("Pesos per 1 unit of foreign currency. USD uses the BSP reference rate. A rate entered by hand stays as it is.")}</p>
				<div class="fh-bsp-bar">
					<div class="fh-enabled"></div>
					<div class="fh-inverse"></div>
					<div class="fh-lookback"></div>
					<button type="button" class="fh-bsp-link" data-action="save">${__("Save")}</button>
				</div>
				<div class="fh-bsp-bar">
					<div class="fh-from"></div>
					<div class="fh-to"></div>
					<div class="fh-bsp-actions">
						<button type="button" class="fh-bsp-link" data-action="preview">${__("Preview")}</button>
						<button type="button" class="fh-bsp-link" data-action="apply">${__("Apply")}</button>
					</div>
				</div>
				<div class="fh-bsp-summary">
					<div class="fh-stats"></div>
					<div class="fh-bsp-views"></div>
				</div>
				<p class="fh-bsp-note"></p>
				<div class="fh-rates fh-matrix-wrap"></div>
			</div>
		`);
		this.enabledControl = this.control(".fh-enabled", {
			fieldtype: "Check",
			fieldname: "enabled",
			label: __("Fetch on the daily job"),
		});
		this.inverseControl = this.control(".fh-inverse", {
			fieldtype: "Check",
			fieldname: "write_inverse",
			label: __("Write inverse"),
		});
		this.lookbackControl = this.control(".fh-lookback", {
			fieldtype: "Int",
			fieldname: "lookback_days",
			label: __("Lookback days"),
		});
		this.fromControl = this.control(".fh-from", {
			fieldtype: "Date",
			fieldname: "from_date",
			label: __("From"),
		});
		this.toControl = this.control(".fh-to", {
			fieldtype: "Date",
			fieldname: "to_date",
			label: __("To"),
		});
		this.page.main.find(".fh-app").get(0).addEventListener("click", (event) => this.onClick(event));
		this.refresh();
	}

	control(selector, df) {
		return frappe.ui.form.make_control({
			parent: this.page.main.find(selector),
			df,
			render_input: true,
		});
	}

	async refresh() {
		const settings = await frappehero.call("frappehero.finance_desk.api.get_bsp_settings");
		this.enabledControl.set_value(settings.enabled);
		this.inverseControl.set_value(settings.write_inverse);
		this.lookbackControl.set_value(settings.lookback_days);
		if (!this.datesReady) {
			const today = frappe.datetime.get_today();
			this.toControl.set_value(today);
			this.fromControl.set_value(frappe.datetime.add_days(today, -Number(settings.lookback_days || 5)));
			this.datesReady = true;
		}
	}

	onClick(event) {
		const action = event.target.closest("[data-action]");
		if (!action) {
			return;
		}
		if (action.dataset.action === "save") {
			this.save();
		} else if (action.dataset.action === "preview") {
			this.preview();
		} else if (action.dataset.action === "apply") {
			this.confirmApply();
		} else if (action.dataset.action === "filter") {
			this.filter = action.dataset.filter || "all";
			this.render();
		}
	}

	range() {
		const from_date = this.fromControl.get_value();
		const to_date = this.toControl.get_value();
		if (!from_date || !to_date) {
			frappe.msgprint(__("Choose a start and end date."));
			return null;
		}
		return { from_date, to_date };
	}

	async save() {
		this.setBusy(true);
		try {
			await frappehero.call("frappehero.finance_desk.api.save_bsp_settings", {
				enabled: this.enabledControl.get_value() ? 1 : 0,
				write_inverse: this.inverseControl.get_value() ? 1 : 0,
				lookback_days: this.lookbackControl.get_value(),
			});
			frappe.show_alert({ message: __("BSP settings saved."), indicator: "green" });
		} finally {
			this.setBusy(false);
		}
	}

	async preview() {
		const range = this.range();
		if (!range) {
			return;
		}
		this.setBusy(true);
		try {
			this.applied = false;
			this.state = await frappehero.call("frappehero.finance_desk.api.preview_bsp_rates", range);
			this.render();
		} finally {
			this.setBusy(false);
		}
	}

	confirmApply() {
		const range = this.range();
		if (!range) {
			return;
		}
		frappe.confirm(
			__("Write BSP rates into Currency Exchange for this range? A rate entered by hand stays as it is."),
			() => this.apply(range)
		);
	}

	async apply(range) {
		this.setBusy(true);
		try {
			this.state = await frappehero.call("frappehero.finance_desk.api.apply_bsp_rates", range);
			this.applied = true;
			this.render();
			frappe.show_alert({ message: __("BSP rates saved."), indicator: "green" });
		} finally {
			this.setBusy(false);
		}
	}

	setBusy(busy) {
		this.page.main.find(".fh-app").toggleClass("fh-loading", busy);
	}

	render() {
		const state = this.state;
		const stats = this.page.main.find(".fh-stats");
		const note = this.page.main.find(".fh-bsp-note");
		const views = this.page.main.find(".fh-bsp-views");
		const table = this.page.main.find(".fh-rates");
		if (!state) {
			stats.empty();
			views.empty();
			note.text(__("Preview a date range to see the rates."));
			table.empty();
			return;
		}
		const counts = state.counts || {};
		stats.html(`
			<div class="fh-stat"><b>${(state.listed || []).length}</b><span>${__("Bulletins")}</span></div>
			<div class="fh-stat"><b>${counts.create || 0}</b><span>${__("Create")}</span></div>
			<div class="fh-stat"><b>${counts.update || 0}</b><span>${__("Update")}</span></div>
			<div class="fh-stat"><b>${counts.skip || 0}</b><span>${__("Leave as is")}</span></div>
		`);
		views.html(
			[
				["all", __("All")],
				["write", __("To write")],
				["skip", __("Left as is")],
			]
				.map(
					([key, label]) =>
						`<button type="button" class="fh-bsp-tab ${this.filter === key ? "fh-on" : ""}" data-action="filter" data-filter="${key}">${label}</button>`
				)
				.join("")
		);
		const notes = [];
		if (this.applied) {
			notes.push(__("Saved {0} new rates and updated {1}.", [state.created || 0, state.updated || 0]));
		}
		if (!(state.listed || []).length) {
			notes.push(__("No bulletin was published in that range."));
		}
		if ((state.empty || []).length) {
			notes.push(__("No rates could be read for {0}.", [state.empty.join(", ")]));
		}
		if ((state.missing_currencies || []).length) {
			notes.push(__("Not enabled in ERPNext: {0}.", [state.missing_currencies.join(", ")]));
		}
		note.text(notes.join(" "));
		const rows = (state.rows || []).filter((row) => {
			if (this.filter === "write") {
				return row.action === "create" || row.action === "update";
			}
			if (this.filter === "skip") {
				return row.action === "skip";
			}
			return true;
		});
		if (!rows.length) {
			table.html(`<div class="fh-empty">${__("Nothing to show.")}</div>`);
			return;
		}
		const labels = { create: __("Create"), update: __("Update"), skip: __("Leave as is") };
		const body = rows
			.map(
				(row) => `
				<tr>
					<td>${frappehero.esc(row.date)}</td>
					<td>${frappehero.esc(row.from_currency)}</td>
					<td class="fh-bsp-arrow" aria-hidden="true">→</td>
					<td>${frappehero.esc(row.to_currency)}</td>
					<td class="fh-bsp-rate">${frappehero.esc(this.formatRate(row.exchange_rate))}</td>
					<td class="fh-bsp-action is-${frappehero.esc(row.action)}">${frappehero.esc(labels[row.action] || row.action)}</td>
					<td class="fh-muted">${frappehero.esc(row.reason)}</td>
				</tr>`
			)
			.join("");
		table.html(`
			<table class="fh-matrix">
				<thead>
					<tr>
						<th>${__("Date")}</th>
						<th>${__("From")}</th>
						<th></th>
						<th>${__("To")}</th>
						<th>${__("Rate")}</th>
						<th>${__("Action")}</th>
						<th>${__("Why")}</th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		`);
	}

	formatRate(value) {
		const number = Number(value);
		if (!Number.isFinite(number)) {
			return value == null ? "" : String(value);
		}
		return number.toLocaleString("en-US", { maximumFractionDigits: 9, useGrouping: false });
	}
};
