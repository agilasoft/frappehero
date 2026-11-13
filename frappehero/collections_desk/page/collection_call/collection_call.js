// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["collection-call"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Collection Call"),
		single_column: true,
	});
	wrapper.collection = new frappehero.CollectionCall(page);
};

frappe.pages["collection-call"].on_page_show = function (wrapper) {
	if (wrapper.collection) {
		wrapper.collection.show();
	}
};

frappehero.CollectionCall = class CollectionCall {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.summary = { customers: 0, amount_due: 0, promises_due: 0, calls_today: 0 };
		this.client = null;
		this.customer = "";
		this.callName = "";
		this.picked = new Set();
		this.draft = this.emptyDraft();
		this.filters = { text: "", overdue_only: 0, followups_only: 0, mine: 0 };
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app fh-call">
				<div class="fh-filters">
					<input type="search" class="fh-search" placeholder="${__("Search customer, group, outcome")}">
					<div class="fh-company"></div>
					<label class="fh-check"><input type="checkbox" class="fh-overdue"> ${__("Overdue")}</label>
					<label class="fh-check"><input type="checkbox" class="fh-follow"> ${__("Follow-ups due")}</label>
					<label class="fh-check"><input type="checkbox" class="fh-mine"> ${__("My calls")}</label>
				</div>
				<div class="fh-stats"></div>
				<div class="fh-call-grid">
					<aside class="fh-list"></aside>
					<section class="fh-detail fh-client"></section>
					<section class="fh-composer"></section>
				</div>
			</div>
		`);
		this.listEl = this.page.main.find(".fh-list");
		this.clientEl = this.page.main.find(".fh-client");
		this.composerEl = this.page.main.find(".fh-composer");
		this.statsEl = this.page.main.find(".fh-stats");
		this.companyControl = frappe.ui.form.make_control({
			parent: this.page.main.find(".fh-company"),
			df: {
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				onchange: () => {
					this.customer = "";
					this.client = null;
					this.callName = "";
					this.picked = new Set();
					this.draft = this.emptyDraft();
					this.renderClient();
					this.refresh();
				},
			},
			render_input: true,
		});
		this.companyControl.set_value(frappe.defaults.get_user_default("Company"));
		const root = this.page.main.find(".fh-call").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => this.onChange(event));
		root.addEventListener("input", (event) => this.onInput(event));
		this.refresh();
	}

	emptyDraft() {
		return {
			direction: "Outbound",
			phone: "",
			contact_person: "",
			outcome: "",
			notes: "",
			promise_amount: "",
			promise_date: "",
			next_follow_up: "",
			call_datetime: this.nowLocal(),
		};
	}

	nowLocal() {
		const raw = (frappe.datetime.now_datetime && frappe.datetime.now_datetime()) || "";
		return String(raw).replace(" ", "T").slice(0, 16);
	}

	show() {
		const options = frappe.route_options || {};
		frappe.route_options = null;
		if (options.customer) {
			this.pendingCustomer = options.customer;
		}
		if (options.company) {
			this.companyControl.set_value(options.company);
		}
		this.refresh();
	}

	company() {
		return this.companyControl.get_value() || "";
	}

	filterArgs() {
		return {
			company: this.company(),
			text: this.filters.text,
			overdue_only: this.filters.overdue_only,
			followups_only: this.filters.followups_only,
			mine: this.filters.mine,
		};
	}

	async refresh() {
		const request = (this.request = (this.request || 0) + 1);
		const result = await frappehero.call("frappehero.collections_desk.api.get_queue", this.filterArgs());
		if (request !== this.request) {
			return;
		}
		this.rows = (result && result.rows) || [];
		this.summary = (result && result.summary) || this.summary;
		this.renderQueue();
		if (this.pendingCustomer) {
			const customer = this.pendingCustomer;
			this.pendingCustomer = "";
			await this.openCustomer(customer);
		}
	}

	async openCustomer(customer) {
		if (!customer || (this.customer === customer && this.client)) {
			return;
		}
		this.customer = customer;
		this.callName = "";
		this.picked = new Set();
		this.draft = this.emptyDraft();
		this.client = null;
		this.renderClient();
		await this.loadClient();
	}

	async loadClient() {
		this.renderQueue();
		if (!this.customer || !this.company()) {
			this.client = null;
			this.renderClient();
			this.renderComposer();
			return;
		}
		const request = (this.clientRequest = (this.clientRequest || 0) + 1);
		const client = await frappehero.call("frappehero.collections_desk.api.get_client", {
			company: this.company(),
			customer: this.customer,
		});
		if (request !== this.clientRequest) {
			return;
		}
		this.client = client;
		if (!this.draft.phone) {
			this.draft.phone = client.phone || "";
		}
		this.renderClient();
		this.renderComposer();
	}

	renderQueue() {
		const summary = this.summary || {};
		this.statsEl.html(`
			<div class="fh-stat"><b>${summary.customers || 0}</b><span>${__("To call")}</span></div>
			<div class="fh-stat"><b>${this.money(summary.amount_due)}</b><span>${__("Amount due")}</span></div>
			<div class="fh-stat"><b>${summary.promises_due || 0}</b><span>${__("Promises due")}</span></div>
			<div class="fh-stat"><b>${summary.calls_today || 0}</b><span>${__("Calls today")}</span></div>
		`);
		this.listEl.html(
			(this.rows || [])
				.map((row) => {
					const meta = [this.money(row.outstanding), row.oldest_due || __("No invoice")].join(" · ");
					const follow = row.follow_up_due ? __("Follow up {0}", [row.next_follow_up]) : row.last_outcome || "";
					return `
					<button type="button" class="fh-card ${row.customer === this.customer ? "fh-selected" : ""}" data-action="open" data-customer="${frappehero.esc(row.customer)}">
						<span class="fh-card-text"><strong>${frappehero.esc(row.customer_name || row.customer)}</strong><span class="fh-muted">${frappehero.esc(meta)}</span></span>
						<span class="fh-pill">${frappehero.esc(follow)}</span>
					</button>`;
				})
				.join("") || `<div class="fh-empty">${__("No customers match these filters.")}</div>`
		);
	}

	renderClient() {
		const client = this.client;
		if (!client) {
			this.clientEl.html(
				`<div class="fh-empty">${__("Choose a customer. The file shows the balance, the invoices, and the earlier calls.")}</div>`
			);
			this.composerEl.html("");
			return;
		}
		const phone = client.tel
			? `<a class="fh-tel" href="${frappehero.esc(client.tel)}">${frappehero.esc(client.phone)}</a>`
			: frappehero.esc(client.phone || __("No phone"));
		const buckets = (client.aging && client.aging.buckets) || {};
		const bucketLine = ["Current", "1-30", "31-60", "61-90", "91 and over"]
			.map((name) => `<div class="fh-stat"><b>${this.money(buckets[name])}</b><span>${frappehero.esc(name)}</span></div>`)
			.join("");
		this.clientEl.html(`
			<div class="fh-detail-head">
				<div>
					<h2>${frappehero.esc(client.customer_name || client.customer)}</h2>
					<div class="fh-muted">${phone} · ${frappehero.esc(client.email || __("No email"))}${client.disabled ? " · " + __("Disabled") : ""}</div>
				</div>
			</div>
			<div class="fh-kv">
				<span class="fh-muted">${__("Group")}</span><span>${frappehero.esc(client.customer_group || "")}</span>
				<span class="fh-muted">${__("Territory")}</span><span>${frappehero.esc(client.territory || "")}</span>
				<span class="fh-muted">${__("Tax ID")}</span><span>${frappehero.esc(client.tax_id || "")}</span>
				<span class="fh-muted">${__("Credit limit")}</span><span>${client.credit_limit == null ? __("None") : this.money(client.credit_limit)}</span>
				<span class="fh-muted">${__("Outstanding")}</span><span>${this.money(client.outstanding)}</span>
				<span class="fh-muted">${__("Address")}</span><span>${frappehero.esc((client.address || []).join(", "))}</span>
			</div>
			<div class="fh-stats">${bucketLine}</div>
			<p class="fh-muted">${__("Amount still due {0}. Disputed {1}.", [this.money(client.aging && client.aging.amount_due), this.money(client.aging && client.aging.disputed_outstanding)])}</p>
			<h3 class="fh-section-label">${__("Open invoices")}</h3>
			${this.invoiceTable(client.invoices)}
			<h3 class="fh-section-label">${__("Receipts")}</h3>
			${this.paymentTable(client.payments)}
			<h3 class="fh-section-label">${__("Open disputes")}</h3>
			${this.disputeTable(client.disputes)}
			<h3 class="fh-section-label">${__("Earlier calls")}</h3>
			${this.callTable(client.calls)}
			<h3 class="fh-section-label">${__("Claims and incidents")}</h3>
			${this.reportTable(client.reports)}
		`);
	}

	invoiceTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><input type="checkbox" data-invoice="${frappehero.esc(row.sales_invoice)}" ${this.picked.has(row.sales_invoice) ? "checked" : ""}></td>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Sales Invoice" data-doc="${frappehero.esc(row.sales_invoice)}">${frappehero.esc(row.sales_invoice)}</button></td>
					<td>${frappehero.esc(row.due_date || "")}</td>
					<td class="fh-num">${this.money(row.outstanding)}</td>
					<td>${row.disputed ? __("Disputed") : ""}</td>
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th></th><th>${__("Invoice")}</th><th>${__("Due")}</th><th>${__("Outstanding")}</th><th></th></tr></thead><tbody>${body || `<tr><td colspan="5">${__("Nothing is outstanding.")}</td></tr>`}</tbody></table>`;
	}

	paymentTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Payment Entry" data-doc="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</button></td>
					<td>${frappehero.esc(row.posting_date || "")}</td>
					<td class="fh-num">${this.money(row.paid_amount)}</td>
					<td>${frappehero.esc(row.mode_of_payment || "")}</td>
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th>${__("Receipt")}</th><th>${__("Date")}</th><th>${__("Amount")}</th><th>${__("Mode")}</th></tr></thead><tbody>${body || `<tr><td colspan="4">${__("No receipts yet.")}</td></tr>`}</tbody></table>`;
	}

	disputeTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Hero Dispute" data-doc="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</button></td>
					<td>${frappehero.esc(row.sales_invoice || "")}</td>
					<td>${frappehero.esc(row.reason || "")}</td>
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th>${__("Dispute")}</th><th>${__("Invoice")}</th><th>${__("Reason")}</th></tr></thead><tbody>${body || `<tr><td colspan="3">${__("No open dispute.")}</td></tr>`}</tbody></table>`;
	}

	callTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Hero Collection Call" data-doc="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</button></td>
					<td>${frappehero.esc(row.outcome || "")}</td>
					<td>${frappehero.esc(row.call_time || "")}</td>
					<td>${frappehero.esc(row.notes || "")}</td>
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th>${__("Call")}</th><th>${__("Outcome")}</th><th>${__("Time")}</th><th>${__("Notes")}</th></tr></thead><tbody>${body || `<tr><td colspan="4">${__("No calls yet.")}</td></tr>`}</tbody></table>`;
	}

	reportTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Hero Collection Report" data-doc="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</button></td>
					<td>${frappehero.esc(row.report_type || "")}</td>
					<td>${frappehero.esc(row.status || "")}</td>
					<td>${frappehero.esc(row.summary || "")}</td>
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th>${__("Report")}</th><th>${__("Type")}</th><th>${__("Status")}</th><th>${__("Summary")}</th></tr></thead><tbody>${body || `<tr><td colspan="4">${__("No claim or incident.")}</td></tr>`}</tbody></table>`;
	}

	renderComposer() {
		if (!this.client) {
			this.composerEl.html("");
			return;
		}
		const draft = this.draft;
		const outcomes = ["Reached", "No Answer", "Busy", "Wrong Number", "Voicemail", "Promised", "Refused", "Disputed", "Callback"]
			.map((outcome) => `<option value="${outcome}" ${draft.outcome === outcome ? "selected" : ""}>${__(outcome)}</option>`)
			.join("");
		this.composerEl.html(`
			<h3 class="fh-section-label">${__("This call")}</h3>
			<p class="fh-muted">${this.callName ? __("Logging onto {0}.", [frappehero.esc(this.callName)]) : __("Save the call, then the actions below are stamped on it.")}</p>
			<label class="fh-field">${__("Direction")}
				<select class="fh-direction">
					<option value="Outbound" ${draft.direction === "Outbound" ? "selected" : ""}>${__("Outbound")}</option>
					<option value="Inbound" ${draft.direction === "Inbound" ? "selected" : ""}>${__("Inbound")}</option>
				</select>
			</label>
			<label class="fh-field">${__("Call time")}<input type="datetime-local" class="fh-call-time" value="${frappehero.esc(draft.call_datetime || "")}"></label>
			<label class="fh-field">${__("Phone")}<input type="text" class="fh-phone" value="${frappehero.esc(draft.phone || "")}"></label>
			<label class="fh-field">${__("Contact")}<input type="text" class="fh-contact" value="${frappehero.esc(draft.contact_person || "")}"></label>
			<label class="fh-field">${__("Outcome")}<select class="fh-outcome"><option value="">${__("Choose")}</option>${outcomes}</select></label>
			<label class="fh-field">${__("Notes")}<textarea class="fh-notes">${frappehero.esc(draft.notes || "")}</textarea></label>
			<label class="fh-field">${__("Promise amount")}<input type="text" class="fh-promise-amount" inputmode="decimal" value="${frappehero.esc(draft.promise_amount || "")}"></label>
			<label class="fh-field">${__("Promise date")}<input type="date" class="fh-promise-date" value="${frappehero.esc(draft.promise_date || "")}"></label>
			<label class="fh-field">${__("Next follow-up")}<input type="date" class="fh-follow-date" value="${frappehero.esc(draft.next_follow_up || "")}"></label>
			<div class="fh-call-actions">
				<button type="button" class="fh-btn" data-action="save">${__("Save call")}</button>
				<button type="button" class="fh-btn" data-action="soa">${__("Generate SOA")}</button>
				<button type="button" class="fh-btn" data-action="send">${__("Send SOA")}</button>
				<button type="button" class="fh-btn" data-action="report">${__("Claim or incident")}</button>
				<button type="button" class="fh-btn" data-action="payment">${__("Record payment")}</button>
				<button type="button" class="fh-btn" data-action="dispute">${__("Raise dispute")}</button>
			</div>
		`);
	}

	readDraft() {
		const root = this.composerEl;
		if (!root.find(".fh-direction").length) {
			return;
		}
		this.draft = {
			direction: root.find(".fh-direction").val() || "Outbound",
			phone: root.find(".fh-phone").val() || "",
			contact_person: root.find(".fh-contact").val() || "",
			outcome: root.find(".fh-outcome").val() || "",
			notes: root.find(".fh-notes").val() || "",
			promise_amount: root.find(".fh-promise-amount").val() || "",
			promise_date: root.find(".fh-promise-date").val() || "",
			next_follow_up: root.find(".fh-follow-date").val() || "",
			call_datetime: root.find(".fh-call-time").val() || "",
		};
	}

	onInput(event) {
		if (!event.target.classList.contains("fh-search")) {
			return;
		}
		clearTimeout(this.timer);
		this.timer = setTimeout(() => {
			this.filters.text = event.target.value || "";
			this.refresh();
		}, 200);
	}

	onChange(event) {
		const target = event.target;
		if (target.classList.contains("fh-overdue") || target.classList.contains("fh-follow") || target.classList.contains("fh-mine")) {
			this.filters.overdue_only = this.page.main.find(".fh-overdue").prop("checked") ? 1 : 0;
			this.filters.followups_only = this.page.main.find(".fh-follow").prop("checked") ? 1 : 0;
			this.filters.mine = this.page.main.find(".fh-mine").prop("checked") ? 1 : 0;
			this.refresh();
		}
		if (target.dataset.invoice) {
			if (target.checked) {
				this.picked.add(target.dataset.invoice);
			} else {
				this.picked.delete(target.dataset.invoice);
			}
		}
	}

	async onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button) {
			return;
		}
		if (button.dataset.action === "open") {
			await this.openCustomer(button.dataset.customer);
		}
		if (button.dataset.action === "form") {
			frappe.set_route("Form", button.dataset.form, button.dataset.doc);
		}
		if (!this.client) {
			return;
		}
		if (button.dataset.action === "save") {
			await this.saveCall();
		}
		if (button.dataset.action === "soa") {
			await this.generateSoa();
		}
		if (button.dataset.action === "send") {
			await this.sendSoa();
		}
		if (button.dataset.action === "report") {
			this.createReport();
		}
		if (button.dataset.action === "payment") {
			this.recordPayment();
		}
		if (button.dataset.action === "dispute") {
			this.raiseDispute();
		}
	}

	pickedInvoices() {
		return ((this.client && this.client.invoices) || []).filter((row) => this.picked.has(row.sales_invoice));
	}

	async saveCall() {
		this.readDraft();
		const saved = await frappehero.call("frappehero.collections_desk.api.save_call", {
			company: this.company(),
			customer: this.customer,
			call_datetime: this.draft.call_datetime,
			direction: this.draft.direction,
			phone: this.draft.phone,
			contact_person: this.draft.contact_person,
			outcome: this.draft.outcome,
			notes: this.draft.notes,
			promise_amount: this.draft.promise_amount,
			promise_date: this.draft.promise_date,
			next_follow_up: this.draft.next_follow_up,
		});
		this.callName = saved.name;
		this.draft.outcome = "";
		this.draft.notes = "";
		this.draft.promise_amount = "";
		this.draft.promise_date = "";
		this.draft.next_follow_up = "";
		this.draft.call_datetime = this.nowLocal();
		frappe.show_alert({ message: __("Call {0} logged", [saved.name]), indicator: "green" });
		await this.refresh();
		await this.loadClient();
	}

	async generateSoa() {
		const statement = await frappehero.call("frappehero.collections_desk.api.preview_statement", {
			company: this.company(),
			customer: this.customer,
		});
		const dialog = new frappe.ui.Dialog({
			title: __("Statement of Account"),
			primary_action_label: __("Open Report"),
			primary_action: () => {
				frappe.route_options = { company: this.company(), customer: this.customer };
				frappe.set_route("query-report", "Statement of Account");
			},
		});
		dialog.$body.html(this.statementHtml(statement));
		dialog.show();
	}

	statementHtml(statement) {
		const rows = (statement && statement.rows) || [];
		const disputed = (statement && statement.disputed_rows) || [];
		return `
			<p>${__("Amount due")}: ${this.money(statement && statement.amount_due)}</p>
			${this.statementTable(rows, true)}
			${disputed.length ? `<h4>${__("Disputed Transactions")}</h4><p>${__("Left out of the amount due.")} ${this.money(statement.disputed_outstanding)}</p>${this.statementTable(disputed, false)}` : ""}
		`;
	}

	statementTable(rows, withBalance) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td>${frappehero.esc(row.posting_date || "")}</td>
					<td>${frappehero.esc(row.sales_invoice || "")}</td>
					<td>${frappehero.esc(row.due_date || "")}</td>
					<td class="fh-num">${this.money(row.outstanding)}</td>
					${withBalance ? `<td class="fh-num">${row.running_balance == null ? "" : this.money(row.running_balance)}</td>` : ""}
				</tr>`
			)
			.join("");
		return `<table class="fh-matrix"><thead><tr><th>${__("Date")}</th><th>${__("Invoice")}</th><th>${__("Due")}</th><th>${__("Outstanding")}</th>${withBalance ? `<th>${__("Balance")}</th>` : ""}</tr></thead><tbody>${body || `<tr><td colspan="5">${__("No invoices are due.")}</td></tr>`}</tbody></table>`;
	}

	sendSoa() {
		const dialog = new frappe.ui.Dialog({
			title: __("Send Statement"),
			fields: [
				{
					fieldname: "recipient",
					fieldtype: "Data",
					options: "Email",
					label: __("Email"),
					reqd: 1,
					default: (this.client && this.client.email) || "",
				},
			],
			primary_action_label: __("Send"),
			primary_action: async (values) => {
				const result = await frappehero.call("frappehero.collections_desk.api.send_statement", {
					company: this.company(),
					customer: this.customer,
					recipient: values.recipient,
					call_name: this.callName,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Statement sent to {0}", [result.recipient]), indicator: "green" });
				if (this.callName) {
					await this.loadClient();
				}
			},
		});
		dialog.show();
	}

	createReport() {
		const picked = this.pickedInvoices()[0];
		const company = this.company();
		const customer = this.customer;
		frappe.prompt(
			[
				{
					fieldname: "report_type",
					fieldtype: "Select",
					options: "Claim\nIncident",
					label: __("Type"),
					reqd: 1,
					default: "Claim",
				},
				{
					fieldname: "sales_invoice",
					fieldtype: "Link",
					options: "Sales Invoice",
					label: __("Sales Invoice"),
					default: picked ? picked.sales_invoice : "",
					get_query: () => ({ filters: { company, customer, docstatus: 1 } }),
				},
				{ fieldname: "amount", fieldtype: "Currency", label: __("Amount") },
				{ fieldname: "summary", fieldtype: "Small Text", label: __("Summary"), reqd: 1 },
				{
					fieldname: "raise_dispute",
					fieldtype: "Check",
					label: __("Also raise a dispute for this invoice"),
				},
			],
			async (values) => {
				const report = await frappehero.call("frappehero.collections_desk.api.create_report", {
					company,
					customer,
					report_type: values.report_type,
					summary: values.summary,
					sales_invoice: values.sales_invoice,
					amount: values.amount,
					call_name: this.callName,
					raise_dispute: values.raise_dispute ? 1 : 0,
				});
				frappe.show_alert({ message: __("{0} {1} created", [report.report_type, report.name]), indicator: "green" });
				await this.loadClient();
			},
			__("Claim or Incident"),
			__("Create")
		);
	}

	recordPayment() {
		const invoices = this.pickedInvoices();
		if (!invoices.length) {
			frappe.msgprint(__("Tick the invoices this payment covers."));
			return;
		}
		const company = this.company();
		const customer = this.customer;
		const dialog = new frappe.ui.Dialog({
			title: __("Record Payment"),
			fields: [
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: __("Amount"),
					reqd: 1,
					default: invoices.reduce((sum, row) => sum + Number(row.outstanding || 0), 0),
				},
				{
					fieldname: "posting_date",
					fieldtype: "Date",
					label: __("Posting Date"),
					reqd: 1,
					default: frappe.datetime.get_today(),
				},
				{
					fieldname: "mode_of_payment",
					fieldtype: "Link",
					options: "Mode of Payment",
					label: __("Mode of Payment"),
				},
			],
			primary_action_label: __("Create Draft"),
			primary_action: async (values) => {
				const result = await frappehero.call("frappehero.collections_desk.api.record_payment", {
					company,
					customer,
					amount: values.amount,
					invoices: invoices.map((row) => row.sales_invoice),
					posting_date: values.posting_date,
					mode_of_payment: values.mode_of_payment,
					call_name: this.callName,
				});
				dialog.hide();
				frappe.set_route("Form", "Payment Entry", result.name);
			},
		});
		dialog.show();
	}

	raiseDispute() {
		const invoices = this.pickedInvoices();
		if (invoices.length !== 1) {
			frappe.msgprint(__("Tick one invoice to dispute."));
			return;
		}
		const invoice = invoices[0].sales_invoice;
		const company = this.company();
		const customer = this.customer;
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			async (values) => {
				await frappehero.call("frappehero.dispute_desk.api.raise_dispute", {
					reference_doctype: "Sales Invoice",
					reference_name: invoice,
					sales_invoice: invoice,
					company,
					customer,
					reason: values.reason,
					source_module: "Collections Desk",
				});
				frappe.show_alert({ message: __("Dispute opened for {0}", [invoice]), indicator: "green" });
				await this.loadClient();
			},
			__("Raise Dispute"),
			__("Raise")
		);
	}

	money(value) {
		return frappe.format(value || 0, { fieldtype: "Float", precision: 2 });
	}
};
