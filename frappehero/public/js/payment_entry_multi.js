// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		set_queries(frm);
		set_allocation_editable(frm);
		if (frm.doc.docstatus === 0 && frm.doc.payment_type !== "Internal Transfer") {
			frm.add_custom_button(__("Get Outstanding Invoices"), () => get_outstanding(frm));
		}
	},

	company(frm) {
		set_queries(frm);
	},

	party_type(frm) {
		set_queries(frm);
	},

	party(frm) {
		set_queries(frm);
	},

	payment_type(frm) {
		set_queries(frm);
	},

	paid_from(frm) {
		queue_preview(frm);
	},

	paid_to(frm) {
		queue_preview(frm);
	},

	posting_date(frm) {
		queue_preview(frm);
	},

	source_exchange_rate(frm) {
		queue_preview(frm);
	},

	target_exchange_rate(frm) {
		queue_preview(frm);
	},

	paid_amount(frm) {
		queue_preview(frm);
	},

	received_amount(frm) {
		queue_preview(frm);
	},
});

frappe.ui.form.on("Payment Entry Reference", {
	hero_account(frm) {
		queue_preview(frm);
	},

	reference_doctype(frm) {
		queue_preview(frm);
	},

	reference_name(frm, cdt, cdn) {
		if (frm._hero_multi_lock) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row) {
			row.hero_account = "";
		}
		queue_preview(frm);
	},

	allocated_amount(frm) {
		queue_preview(frm);
	},

	hero_allocated_invoice_amount(frm) {
		queue_preview(frm);
	},

	hero_payment_rate(frm) {
		queue_preview(frm);
	},
});

function set_queries(frm) {
	const account_type = frm.doc.party_type === "Customer" ? "Receivable" : "Payable";
	frm.set_query("hero_account", "references", () => ({
		filters: {
			company: frm.doc.company,
			is_group: 0,
			account_type,
		},
	}));
	frm.set_query("reference_name", "references", (doc) => {
		const filters = {
			company: doc.company,
			docstatus: 1,
			outstanding_amount: [">", 0],
		};
		if (doc.party_type === "Customer") {
			filters.customer = doc.party;
		} else if (doc.party_type === "Supplier") {
			filters.supplier = doc.party;
		}
		return { filters };
	});
}

function get_outstanding(frm) {
	const bank = bank_account(frm);
	if (!frm.doc.company || !frm.doc.party_type || !frm.doc.party || !frm.doc.posting_date || !bank) {
		frappe.msgprint(__("Choose the company, party, posting date, and bank account first."));
		return;
	}
	if (frm.doc.payment_type !== "Pay" && frm.doc.payment_type !== "Receive") {
		frappe.msgprint(__("Multiple accounts are available on Pay and Receive."));
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
				payment_type: frm.doc.payment_type,
				bank_account: bank,
				party_account: party_account(frm),
				payment_exchange_rate: bank_rate(frm),
				paid_amount: bank_amount(frm),
			},
			freeze: true,
			callback(response) {
				const message = response && response.message;
				if (!message || !Array.isArray(message.references)) {
					return;
				}
				frm._hero_multi_lock = true;
				frm.clear_table("references");
				message.references.forEach((row) => {
					const child = frm.add_child("references");
					Object.assign(child, row);
				});
				apply_header(frm, message);
				frm._hero_multi_lock = false;
				frm.refresh_field("references");
				frm.refresh_fields();
				set_allocation_editable(frm);
				frm.dirty();
				frm._hero_multi_signature = input_signature(frm);
			},
		});
	};
	if ((frm.doc.references || []).some((row) => row.reference_name || row.allocated_amount)) {
		frappe.confirm(__("Replace the invoices on this payment?"), load);
		return;
	}
	load();
}

function queue_preview(frm) {
	if (frm._hero_multi_lock || frm.doc.docstatus || !needs_custom(frm)) {
		return;
	}
	if (frm._hero_multi_timer) {
		clearTimeout(frm._hero_multi_timer);
	}
	frm._hero_multi_timer = setTimeout(() => {
		frm._hero_multi_timer = null;
		preview(frm);
	}, 200);
}

