const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const directory = path.join(__dirname, "..");
const referencesSource = fs.readFileSync(path.join(directory, "payment_entry_references.js"), "utf8");
const multiSource = fs.readFileSync(path.join(directory, "payment_entry_multi.js"), "utf8");

function flt(value, precision) {
	const number = Number(value);
	if (!Number.isFinite(number)) {
		return 0;
	}
	if (precision == null) {
		return number;
	}
	const factor = 10 ** precision;
	return Math.round(number * factor) / factor;
}

function load(options = {}) {
	const shared = {
		handlers: {},
		writes: [],
		timers: [],
		locals: {},
		dirtied: false,
	};
	const invoices =
		options.invoices ||
		(() => ({
			hero_invoice_currency: "PHP",
			hero_invoice_amount: 8000,
			conversion_rate: 1,
		}));
	const context = {
		__: (text) => text,
		flt,
		locals: shared.locals,
		setTimeout(fn) {
			shared.timers.push(fn);
			return shared.timers.length;
		},
		clearTimeout(id) {
			if (id) {
				shared.timers[id - 1] = null;
			}
		},
		frappe: {
			ui: {
				form: {
					on(doctype, events) {
						shared.handlers[doctype] = shared.handlers[doctype] || {};
						for (const [name, fn] of Object.entries(events)) {
							shared.handlers[doctype][name] = shared.handlers[doctype][name] || [];
							shared.handlers[doctype][name].push(fn);
						}
					},
				},
			},
			meta: {
				get_docfield() {
					return {};
				},
			},
			model: {
				set_value(cdt, cdn, field, value) {
					const row = shared.locals[cdt][cdn];
					shared.writes.push({ cdt, cdn, field, value });
					row[field] = value;
					row.__unsaved = 1;
					const parent = shared.locals[row.parenttype] && shared.locals[row.parenttype][row.parent];
					if (parent) {
						parent.__unsaved = 1;
					}
					return Promise.resolve();
				},
			},
			db: {
				get_value() {
					return Promise.resolve({ message: { default_currency: options.companyCurrency || "PHP" } });
				},
			},
			call(request) {
				const method = request.method || "";
				const args = request.args || {};
				if (options.call) {
					return options.call(method, args);
				}
				if (method.endsWith("invoice_currency_for_references")) {
					const refs = args.references || [];
					return Promise.resolve({ message: refs.map((row, index) => invoices(row, index)) });
				}
				return Promise.resolve({ message: {} });
			},
		},
	};
	vm.createContext(context);
	vm.runInContext(referencesSource, context);
	vm.runInContext(multiSource, context);

	function fire(doctype, event, ...args) {
		for (const fn of (shared.handlers[doctype] && shared.handlers[doctype][event]) || []) {
			fn(...args);
		}
	}

	async function flush() {
		for (let pass = 0; pass < 8; pass++) {
			const batch = shared.timers.slice();
			shared.timers.length = 0;
			for (const fn of batch) {
				if (typeof fn === "function") {
					fn();
				}
			}
			await Promise.resolve();
			await Promise.resolve();
			await Promise.resolve();
		}
	}

	function remember(doc) {
		shared.locals[doc.doctype] = shared.locals[doc.doctype] || {};
		shared.locals[doc.doctype][doc.name] = doc;
		for (const row of doc.references || []) {
			shared.locals[row.doctype] = shared.locals[row.doctype] || {};
			shared.locals[row.doctype][row.name] = row;
		}
	}

	function payment(rows, docOverrides) {
		const doc = Object.assign(
			{
				doctype: "Payment Entry",
				name: "ATN-MNL-CV-0000000037",
				docstatus: 0,
				company: "ATN",
				payment_type: "Pay",
				party_type: "Supplier",
				party: "LORANOMNL",
				paid_from: "BDO-PAS-PHP-ATN - Banco de Oro",
				paid_from_account_currency: "PHP",
				paid_to: "Creditors PHP",
				paid_to_account_currency: "PHP",
				source_exchange_rate: 1,
				target_exchange_rate: 1,
				references: rows,
			},
			docOverrides || {}
		);
		doc.references = rows;
		remember(doc);
		const frm = {
			doc,
			doctype: "Payment Entry",
			fields_dict: {
				references: {
					grid: {
						refresh() {},
						setup_visible_columns() {},
					},
				},
			},
			set_query() {},
			add_custom_button() {},
			refresh_field() {},
			refresh_fields() {},
			dirty() {
				shared.dirtied = true;
				doc.__unsaved = 1;
			},
		};
		return frm;
	}

	return { shared, fire, flush, payment };
}

function savedRow(overrides) {
	return Object.assign(
		{
			doctype: "Payment Entry Reference",
			name: "row-1",
			parenttype: "Payment Entry",
			parent: "ATN-MNL-CV-0000000037",
			reference_doctype: "Purchase Invoice",
			reference_name: "PINV-1",
			allocated_amount: 5000,
			hero_allocated_invoice_amount: 0,
			hero_allocated_account_amount: 5000,
			hero_bank_amount: 5000,
			hero_invoice_currency: "",
			hero_invoice_amount: 0,
			hero_booked_rate: 0,
			hero_payment_currency: "",
			hero_account_currency: "PHP",
		},
		overrides || {}
	);
}

