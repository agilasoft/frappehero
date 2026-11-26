// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		set_queries(frm);
		hide_calculated_amounts(frm);
		ensure_company_currency(frm);
		if (is_draft(frm) && frm.doc.payment_type !== "Internal Transfer") {
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

	account(frm, cdt, cdn) {
		if (frm._hero_multi_lock) {
			return;
		}
		const row = locals[cdt][cdn];
		if (!row || !row.account || row.account === row.hero_account) {
			return;
		}
		frm._hero_multi_lock = true;
		frappe.model.set_value(cdt, cdn, "hero_account", row.account).finally(() => {
			frm._hero_multi_lock = false;
			queue_preview(frm);
		});
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
			if (row.reference_name) {
				row.hero_allocation_basis = "Invoice";
				row._hero_ref_fill = true;
			} else {
				delete row._hero_ref_fill;
			}
		}
		stamp_payment_currency(frm);
		queue_preview(frm);
	},

	allocated_amount(frm, cdt, cdn) {
		if (frm._hero_multi_lock) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row && row._hero_ref_fill) {
			delete row._hero_ref_fill;
		}
		queue_preview(frm);
	},

	hero_allocated_invoice_amount(frm, cdt, cdn) {
		if (frm._hero_multi_lock || !is_draft(frm)) {
			return;
		}
		ensure_company_currency(frm);
		const row = locals[cdt][cdn];
		if (row) {
			row.hero_allocation_basis = "Invoice";
			row._hero_convert = true;
			delete row._hero_ref_fill;
		}
		convert_allocation(frm, cdt, cdn);
		queue_preview(frm);
	},

	hero_payment_rate(frm) {
		queue_preview(frm);
	},
});

const HIDDEN_REFERENCE_FIELDS = [
	"total_amount",
	"outstanding_amount",
	"allocated_amount",
	"account",
	"account_type",
	"payment_type",
	"exchange_rate",
	"exchange_gain_loss",
	"hero_account",
	"hero_account_currency",
	"hero_allocated_account_amount",
	"hero_booked_rate",
	"hero_payment_rate",
	"hero_payment_currency",
	"hero_bank_amount",
	"hero_allocation_basis",
];

function hide_calculated_amounts(frm) {
	const grid = frm.fields_dict.references && frm.fields_dict.references.grid;
	if (!grid || grid._hero_amounts_hidden || !frappe.meta) {
		return;
	}
	grid._hero_amounts_hidden = true;
	HIDDEN_REFERENCE_FIELDS.forEach((fieldname) => {
		const field = frappe.meta.get_docfield("Payment Entry Reference", fieldname, frm.doc.name);
		if (!field) {
			return;
		}
		field.hidden = 1;
		field.read_only = 1;
		field.in_list_view = 0;
	});
	if (typeof grid.setup_visible_columns === "function") {
		grid.setup_visible_columns();
	}
}

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
					child.hero_allocation_basis = "Invoice";
				});
				apply_header(frm, message);
				frm.refresh_field("references");
				frm.refresh_fields();
				frm._hero_multi_signature = input_signature(frm);
				frm._hero_multi_lock = false;
				frm.dirty();
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
			Promise.resolve(apply_rows(frm, message.references)).finally(() => {
				frm.refresh_fields();
				frm._hero_multi_signature = input_signature(frm);
				frm._hero_multi_lock = false;
			});
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
	const party = party_currency(frm);
	return (frm.doc.references || []).some((row) => {
		const invoice = row.hero_invoice_currency;
		const account = row.hero_account_currency || party;
		return (
			invoice &&
			account &&
			invoice !== account &&
			(row.reference_name || row.hero_allocated_invoice_amount || row.allocated_amount)
		);
	});
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

function party_currency(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.paid_from_account_currency || "";
	}
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.paid_to_account_currency || "";
	}
	return "";
}

function party_exchange_rate(frm) {
	const currency = party_currency(frm);
	if (frm._hero_company_currency && currency === frm._hero_company_currency) {
		return 1;
	}
	const rate =
		frm.doc.payment_type === "Receive" ? frm.doc.source_exchange_rate : frm.doc.target_exchange_rate;
	const number = Number(rate);
	return number > 0 ? number : 0;
}

function ensure_company_currency(frm) {
	if (frm._hero_company_currency || frm._hero_company_currency_loading || !frm.doc.company || !frappe.db) {
		return;
	}
	frm._hero_company_currency_loading = true;
	frappe.db.get_value("Company", frm.doc.company, "default_currency").then((response) => {
		frm._hero_company_currency_loading = false;
		const message = response && response.message;
		frm._hero_company_currency = (message && message.default_currency) || "";
		convert_open_rows(frm);
	});
}

function money(value) {
	const number = Number(value);
	if (!isFinite(number)) {
		return 0;
	}
	return flt(number, 2);
}

function paying_currency(frm) {
	if (frm.doc.payment_type === "Receive") {
		return frm.doc.paid_to_account_currency || "";
	}
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.paid_from_account_currency || "";
	}
	return "";
}

function stamp_payment_currency(frm) {
	const currency = paying_currency(frm);
	if (!currency) {
		return;
	}
	(frm.doc.references || []).forEach((row) => {
		row.hero_payment_currency = currency;
	});
}

function invoice_rate(row) {
	const payment = Number(row.hero_payment_rate);
	if (payment > 0) {
		return payment;
	}
	const booked = Number(row.hero_booked_rate);
	return booked > 0 ? booked : 0;
}

