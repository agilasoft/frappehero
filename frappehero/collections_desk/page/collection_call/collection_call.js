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
		this.installMenus();
		this.page.main.html(`
			<div class="fh-app fh-call">
				<div class="fh-call-bar">
					<input type="search" class="fh-search" placeholder="${__("Search customer, group, outcome")}">
					<div class="fh-company"></div>
					<div class="fh-call-checks">
						<label class="fh-check"><input type="checkbox" class="fh-overdue"> ${__("Overdue")}</label>
						<label class="fh-check"><input type="checkbox" class="fh-follow"> ${__("Follow-ups due")}</label>
						<label class="fh-check"><input type="checkbox" class="fh-mine"> ${__("My calls")}</label>
					</div>
				</div>
				<div class="fh-call-summary"></div>
				<div class="fh-call-grid">
					<aside class="fh-call-queue"></aside>
					<section class="fh-call-stage">
						<div class="fh-call-sticky">
							<div class="fh-call-identity"></div>
							${this.toolBar()}
						</div>
						<div class="fh-call-cluster"></div>
						<div class="fh-call-log"></div>
						<div class="fh-call-file"></div>
					</section>
				</div>
			</div>
		`);
		this.listEl = this.page.main.find(".fh-call-queue");
		this.headEl = this.page.main.find(".fh-call-identity");
		this.clusterEl = this.page.main.find(".fh-call-cluster");
		this.clientEl = this.page.main.find(".fh-call-file");
		this.composerEl = this.page.main.find(".fh-call-log");
		this.statsEl = this.page.main.find(".fh-call-summary");
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

	installMenus() {
		const create = __("Create");
		const open = __("Open");
		this.page.add_inner_button(__("Call"), () => this.requireClient(() => this.saveCall()), create);
		this.page.add_inner_button(__("Statement"), () => this.requireClient(() => this.generateSoa()), create);
		this.page.add_inner_button(__("Claim"), () => this.requireClient(() => this.createReport("Claim")), create);
		this.page.add_inner_button(__("Incident"), () => this.requireClient(() => this.createReport("Incident")), create);
		this.page.add_inner_button(__("Payment"), () => this.requireClient(() => this.recordPayment()), create);
		this.page.add_inner_button(__("Dispute"), () => this.requireClient(() => this.raiseDispute()), create);
		this.page.add_inner_button(__("Send statement"), () => this.requireClient(() => this.sendSoa()), create);
		this.page.add_inner_button(__("Statement of Account"), () => this.openStatement(), open);
		this.page.add_inner_button(__("Collection Calls"), () => frappe.set_route("List", "Hero Collection Call"), open);
		this.page.add_inner_button(__("Claims and Incidents"), () => frappe.set_route("List", "Hero Collection Report"), open);
	}

	requireClient(action) {
		if (!this.client) {
			frappe.msgprint(__("Choose a customer first."));
			return;
		}
		return action();
	}

	menuItem(action, label, extra) {
		return `<button type="button" class="fh-menu-btn" data-action="${action}" ${extra || ""}>${frappehero.esc(label)}</button>`;
	}

	toolBar() {
		return `
			<div class="fh-call-tools">
				<div class="fh-cockpit-menus">
					<div class="fh-cockpit-menu">
						<span>${__("Create")}</span>
						${this.menuItem("save", __("Create call"))}
						${this.menuItem("soa", __("Create statement"))}
						${this.menuItem("send", __("Send statement"))}
						${this.menuItem("report", __("Create claim"), 'data-report-type="Claim"')}
						${this.menuItem("report", __("Create incident"), 'data-report-type="Incident"')}
						${this.menuItem("payment", __("Create payment"))}
						${this.menuItem("dispute", __("Create dispute"))}
					</div>
					<div class="fh-cockpit-menu">
						<span>${__("Open")}</span>
						${this.menuItem("open-statement", __("Statement of Account"))}
						${this.menuItem("open-calls", __("Collection calls"))}
						${this.menuItem("open-claims", __("Claims and incidents"))}
					</div>
				</div>
			</div>
		`;
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

	async loadClient(options) {
		const keepDraft = Boolean(options && options.keepDraft);
		if (keepDraft) {
			this.readDraft();
		}
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
		if (!keepDraft && !this.draft.phone) {
			this.draft.phone = client.phone || "";
		}
		this.renderClient();
		this.renderComposer();
	}

	renderQueue() {
		const summary = this.summary || {};
		this.statsEl.html(
			[
				[summary.customers || 0, __("To call")],
				[this.money(summary.amount_due), __("Amount due")],
				[summary.promises_due || 0, __("Promises due")],
				[summary.calls_today || 0, __("Calls today")],
			]
				.map(
					([value, label]) =>
						`<div class="fh-call-figure"><b>${frappehero.esc(value)}</b><span>${frappehero.esc(label)}</span></div>`
				)
				.join("")
		);
		this.listEl.html(
			(this.rows || [])
				.map((row) => {
					const due = row.oldest_due ? __("Due {0}", [this.date(row.oldest_due)]) : "";
					const follow = row.follow_up_due
						? __("Follow up {0}", [this.date(row.next_follow_up)])
						: row.last_outcome || "";
					const meta = [this.money(row.outstanding), due, follow].filter(Boolean).join(" · ");
					return `
					<button type="button" class="fh-call-item ${row.customer === this.customer ? "fh-selected" : ""}" data-action="open" data-customer="${frappehero.esc(row.customer)}">
						<span class="fh-call-item-name">${frappehero.esc(row.customer_name || row.customer)}</span>
						<span class="fh-call-item-meta">${frappehero.esc(meta)}</span>
					</button>`;
				})
				.join("") || `<div class="fh-empty">${__("No customers match these filters.")}</div>`
		);
	}

	renderClient() {
		const client = this.client;
		if (!client) {
			this.headEl.empty();
			this.clusterEl.empty();
			this.clientEl.html(
				`<div class="fh-empty">${__("Choose a customer. The cockpit shows the balance, the invoices, and the earlier calls.")}</div>`
			);
			return;
		}
		const phone = client.tel
			? `<a class="fh-tel" href="${frappehero.esc(client.tel)}">${frappehero.esc(client.phone)}</a>`
			: frappehero.esc(client.phone || __("No phone"));
		const address = (client.address || []).filter(Boolean).join(", ");
		const facts = [
			[__("Group"), client.customer_group],
			[__("Territory"), client.territory],
			[__("Tax ID"), client.tax_id],
			[__("Credit limit"), client.credit_limit == null ? __("None") : this.money(client.credit_limit)],
		]
			.filter(([, value]) => value)
			.map(
				([label, value]) =>
					`<div class="fh-call-figure"><span>${frappehero.esc(label)}</span><b>${frappehero.esc(value)}</b></div>`
			)
			.join("");
		const buckets = (client.aging && client.aging.buckets) || {};
		const aging = ["Current", "1-30", "31-60", "61-90", "91 and over"]
			.map(
				(name) =>
					`<div class="fh-call-figure"><span>${frappehero.esc(name)}</span><b>${frappehero.esc(this.money(buckets[name]))}</b></div>`
			)
			.join("");
		const due = this.money(client.aging && client.aging.amount_due);
		const disputed = this.money(client.aging && client.aging.disputed_outstanding);
		this.headEl.html(`
			<header class="fh-call-head">
				<div>
					<h2>${frappehero.esc(client.customer_name || client.customer)}</h2>
					<p class="fh-muted">${phone} · ${frappehero.esc(client.email || __("No email"))}${client.disabled ? " · " + frappehero.esc(__("Disabled")) : ""}</p>
					${address ? `<p class="fh-muted">${frappehero.esc(address)}</p>` : ""}
				</div>
				<div class="fh-call-outstanding">
					<b>${frappehero.esc(this.money(client.outstanding))}</b>
					<span>${__("Outstanding")}</span>
				</div>
			</header>
		`);
		this.clusterEl.html(`
			<div class="fh-call-facts">${facts}</div>
			<div class="fh-call-aging">${aging}</div>
			<p class="fh-call-note">${__("Amount still due {0}. Disputed {1}.", [due, disputed])}</p>
		`);
		this.clientEl.html(`
			${this.section(__("Open invoices"), this.invoiceTable(client.invoices))}
			<div class="fh-call-boards">
				${this.section(__("Receipts"), client.payments && client.payments.length ? this.paymentTable(client.payments) : `<p class="fh-empty">${__("No receipts yet.")}</p>`)}
				${this.section(__("Open disputes"), client.disputes && client.disputes.length ? this.disputeTable(client.disputes) : `<p class="fh-empty">${__("No open dispute.")}</p>`)}
				${this.section(__("Earlier calls"), client.calls && client.calls.length ? this.callTable(client.calls) : `<p class="fh-empty">${__("No calls yet.")}</p>`)}
				${this.section(__("Claims and incidents"), client.reports && client.reports.length ? this.reportTable(client.reports) : `<p class="fh-empty">${__("No claim or incident.")}</p>`)}
			</div>
		`);
	}

	section(title, body) {
		return `<section class="fh-call-section"><h3>${frappehero.esc(title)}</h3>${body}</section>`;
	}

	invoiceTable(rows) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td><input type="checkbox" data-invoice="${frappehero.esc(row.sales_invoice)}" ${this.picked.has(row.sales_invoice) ? "checked" : ""}></td>
					<td><button type="button" class="fh-btn" data-action="form" data-form="Sales Invoice" data-doc="${frappehero.esc(row.sales_invoice)}">${frappehero.esc(row.sales_invoice)}</button></td>
					<td>${frappehero.esc(this.date(row.due_date))}</td>
					<td class="fh-num">${frappehero.esc(this.money(row.outstanding))}</td>
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
					<td>${frappehero.esc(this.date(row.posting_date))}</td>
					<td class="fh-num">${frappehero.esc(this.money(row.paid_amount))}</td>
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
					<td>${frappehero.esc(this.when(row.call_time))}</td>
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
			this.composerEl.empty();
			return;
		}
		const draft = this.draft;
		const outcomes = ["Reached", "No Answer", "Busy", "Wrong Number", "Voicemail", "Promised", "Refused", "Disputed", "Callback"]
			.map((outcome) => `<option value="${outcome}" ${draft.outcome === outcome ? "selected" : ""}>${__(outcome)}</option>`)
			.join("");
		this.composerEl.html(`
			<h3>${__("This call")}</h3>
			<p class="fh-muted">${this.callName ? __("Logging onto {0}.", [frappehero.esc(this.callName)]) : __("Create call logs this call. Later actions stamp that call.")}</p>
			<div class="fh-call-fields">
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
				<label class="fh-field">${__("Promise amount")}<input type="text" class="fh-promise-amount" inputmode="decimal" value="${frappehero.esc(draft.promise_amount || "")}"></label>
				<label class="fh-field">${__("Promise date")}<input type="date" class="fh-promise-date" value="${frappehero.esc(draft.promise_date || "")}"></label>
				<label class="fh-field">${__("Next follow-up")}<input type="date" class="fh-follow-date" value="${frappehero.esc(draft.next_follow_up || "")}"></label>
				<label class="fh-field fh-call-notes">${__("Notes")}<textarea class="fh-notes">${frappehero.esc(draft.notes || "")}</textarea></label>
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
		if (button.dataset.action === "open-statement") {
			this.openStatement();
			return;
		}
		if (button.dataset.action === "open-calls") {
			frappe.set_route("List", "Hero Collection Call");
			return;
		}
		if (button.dataset.action === "open-claims") {
			frappe.set_route("List", "Hero Collection Report");
			return;
		}
		if (!this.client) {
			if (["save", "soa", "send", "report", "payment", "dispute"].includes(button.dataset.action)) {
				frappe.msgprint(__("Choose a customer first."));
			}
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
			this.createReport(button.dataset.reportType);
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
			<p>${__("Amount due")}: ${frappehero.esc(this.money(statement && statement.amount_due))}</p>
			${this.statementTable(rows, true)}
					${disputed.length ? `<h4>${__("Disputed Transactions")}</h4><p>${__("Left out of the amount due.")} ${frappehero.esc(this.money(statement.disputed_outstanding))}</p>${this.statementTable(disputed, false)}` : ""}
		`;
	}

	statementTable(rows, withBalance) {
		const body = (rows || [])
			.map(
				(row) => `<tr>
					<td>${frappehero.esc(this.date(row.posting_date))}</td>
					<td>${frappehero.esc(row.sales_invoice || "")}</td>
					<td>${frappehero.esc(this.date(row.due_date))}</td>
					<td class="fh-num">${frappehero.esc(this.money(row.outstanding))}</td>
					${withBalance ? `<td class="fh-num">${row.running_balance == null ? "" : frappehero.esc(this.money(row.running_balance))}</td>` : ""}
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
					await this.loadClient({ keepDraft: true });
				}
			},
		});
		dialog.show();
	}

	openStatement() {
		const options = { company: this.company() };
		if (this.customer) {
			options.customer = this.customer;
		}
		frappe.route_options = options;
		frappe.set_route("query-report", "Statement of Account");
	}

	createReport(reportType) {
		const picked = this.pickedInvoices()[0];
		const company = this.company();
		const customer = this.customer;
		const type = reportType === "Incident" ? "Incident" : "Claim";
		frappe.prompt(
			[
				{
					fieldname: "report_type",
					fieldtype: "Select",
					options: "Claim\nIncident",
					label: __("Type"),
					reqd: 1,
					default: type,
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
				await this.loadClient({ keepDraft: true });
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
				await this.loadClient({ keepDraft: true });
			},
			__("Raise Dispute"),
			__("Raise")
		);
	}

	money(value) {
		const number = Number(value);
		const amount = Number.isFinite(number) ? number : 0;
		const sign = amount < 0 ? "-" : "";
		const [whole, fraction] = Math.abs(amount).toFixed(2).split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
		return `${sign}${grouped}.${fraction}`;
	}

	date(value) {
		if (!value) {
			return "";
		}
		const text = String(value).slice(0, 10);
		if (frappe.datetime && frappe.datetime.str_to_user) {
			return frappe.datetime.str_to_user(text);
		}
		return text;
	}

	when(value) {
		if (!value) {
			return "";
		}
		const text = String(value).replace("T", " ");
		const clock = text.slice(11, 16);
		const day = this.date(text);
		return clock ? `${day} ${clock}` : day;
	}
};
