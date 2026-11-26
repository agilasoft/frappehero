const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "sales_invoice_dispute.js"), "utf8");

function load(roles) {
	const handlers = [];
	const context = {
		__: (text) => text,
		frappe: {
			ui: {
				form: {
					on(doctype, events) {
						assert.equal(doctype, "Sales Invoice");
						handlers.push(events);
					},
				},
			},
			user: {
				has_role(role) {
					return (roles || []).includes(role);
				},
			},
		},
	};
	vm.createContext(context);
	vm.runInContext(source, context, { filename: "sales_invoice_dispute.js" });
	return handlers;
}

function refresh(doc, roles) {
	const buttons = [];
	const frm = {
		doc,
		get_field() {
			return null;
		},
		add_custom_button(label, fn, group) {
			buttons.push({ label, group, fn });
		},
	};
	for (const events of load(roles)) {
		events.refresh(frm);
	}
	return buttons;
}

const submitted = {
	docstatus: 1,
	name: "ASL-MNL-INV-0000000150",
	hero_dispute_status: "",
	hero_dispute: "",
};

test("a submitted invoice puts Dispute under the Create menu", () => {
	const buttons = refresh(submitted, ["Accounts Manager"]);
	assert.deepEqual(
		buttons.map((button) => ({ label: button.label, group: button.group })),
		[{ label: "Dispute", group: "Create" }]
	);
});

test("an open dispute stays Open Dispute under the Dispute menu", () => {
	const buttons = refresh(
		{
			...submitted,
			hero_dispute_status: "Open",
			hero_dispute: "DISP-0001",
		},
		["System Manager"]
	);
	assert.deepEqual(
		buttons.map((button) => ({ label: button.label, group: button.group })),
		[{ label: "Open Dispute", group: "Dispute" }]
	);
});

test("a draft invoice and a user without the role get no dispute button", () => {
	assert.deepEqual(refresh({ ...submitted, docstatus: 0 }, ["Accounts Manager"]), []);
	assert.deepEqual(refresh(submitted, ["Accounts User"]), []);
});