function paying_rate(frm) {
	const currency = paying_currency(frm);
	if (frm._hero_company_currency && currency === frm._hero_company_currency) {
		return 1;
	}
	const rate = Number(bank_rate(frm));
	return rate > 0 ? rate : 0;
}

function is_draft(frm) {
	const status = frm.doc && frm.doc.docstatus;
	return status == null || status === "" || Number(status) === 0;
}

function convert_allocation(frm, cdt, cdn) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || frm._hero_multi_lock || !row._hero_convert || !is_draft(frm)) {
		return;
	}
	stamp_payment_currency(frm);
	const invoiceCurrency = row.hero_invoice_currency || "";
	const payingCurrency = paying_currency(frm);
	if (!invoiceCurrency || !payingCurrency) {
		return;
	}
	let invoiceAmount;
	let payingAmount;
	if (invoiceCurrency === payingCurrency) {
		invoiceAmount = money(row.hero_allocated_invoice_amount);
		payingAmount = invoiceAmount;
	} else {
		const rate = invoice_rate(row);
		const bankRate = paying_rate(frm);
		if (!(rate > 0) || !(bankRate > 0)) {
			return;
		}
		invoiceAmount = money(row.hero_allocated_invoice_amount);
		payingAmount = money((invoiceAmount * rate) / bankRate);
	}
	write_allocation(
		frm,
		cdt,
		cdn,
		invoiceAmount,
		payingAmount,
		party_amount(frm, row, invoiceAmount, payingAmount),
		account_amount(frm, row, invoiceAmount, payingAmount)
	);
	if (!frm.doc.company || frm._hero_company_currency) {
		delete row._hero_convert;
	}
}

function party_amount(frm, row, invoiceAmount, payingAmount) {
	const party = party_currency(frm);
	const paying = paying_currency(frm);
	const invoice = row.hero_invoice_currency || "";
	if (!party) {
		return null;
	}
	if (party === paying) {
		return payingAmount;
	}
	if (party === invoice) {
		return invoiceAmount;
	}
	const booked = Number(row.hero_booked_rate) || 0;
	const partyRate = party_exchange_rate(frm);
	if (!(booked > 0)) {
		return null;
	}
	if (frm._hero_company_currency && party === frm._hero_company_currency) {
		return money(invoiceAmount * booked);
	}
	if (!(partyRate > 0)) {
		return null;
	}
	return money((invoiceAmount * booked) / partyRate);
}

function account_amount(frm, row, invoiceAmount, payingAmount) {
	const accountCurrency = row.hero_account_currency || "";
	const invoiceCurrency = row.hero_invoice_currency || "";
	const paying = paying_currency(frm);
	if (!accountCurrency) {
		return null;
	}
	if (accountCurrency === invoiceCurrency) {
		return invoiceAmount;
	}
	if (accountCurrency === paying) {
		return payingAmount;
	}
	const booked = Number(row.hero_booked_rate) || 0;
	if (booked > 0 && frm._hero_company_currency && accountCurrency === frm._hero_company_currency) {
		return money(invoiceAmount * booked);
	}
	return null;
}

function write_allocation(frm, cdt, cdn, invoiceAmount, payingAmount, partyAmount, accountAmount) {
	const row = locals[cdt][cdn];
	frm._hero_multi_lock = true;
	const writes = [];
	if (Number(row.hero_allocated_invoice_amount) !== Number(invoiceAmount)) {
		writes.push(frappe.model.set_value(cdt, cdn, "hero_allocated_invoice_amount", invoiceAmount));
	}
	if (Number(row.hero_bank_amount) !== Number(payingAmount)) {
		writes.push(frappe.model.set_value(cdt, cdn, "hero_bank_amount", payingAmount));
	}
	if (partyAmount !== null && Number(row.allocated_amount) !== Number(partyAmount)) {
		writes.push(frappe.model.set_value(cdt, cdn, "allocated_amount", partyAmount));
	}
	if (accountAmount !== null && Number(row.hero_allocated_account_amount) !== Number(accountAmount)) {
		writes.push(frappe.model.set_value(cdt, cdn, "hero_allocated_account_amount", accountAmount));
	}
	Promise.all(writes).finally(() => {
		frm._hero_multi_lock = false;
	});
}

// Invoice currency is loaded for display when a payment opens. Only a row whose
// allocated invoice amount was edited in this session is converted. Rewriting
// every saved row marks the voucher Not Saved and replaces the allocation that
// print and the next save would keep.
function convert_open_rows(frm) {
	if (!is_draft(frm)) {
		return;
	}
	(frm.doc.references || []).forEach((row) => {
		if (!row || !row._hero_convert || !row.doctype || !row.name) {
			return;
		}
		convert_allocation(frm, row.doctype, row.name);
	});
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
			row.hero_allocation_basis || "",
			row.hero_allocated_invoice_amount || 0,
			row.hero_bank_amount || 0,
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
	const writes = [];
	(frm.doc.references || []).forEach((row) => {
		const found = by_name[(row.reference_doctype || "") + "::" + (row.reference_name || "")];
		if (!found) {
			return;
		}
		Object.assign(row, found);
		if (!row.doctype || !row.name) {
			return;
		}
		["hero_allocated_invoice_amount", "hero_bank_amount", "allocated_amount", "hero_allocated_account_amount"].forEach(
			(field) => {
				if (found[field] !== undefined) {
					writes.push(frappe.model.set_value(row.doctype, row.name, field, found[field]));
				}
			}
		);
	});
	return Promise.all(writes);
}
