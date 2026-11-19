const assert = require("node:assert/strict");
const test = require("node:test");

const proof = require("../proof_app.js");

const payment = {
	name: "ATN-MNL-CV-00000000137",
	party_name: "PREMIER GLOBAL LOGISTICS CORP.",
	party_type: "Supplier",
	party: "PREMIER GLOBAL LOGISTICS CORP.",
	posting_date: "2026-11-12",
	payment_type: "Pay",
	docstatus: 1,
	mode_of_payment: "Cheque",
	reference_no: "0001115478",
	reference_date: "2026-11-12",
	company: "ALL TRANSPORT NETWORK, INC.",
	amount: 5512.65,
	currency: "PHP",
	allocated_currency: "PHP",
	proof_of_payment: "/private/files/slip.jpg",
	proof_uploaded_by: "Administrator",
	proof_uploaded_on: "2026-11-13 07:34:48",
	can_upload: true,
	references: [
		{
			reference_doctype: "Purchase Invoice",
			reference_name: "ATN-MNL-APV-00000000048",
			allocated_amount: 5512.65,
			invoice_currency: "PHP",
			invoice_amount: 5512.65,
		},
	],
};

test("currency is plain text, not a desk formatter div", () => {
	const html = proof.renderDetailHtml(payment, "mm-dd-yyyy");
	assert.equal(html.includes("style="), false);
	assert.equal(html.includes("text-align"), false);
	assert.equal(html.includes("<div style"), false);
	assert.ok(html.includes("5,512.65") || html.includes("5512.65"));
});

test("the party type sits on its own line", () => {
	const html = proof.renderDetailHtml(payment, "mm-dd-yyyy");
	assert.match(html, /who-name">PREMIER GLOBAL LOGISTICS CORP\.</);
	assert.match(html, /who-type">Supplier</);
	assert.equal(html.includes("CORP.Supplier"), false);
	assert.match(html, /ATN-MNL-APV-00000000048/);
	assert.match(html, /Purchase Invoice/);
	assert.match(html, /11-12-2026/);
	assert.match(html, /Uploaded by Administrator · 11-13-2026 07:34/);
});

test("a different invoice currency is shown once", () => {
	const row = Object.assign({}, payment, {
		references: [
			{
				reference_doctype: "Purchase Invoice",
				reference_name: "PINV-1",
				allocated_amount: 1000,
				invoice_currency: "USD",
				invoice_amount: 18,
			},
		],
	});
	const html = proof.renderDetailHtml(row, "yyyy-mm-dd");
	assert.match(html, /Invoice /);
	assert.match(html, /18\.00/);
});

test("pending cards escape the name and keep the amount as text", () => {
	const html = proof.renderPendingHtml(
		[{ name: "PE&1", party: "North <Store>", posting_date: "2026-11-01", amount: 10, currency: "PHP" }],
		"yyyy-mm-dd"
	);
	assert.match(html, /data-name="PE&amp;1"/);
	assert.match(html, /North &lt;Store&gt;/);
	assert.equal(html.includes("<div"), false);
});

test("an empty list says nothing is waiting", () => {
	assert.match(proof.renderPendingHtml([], "yyyy-mm-dd"), /Nothing is waiting on you/);
});

test("server messages drop markup", () => {
	const raw = JSON.stringify([JSON.stringify({ message: "Payment <b>missing</b>." })]);
	assert.equal(proof.serverMessage({ _server_messages: raw }), "Payment missing.");
	assert.equal(proof.serverMessage({}), "");
});

test("file rules match the upload limit", () => {
	assert.equal(proof.fileError({ name: "slip.JPG", size: 12 }), "");
	assert.equal(proof.fileError({ name: "slip.gif", size: 12 }), "Use a JPEG, PNG, WebP, or PDF.");
	assert.equal(proof.fileError({ name: "slip.pdf", size: 10 * 1024 * 1024 + 1 }), "The file must be 10 MB or smaller.");
});
