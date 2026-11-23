const assert = require("node:assert/strict");
const test = require("node:test");

const status = require("../document_status.js");

const future = (date) => date > "2026-11-23";

function present(doc, extra) {
	return status.presentedIndicator(
		doc,
		Object.assign(
			{
				doctype: doc.doctype,
				stateField: "workflow_state",
				stateStyle: (state) =>
					({
						"Pending Approval": "Warning",
						Approved: "Success",
						Rejected: "Danger",
					})[state] || "",
				translate: (label, doctype) => label + ":" + doctype,
				isReleaseInFuture: future,
			},
			extra || {}
		)
	);
}

test("a draft sales invoice shows its workflow state in the status pill", () => {
	const indicator = present({
		doctype: "Sales Invoice",
		docstatus: 0,
		status: "Draft",
		workflow_state: "Pending Approval",
	});
	assert.deepEqual(indicator, [
		"Pending Approval:Sales Invoice",
		"orange",
		"workflow_state,=,Pending Approval",
	]);
});

test("a submitted sales invoice shows Paid, Overdue, and the other invoice statuses", () => {
	const cases = {
		Paid: "green",
		Unpaid: "orange",
		Overdue: "red",
		"Partly Paid": "yellow",
		"Credit Note Issued": "gray",
		Return: "gray",
		"Unpaid and Discounted": "orange",
		"Partly Paid and Discounted": "yellow",
		"Overdue and Discounted": "red",
		"Internal Transfer": "darkgrey",
	};
	for (const [name, color] of Object.entries(cases)) {
		const indicator = present({
			doctype: "Sales Invoice",
			docstatus: 1,
			status: name,
			workflow_state: "Approved",
		});
		assert.deepEqual(indicator, [name + ":Sales Invoice", color, "status,=," + name]);
	}
});

test("a draft without a workflow state stays Draft", () => {
	assert.deepEqual(
		present({ doctype: "Sales Invoice", docstatus: "0", status: "Draft", workflow_state: "  " }),
		["Draft:Sales Invoice", "red", "docstatus,=,0"]
	);
});

test("a cancelled document shows Cancelled", () => {
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 2,
			status: "Cancelled",
			workflow_state: "Rejected",
		}),
		["Cancelled:Purchase Invoice", "red", "docstatus,=,2"]
	);
});

test("a submitted purchase invoice uses the purchase status colors and hold labels", () => {
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 1,
			status: "Overdue",
			workflow_state: "Approved",
		}),
		["Overdue:Purchase Invoice", "red", "status,=,Overdue"]
	);
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 1,
			status: "Debit Note Issued",
			outstanding_amount: 5,
			on_hold: 1,
		}),
		["Debit Note Issued:Purchase Invoice", "gray", "status,=,Debit Note Issued"]
	);
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 1,
			status: "Unpaid",
			outstanding_amount: "12.50",
			on_hold: 1,
		}),
		["On Hold:Purchase Invoice", "darkgrey"]
	);
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 1,
			status: "Unpaid",
			outstanding_amount: 4,
			on_hold: "1",
			release_date: "2026-12-01",
		}),
		["Temporarily on Hold:Purchase Invoice", "darkgrey"]
	);
	assert.deepEqual(
		present({
			doctype: "Purchase Invoice",
			docstatus: 1,
			status: "Partly Paid",
			outstanding_amount: 4,
			on_hold: 1,
			release_date: "2026-11-23",
		}),
		["Partly Paid:Purchase Invoice", "yellow", "status,=,Partly Paid"]
	);
});

test("a submitted payment shows Submitted", () => {
	assert.deepEqual(
		present({
			doctype: "Payment Entry",
			docstatus: "1",
			status: "Submitted",
			workflow_state: "Approved",
		}),
		["Submitted:Payment Entry", "blue", "docstatus,=,1"]
	);
});

test("a draft payment shows the workflow state", () => {
	const indicator = present({
		doctype: "Payment Entry",
		docstatus: 0,
		status: "Draft",
		workflow_state: "Rejected",
	});
	assert.equal(indicator[0], "Rejected:Payment Entry");
	assert.equal(indicator[1], "red");
});

test("documents without a workflow keep the original indicator", () => {
	assert.equal(present({ doctype: "Sales Invoice", docstatus: 1, status: "Paid" }, { stateField: "" }), null);
	assert.equal(present({ doctype: "Journal Entry", docstatus: 0, workflow_state: "Pending" }), null);
	assert.equal(
		present({ doctype: "Sales Invoice", docstatus: 0, __unsaved: 1, workflow_state: "Pending Approval" }),
		null
	);
});

test("an unknown workflow style is gray", () => {
	const indicator = present({
		doctype: "Sales Invoice",
		docstatus: 0,
		workflow_state: "With Accounts",
	});
	assert.equal(indicator[1], "gray");
	assert.equal(indicator[2], "workflow_state,=,With Accounts");
});

test("the desk wrapper leaves other doctypes alone and merges these three", async () => {
	const seen = [];
	const added = [];
	const desk = {
		get_indicator(doc, doctype) {
			seen.push(doctype || doc.doctype);
			return ["Original", "blue", "status,=,Original"];
		},
		workflow: {
			get_state_fieldname(doctype) {
				return doctype === "Journal Entry" ? "" : "workflow_state";
			},
		},
		datetime: {
			nowdate: () => "2026-11-23",
			get_diff: (date, today) => (date > today ? 1 : 0),
		},
		views: {
			ListView: class {
				async set_fields() {
					added.push("base");
				}
				_add_field(field) {
					added.push(field);
				}
			},
		},
	};
	global.locals = { "Workflow State": { "Pending Approval": { style: "Warning" } } };
	status.install(desk);
	status.install(desk);

	assert.deepEqual(
		desk.get_indicator({ doctype: "Sales Invoice", docstatus: 0, workflow_state: "Pending Approval", status: "Draft" }),
		["Pending Approval", "orange", "workflow_state,=,Pending Approval"]
	);
	assert.deepEqual(
		desk.get_indicator({ doctype: "Sales Invoice", docstatus: 1, workflow_state: "Approved", status: "Overdue" }),
		["Overdue", "red", "status,=,Overdue"]
	);
	assert.deepEqual(desk.get_indicator({ doctype: "Journal Entry", docstatus: 1, status: "Submitted" }), [
		"Original",
		"blue",
		"status,=,Original",
	]);
	assert.deepEqual(seen, ["Journal Entry"]);

	const list = new desk.views.ListView();
	list.doctype = "Purchase Invoice";
	await list.set_fields();
	assert.deepEqual(added, ["base", "workflow_state"]);

	const other = new desk.views.ListView();
	other.doctype = "Journal Entry";
	await other.set_fields();
	assert.deepEqual(added, ["base", "workflow_state", "base"]);
	delete global.locals;
});
