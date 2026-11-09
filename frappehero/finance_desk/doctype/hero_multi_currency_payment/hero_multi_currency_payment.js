// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Multi Currency Payment", {
	refresh(frm) {
		set_queries(frm);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Outstanding Invoices"), () => get_outstanding(frm));
		}
	},

	company(frm) {
		set_queries(frm);
		clear_allocations(frm);
	},

	party_type(frm) {
		frm.set_value("party", "");
		frm.set_value("payment_type", payment_type_for(frm.doc.party_type));
		set_queries(frm);
		clear_allocations(frm);
	},

	party(frm) {
		clear_allocations(frm);
	},

	bank_account(frm) {
		if (!frm.doc.bank_account) {
			frm.set_value("payment_currency", "");
			return;
		}
		frappe.db.get_value("Account", frm.doc.bank_account, "account_currency").then((response) => {
			const currency = response && response.message && response.message.account_currency;
			if (currency && frm.doc.payment_currency !== currency) {
				frm.set_value("payment_currency", currency);
				return;
			}
			queue_preview(frm);
		});
	},

	payment_currency(frm) {
		queue_preview(frm);
	},

	posting_date(frm) {
		queue_preview(frm);
	},

	payment_exchange_rate(frm) {
		queue_preview(frm);
	},

	paid_amount(frm) {
		queue_preview(frm);
	},

	advance_account(frm) {
		queue_preview(frm);
	},

	advance_exchange_rate(frm) {
		queue_preview(frm);
	},
});

frappe.ui.form.on("Hero Multi Currency Allocation", {
	account(frm) {
		queue_preview(frm);
	},

	reference_doctype(frm) {
		queue_preview(frm);
	},

	reference_name(frm) {
		queue_preview(frm);
	},

	allocated_amount(frm) {
		queue_preview(frm);
	},

	payment_rate(frm) {
		queue_preview(frm);
	},
});

function payment_type_for(party_type) {
	if (party_type === "Customer") {
		return "Receive";
	}
	if (party_type === "Supplier") {
		return "Pay";
	}
	return "";
}

function set_queries(frm) {
	const account_type = frm.doc.party_type === "Customer" ? "Receivable" : "Payable";
	frm.set_query("bank_account", () => ({
		filters: {
			company: frm.doc.company,
			is_group: 0,
			account_type: ["in", ["Bank", "Cash"]],
		},
	}));
	frm.set_query("advance_account", () => ({
		filters: {
			company: frm.doc.company,
			is_group: 0,
			account_type,
		},
	}));
	frm.set_query("account", "allocations", () => ({
		filters: {
			company: frm.doc.company,
			is_group: 0,
			account_type,
		},
	}));
	frm.set_query("reference_name", "allocations", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		const filters = {
			company: doc.company,
			docstatus: 1,
			outstanding_amount: [">", 0],
		};
		if (row.reference_doctype === "Sales Invoice") {
			filters.customer = doc.party;
		} else if (row.reference_doctype === "Purchase Invoice") {
			filters.supplier = doc.party;
		}
		return { filters };
	});
}

function clear_allocations(frm) {
	if (frm._hero_payment_lock) {
		return;
	}
	frm.clear_table("allocations");
	frm.refresh_field("allocations");
	frm._hero_payment_signature = "";
}

function get_outstanding(frm) {
	if (!frm.doc.company || !frm.doc.party_type || !frm.doc.party || !frm.doc.posting_date || !frm.doc.bank_account) {
		frappe.msgprint(__("Choose the company, party, posting date, and bank account first."));
		return;
	}
	const load = () => {
		frappe.call({
			method: "frappehero.finance_desk.multi_currency_payment.outstanding_invoices",
			args: {
				company: frm.doc.company,
				party_type: frm.doc.party_type,
				party: frm.doc.party,
				posting_date: frm.doc.posting_date,
				bank_account: frm.doc.bank_account,
				payment_exchange_rate: frm.doc.payment_exchange_rate,
			},
			freeze: true,
			callback(response) {
				const message = response && response.message;
				if (!message || !Array.isArray(message.allocations)) {
					return;
				}
				frm._hero_payment_lock = true;
				frm.clear_table("allocations");
				message.allocations.forEach((row) => frm.add_child("allocations", row));
				apply_header(frm, message);
				frm._hero_payment_lock = false;
				frm.refresh_field("allocations");
				frm.dirty();
				frm._hero_payment_signature = input_signature(frm);
			},
		});
	};
	if ((frm.doc.allocations || []).length) {
		frappe.confirm(__("Replace the invoices on this payment?"), load);
		return;
	}
	load();
}

