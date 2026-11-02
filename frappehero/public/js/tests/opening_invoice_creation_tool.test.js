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