test("opening a saved payment keeps its allocation and stays saved", async () => {
	const { shared, fire, flush, payment } = load({});
	const row = savedRow();
	const frm = payment([row]);
	fire("Payment Entry", "refresh", frm);
	await flush();

	assert.equal(row.allocated_amount, 5000);
	assert.equal(row.hero_bank_amount, 5000);
	assert.equal(row.hero_allocated_account_amount, 5000);
	assert.equal(row.hero_allocated_invoice_amount, 0);
	assert.equal(row.hero_payment_currency, "");
	assert.equal(row.hero_allocation_basis || "", "");
	assert.equal(shared.writes.length, 0);
	assert.equal(frm.doc.__unsaved || 0, 0);
	assert.equal(shared.dirtied, false);
	assert.equal(row.hero_invoice_currency, "PHP");
});

test("opening does not recompute a multi-currency allocation from the invoice amount", async () => {
	const { shared, fire, flush, payment } = load({
		invoices: () => ({
			hero_invoice_currency: "USD",
			hero_invoice_amount: 1000,
			conversion_rate: 57,
		}),
	});
	const row = savedRow({
		allocated_amount: 5000,
		hero_allocated_invoice_amount: 100,
		hero_allocated_account_amount: 5000,
		hero_bank_amount: 5000,
		hero_invoice_currency: "USD",
		hero_invoice_amount: 1000,
		hero_booked_rate: 56,
		hero_account_currency: "USD",
		hero_payment_currency: "PHP",
	});
	const frm = payment([row]);
	fire("Payment Entry", "refresh", frm);
	await flush();

	assert.equal(row.allocated_amount, 5000);
	assert.equal(row.hero_bank_amount, 5000);
	assert.equal(row.hero_allocated_account_amount, 5000);
	assert.equal(row.hero_booked_rate, 56);
	assert.equal(shared.writes.length, 0);
	assert.equal(frm.doc.__unsaved || 0, 0);
});

test("editing the allocated invoice amount converts that draft row", async () => {
	const { shared, fire, flush, payment } = load({});
	const edited = savedRow({ name: "row-1", reference_name: "PINV-1" });
	const other = savedRow({
		name: "row-2",
		reference_name: "PINV-2",
		allocated_amount: 80,
		hero_allocated_invoice_amount: 25,
		hero_allocated_account_amount: 80,
		hero_bank_amount: 80,
	});
	const frm = payment([edited, other]);
	fire("Payment Entry", "refresh", frm);
	await flush();
	shared.writes.length = 0;

	edited.hero_allocated_invoice_amount = 200;
	fire("Payment Entry Reference", "hero_allocated_invoice_amount", frm, edited.doctype, edited.name);

	assert.equal(edited.allocated_amount, 200);
	assert.equal(edited.hero_bank_amount, 200);
	assert.equal(edited.hero_allocation_basis, "Invoice");
	assert.equal(other.allocated_amount, 80);
	assert.equal(other.hero_allocated_invoice_amount, 25);
	assert.equal(frm.doc.__unsaved, 1);
	assert.ok(shared.writes.some((write) => write.field === "allocated_amount" && write.value === 200));
});

test("an invoice amount edited before currency arrives converts only that row", async () => {
	let release;
	const started = new Promise((resolve) => {
		release = resolve;
	});
	const { shared, fire, flush, payment } = load({
		call(method, args) {
			if (method.endsWith("invoice_currency_for_references")) {
				return started.then(() => ({
					message: (args.references || []).map(() => ({
						hero_invoice_currency: "PHP",
						hero_invoice_amount: 8000,
						conversion_rate: 1,
					})),
				}));
			}
			return Promise.resolve({ message: {} });
		},
	});
	const edited = savedRow({ name: "row-1", reference_name: "PINV-1", allocated_amount: 5000 });
	const other = savedRow({
		name: "row-2",
		reference_name: "PINV-2",
		allocated_amount: 80,
		hero_allocated_invoice_amount: 25,
		hero_allocated_account_amount: 80,
		hero_bank_amount: 80,
	});
	const frm = payment([edited, other]);
	fire("Payment Entry", "refresh", frm);
	await flush();

	edited.hero_allocated_invoice_amount = 200;
	fire("Payment Entry Reference", "hero_allocated_invoice_amount", frm, edited.doctype, edited.name);
	assert.equal(edited.allocated_amount, 5000);

	release();
	await started;
	await flush();

	assert.equal(edited.allocated_amount, 200);
	assert.equal(other.allocated_amount, 80);
	assert.equal(other.hero_bank_amount, 80);
	assert.ok(shared.writes.every((write) => write.cdn === edited.name));
});

test("a submitted payment is not rewritten on open or by the invoice amount handler", async () => {
	const { shared, fire, flush, payment } = load({
		invoices: () => ({
			hero_invoice_currency: "USD",
			hero_invoice_amount: 1000,
			conversion_rate: 57,
		}),
	});
	const row = savedRow({
		allocated_amount: 5000,
		hero_allocated_invoice_amount: 100,
		hero_invoice_currency: "USD",
		hero_invoice_amount: 1000,
		hero_booked_rate: 56,
		hero_account_currency: "USD",
	});
	const frm = payment([row], { docstatus: 1 });
	fire("Payment Entry", "refresh", frm);
	await flush();
	row.hero_allocated_invoice_amount = 40;
	fire("Payment Entry Reference", "hero_allocated_invoice_amount", frm, row.doctype, row.name);

	assert.equal(row.allocated_amount, 5000);
	assert.equal(row.hero_bank_amount, 5000);
	assert.equal(shared.writes.length, 0);
	assert.equal(frm.doc.__unsaved || 0, 0);
});