function preview(frm) {
	if (!needs_custom(frm) || !bank_account(frm)) {
		return;
	}
	const signature = input_signature(frm);
	if (frm._hero_multi_signature === signature) {
		return;
	}
	const token = (frm._hero_multi_token || 0) + 1;
	frm._hero_multi_token = token;
	frappe
		.call({
			method: "frappehero.finance_desk.multi_currency_payment.preview",
			args: { payment: frm.doc },
		})
		.then((response) => {
			if (frm._hero_multi_token !== token) {
				return;
			}
			const message = response && response.message;
			if (!message || !Array.isArray(message.references)) {
				frm._hero_multi_signature = "";
				return;
			}
			frm._hero_multi_lock = true;
			apply_header(frm, message);
			apply_rows(frm, message.references);
			frm._hero_multi_lock = false;
			frm.refresh_fields();
			set_allocation_editable(frm);
			frm._hero_multi_signature = input_signature(frm);
		})
		.catch(() => {
			if (frm._hero_multi_token === token) {
				frm._hero_multi_signature = "";
			}
		});
}

function needs_custom(frm) {
	if (spans_accounts(frm)) {
		return true;
	}
	return (frm.doc.references || []).some(
		(row) =>
			row.hero_invoice_currency &&
			row.hero_account_currency &&
			row.hero_invoice_currency !== row.hero_account_currency &&
			(row.reference_name || row.hero_allocated_invoice_amount || row.allocated_amount)
	);
}

function set_allocation_editable(frm) {
	const field = frm.fields_dict.references;
	if (!field || !field.grid || !field.grid.update_docfield_property) {
		return;
	}
	field.grid.update_docfield_property("allocated_amount", "read_only", needs_custom(frm) ? 1 : 0);
}

function spans_accounts(frm) {
	const names = new Set();
	(frm.doc.references || []).forEach((row) => {
		if (row.hero_account && (row.reference_name || row.allocated_amount)) {
			names.add(row.hero_account);
		}
	});
	if (names.size > 1) {
		return true;
	}
	const party = party_account(frm);
	return Boolean(names.size === 1 && party && !names.has(party));
}

function bank_account(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.paid_to || "";
	}
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.paid_from || "";
	}
	return "";
}

function party_account(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.paid_from || "";
	}
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.paid_to || "";
	}
	return "";
}

function bank_rate(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.target_exchange_rate || 0;
	}
	return frm.doc.source_exchange_rate || 0;
}

function bank_amount(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.received_amount || 0;
	}
	return frm.doc.paid_amount || 0;
}

function input_signature(frm) {
	const rows = frm.doc.references || [];
	return JSON.stringify({
		company: frm.doc.company || "",
		party_type: frm.doc.party_type || "",
		party: frm.doc.party || "",
		payment_type: frm.doc.payment_type || "",
		posting_date: frm.doc.posting_date || "",
		bank_account: bank_account(frm),
		party_account: party_account(frm),
		bank_rate: bank_rate(frm),
		bank_amount: bank_amount(frm),
		rows: rows.map((row) => [
			row.hero_account || "",
			row.reference_doctype || "",
			row.reference_name || "",
			row.hero_allocated_invoice_amount || 0,
			row.allocated_amount || 0,
			row.hero_payment_rate || 0,
		]),
	});
}

function apply_header(frm, message) {
	[
		"paid_from",
		"paid_to",
		"paid_from_account_currency",
		"paid_to_account_currency",
		"paid_amount",
		"received_amount",
		"source_exchange_rate",
		"target_exchange_rate",
		"base_paid_amount",
		"base_received_amount",
		"difference_amount",
		"unallocated_amount",
		"hero_multi_account",
	].forEach((field) => {
		if (message[field] !== undefined && frm.fields_dict[field]) {
			frm.doc[field] = message[field];
		}
	});
	if (message.hero_multi_account !== undefined && frm.fields_dict.hero_multi_account) {
		frm.doc.hero_multi_account = message.hero_multi_account;
	}
}

function apply_rows(frm, rows) {
	const by_name = {};
	rows.forEach((row) => {
		by_name[(row.reference_doctype || "") + "::" + (row.reference_name || "")] = row;
	});
	(frm.doc.references || []).forEach((row) => {
		const found = by_name[(row.reference_doctype || "") + "::" + (row.reference_name || "")];
		if (!found) {
			return;
		}
		Object.assign(row, found);
	});
}
