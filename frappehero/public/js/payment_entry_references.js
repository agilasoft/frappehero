// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		watch_references(frm);
		queue_invoice_currency(frm);
	},

	party_type(frm) {
		queue_invoice_currency(frm);
	},

	party(frm) {
		queue_invoice_currency(frm);
	},
});

frappe.ui.form.on("Payment Entry Reference", {
	reference_doctype(frm) {
		queue_invoice_currency(frm);
	},

	reference_name(frm) {
		queue_invoice_currency(frm);
	},
});

function watch_references(frm) {
	const field = frm.fields_dict.references;
	if (!field || field._hero_invoice_watched) {
		return;
	}
	field._hero_invoice_watched = true;
	const grid = field.grid;
	const refresh = grid.refresh;
	grid.refresh = function (...args) {
		const result = refresh.apply(this, args);
		queue_invoice_currency(frm);
		return result;
	};
}

function queue_invoice_currency(frm) {
	if (frm._hero_invoice_timer) {
		clearTimeout(frm._hero_invoice_timer);
	}
	frm._hero_invoice_timer = setTimeout(() => {
		frm._hero_invoice_timer = null;
		fill_invoice_currency(frm);
	}, 100);
}

function fill_invoice_currency(frm) {
	const rows = frm.doc.references || [];
	const signature = JSON.stringify({
		party_type: frm.doc.party_type || "",
		party: frm.doc.party || "",
		rows: rows.map((row) => [row.reference_doctype || "", row.reference_name || ""]),
	});
	if (frm._hero_invoice_signature === signature) {
		return;
	}
	frm._hero_invoice_signature = signature;
	if (!rows.length || !rows.some((row) => row.reference_doctype && row.reference_name)) {
		apply_invoice_currency(
			frm,
			rows.map(() => ({ hero_invoice_currency: "", hero_invoice_amount: 0 }))
		);
		return;
	}
	const token = (frm._hero_invoice_token || 0) + 1;
	frm._hero_invoice_token = token;
	frappe
		.call({
			method: "frappehero.finance_desk.payment_reference.invoice_currency_for_references",
			args: {
				references: rows.map((row) => ({
					reference_doctype: row.reference_doctype,
					reference_name: row.reference_name,
				})),
				party_type: frm.doc.party_type,
				party: frm.doc.party,
			},
		})
		.then((response) => {
			if (frm._hero_invoice_token !== token) {
				return;
			}
			if (!response || !Array.isArray(response.message)) {
				frm._hero_invoice_signature = "";
				return;
			}
			apply_invoice_currency(frm, response.message);
		})
		.catch(() => {
			if (frm._hero_invoice_token === token) {
				frm._hero_invoice_signature = "";
			}
		});
}

function apply_invoice_currency(frm, columns) {
	const rows = frm.doc.references || [];
	let changed = false;
	rows.forEach((row, index) => {
		const column = columns[index] || { hero_invoice_currency: "", hero_invoice_amount: 0 };
		const currency = column.hero_invoice_currency || "";
		const amount = column.hero_invoice_amount || 0;
		if ((row.hero_invoice_currency || "") !== currency) {
			row.hero_invoice_currency = currency;
			changed = true;
		}
		if (Number(row.hero_invoice_amount) !== Number(amount)) {
			row.hero_invoice_amount = amount;
			changed = true;
		}
	});
	if (!changed || !frm.fields_dict.references) {
		return;
	}
	frm.refresh_field("references");
}
