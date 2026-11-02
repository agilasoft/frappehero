const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
	path.join(__dirname, "..", "opening_invoice_creation_tool.js"),
	"utf8"
);
const expected = ["Sales", "Purchase", "Credit Note", "Debit Note"];

function form(options = "Sales\nPurchase") {
	const handlers = {};
	const registrations = [];
	const context = vm.createContext({
		__: (text) => text,
		frappehero: {},
		frappe: {
			provide() {},
			show_alert() {},
			ui: {
				form: {
					on(doctype, events) {
						registrations.push(doctype);
						handlers[doctype] = events;
					},
					ControlSelect: class {
						set_options() {
							const raw = (this.df && this.df.options) || "";
							const list = (Array.isArray(raw) ? raw : String(raw).split("\n")).filter(Boolean);
							if (JSON.stringify(list) === this.last_options) {
								return;
							}
							this.last_options = JSON.stringify(list);
							this.rendered_options = list;
						}
					},
					add_options(input, options_list) {
						input.painted = options_list.slice();
						return options_list.slice();
					},
				},
			},
		},
		setTimeout() {},
	});
	vm.runInContext(source, context);

	const df = { options };
	const control = { df, rendered_options: ["Sales", "Purchase"] };
	const frm = {
		fields_dict: { invoice_type: control },
		set_df_property(fieldname, property, value) {
			assert.equal(fieldname, "invoice_type");
			if (df[property] !== value) {
				df[property] = value;
				this.refresh_field(fieldname);
			}
		},
		refresh_field(fieldname) {
			assert.equal(fieldname, "invoice_type");
			control.rendered_options = df.options.split("\n");
		},
	};
	return { frm, control, events: handlers["Opening Invoice Creation Tool"], context, registrations };
}

test("Desk asset enables notes without a DocType script in cached metadata", () => {
	const { frm, control, events } = form();
	assert.ok(events);
	events.setup(frm);
	assert.deepEqual(control.rendered_options, expected);
});

test("loading the Desk asset and DocType hook registers handlers only once", () => {
	const { context, registrations } = form();
	vm.runInContext(source, context);
	assert.deepEqual(registrations, [
		"Opening Invoice Creation Tool",
		"Opening Invoice Creation Tool Item",
	]);
});

test("setup renders both note choices alongside standard invoice types", () => {
	const { frm, control, events } = form();
	events.setup(frm);
	assert.deepEqual(control.rendered_options, expected);
});

test("refresh repairs a stale select even when metadata already contains both notes", () => {
	const { frm, control, events } = form(expected.join("\n"));
	events.refresh(frm);
	assert.deepEqual(control.rendered_options, expected);
});

test("post-render restores choices replaced by another form handler", () => {
	const { frm, control, events } = form();
	events.setup(frm);
	control.df.options = "Sales\nPurchase";
	control.rendered_options = ["Sales", "Purchase"];
	events.onload_post_render(frm);
	assert.deepEqual(control.rendered_options, expected);
});

test("repeated form events do not duplicate choices or reset the selected note", () => {
	const { frm, control, events } = form();
	frm.doc = { invoice_type: "Credit Note" };
	events.setup(frm);
	events.refresh(frm);
	events.onload_post_render(frm);
	assert.deepEqual(control.rendered_options, expected);
	assert.equal(frm.doc.invoice_type, "Credit Note");
});

test("array options and existing additional choices are preserved", () => {
	const { frm, control, events } = form(["Sales", "Purchase", "Custom", "Credit Note"]);
	events.setup(frm);
	assert.deepEqual(control.rendered_options, ["Sales", "Purchase", "Custom", "Credit Note", "Debit Note"]);
});

test("type choices reach the rendered select when metadata is a different copy", () => {
	const { frm, control, events } = form();
	const meta = { options: "Sales\nPurchase" };
	frm.doctype = "Opening Invoice Creation Tool";
	frm.set_df_property = (fieldname, property, value) => {
		assert.equal(fieldname, "invoice_type");
		meta[property] = value;
	};
	events.setup(frm);
	assert.equal(meta.options, expected.join("\n"));
	assert.equal(control.df.options, expected.join("\n"));
	assert.deepEqual(control.rendered_options, expected);
});

test("the select builder adds credit note and debit note to sales and purchase", () => {
	const { context } = form();
	const control = {
		df: {
			fieldname: "invoice_type",
			parent: "Opening Invoice Creation Tool",
			options: "Sales\nPurchase",
		},
		frm: { doctype: "Opening Invoice Creation Tool" },
	};
	const input = {
		closest(selector) {
			assert.equal(selector, ".frappe-control");
			return { fieldobj: control };
		},
	};
	const painted = context.frappe.ui.form.add_options(input, ["Sales", "Purchase"]);
	assert.deepEqual(Array.from(painted), expected);
	assert.equal(control.df.options, expected.join("\n"));
});

test("other selects keep the options they were given", () => {
	const { context } = form();
	const input = {
		closest() {
			return { fieldobj: { df: { fieldname: "status", parent: "Sales Invoice" } } };
		},
	};
	const painted = context.frappe.ui.form.add_options(input, ["Draft", "Paid"]);
	assert.deepEqual(painted, ["Draft", "Paid"]);
});

test("an already drawn select gains credit note and debit note", () => {
	const { frm, control, events } = form();
	const nodes = [{ value: "Sales" }, { value: "Purchase" }];
	const select = {
		tagName: "SELECT",
		value: "Sales",
		options: nodes,
		get firstChild() {
			return nodes[0] || null;
		},
		removeChild() {
			nodes.shift();
		},
		appendChild(option) {
			nodes.push(option);
		},
		ownerDocument: {
			createElement() {
				return {};
			},
		},
	};
	control.$input = select;
	events.setup(frm);
	assert.deepEqual(
		nodes.map((option) => option.value),
		expected
	);
	assert.equal(select.value, "Sales");
});

test("a later select refresh cannot drop credit note or debit note", () => {
	const { context } = form();
	const Control = context.frappe.ui.form.ControlSelect;
	const control = new Control();
	control.df = {
		fieldname: "invoice_type",
		parent: "Opening Invoice Creation Tool",
		options: "Sales\nPurchase",
	};
	control.frm = { doctype: "Opening Invoice Creation Tool" };
	control.last_options = JSON.stringify(expected);
	control.rendered_options = ["Sales", "Purchase"];
	control.set_options();
	assert.deepEqual(control.rendered_options, expected);
});