function queue_preview(frm) {
	if (frm._hero_payment_lock || frm.doc.docstatus) {
		return;
	}
	if (frm._hero_payment_timer) {
		clearTimeout(frm._hero_payment_timer);
	}
	frm._hero_payment_timer = setTimeout(() => {
		frm._hero_payment_timer = null;
		preview(frm);
	}, 200);
}

function preview(frm) {
	if (!ready(frm)) {
		return;
	}
	const signature = input_signature(frm);
	if (frm._hero_payment_signature === signature) {
		return;
	}
	const token = (frm._hero_payment_token || 0) + 1;
	frm._hero_payment_token = token;
	frappe
		.call({
			method: "frappehero.finance_desk.multi_currency_payment.preview",
			args: { payment: frm.doc },
		})
		.then((response) => {
			if (frm._hero_payment_token !== token) {
				return;
			}
			const message = response && response.message;
			if (!message || !Array.isArray(message.allocations)) {
				frm._hero_payment_signature = "";
				return;
			}
			frm._hero_payment_lock = true;
			apply_header(frm, message);
			apply_rows(frm, message.allocations);
			frm._hero_payment_lock = false;
			frm.refresh_fields();
			frm._hero_payment_signature = input_signature(frm);
		})
		.catch(() => {
			if (frm._hero_payment_token === token) {
				frm._hero_payment_signature = "";
			}
		});
}

function ready(frm) {
	const rows = frm.doc.allocations || [];
	return Boolean(
		frm.doc.company &&
			frm.doc.party_type &&
			frm.doc.party &&
			frm.doc.posting_date &&
			frm.doc.bank_account &&
			rows.some((row) => row.reference_name || row.allocated_amount)
	);
}

function input_signature(frm) {
	const rows = frm.doc.allocations || [];
	return JSON.stringify({
		company: frm.doc.company || "",
		party_type: frm.doc.party_type || "",
		party: frm.doc.party || "",
		posting_date: frm.doc.posting_date || "",
		bank_account: frm.doc.bank_account || "",
		payment_exchange_rate: frm.doc.payment_exchange_rate || 0,
		paid_amount: frm.doc.paid_amount || 0,
		advance_account: frm.doc.advance_account || "",
		advance_exchange_rate: frm.doc.advance_exchange_rate || 0,
		rows: rows.map((row) => [
			row.account || "",
			row.reference_doctype || "",
			row.reference_name || "",
			row.allocated_amount || 0,
			row.payment_rate || 0,
		]),
	});
}

function apply_header(frm, message) {
	[
		"payment_type",
		"payment_currency",
		"company_currency",
		"payment_exchange_rate",
		"paid_amount",
		"allocated_amount",
		"unallocated_amount",
		"base_paid_amount",
		"exchange_gain_loss",
		"multi_currency",
		"advance_currency",
		"advance_exchange_rate",
		"advance_amount",
	].forEach((field) => {
		if (message[field] !== undefined) {
			frm.doc[field] = message[field];
		}
	});
}

function apply_rows(frm, rows) {
	const by_name = {};
	rows.forEach((row) => {
		by_name[(row.reference_doctype || "") + "::" + (row.reference_name || "")] = row;
	});
	(frm.doc.allocations || []).forEach((row) => {
		const found = by_name[(row.reference_doctype || "") + "::" + (row.reference_name || "")];
		if (!found) {
			return;
		}
		[
			"account",
			"account_currency",
			"reference_doctype",
			"reference_name",
			"invoice_currency",
			"outstanding_amount",
			"allocated_amount",
			"booked_rate",
			"payment_rate",
			"payment_currency",
			"payment_amount",
		].forEach((field) => {
			if (found[field] !== undefined) {
				row[field] = found[field];
			}
		});
	});
}
