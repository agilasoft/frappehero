// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

const CHEQUE_PAYMENT_TYPES = ["Pay", "Internal Transfer"];

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		frm.set_query("hero_cheque_leaf", () => {
			const filters = { status: "Active" };
			const bank = known_bank_account(frm);
			if (bank) {
				filters.bank_account = bank;
			}
			if (frm.doc.company) {
				filters.company = frm.doc.company;
			}
			return { filters };
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 0 || !draws_cheque(frm)) {
			return;
		}
		frm.add_custom_button(__("Assign Cheque Number"), () => assign_cheque(frm), __("Cheque"));
	},

	async payment_type(frm) {
		forget_bank_account(frm);
		if (!draws_cheque(frm)) {
			await clear_cheque(frm);
			return;
		}
		await clear_cheque(frm);
		await suggest_cheque(frm);
	},

	async bank_account(frm) {
		if (frm.doc.payment_type !== "Pay") {
			return;
		}
		await clear_cheque(frm);
		await suggest_cheque(frm);
	},

	async paid_from(frm) {
		if (frm.doc.payment_type !== "Internal Transfer") {
			return;
		}
		forget_bank_account(frm);
		await clear_cheque(frm);
		await suggest_cheque(frm);
	},

	async company(frm) {
		if (frm.doc.payment_type !== "Internal Transfer") {
			return;
		}
		forget_bank_account(frm);
		await clear_cheque(frm);
		await suggest_cheque(frm);
	},

	async mode_of_payment(frm) {
		if (frm.__cheque_silent || frm.doc.docstatus !== 0 || !draws_cheque(frm)) {
			return;
		}
		const bank = await source_bank_account(frm);
		if (!bank) {
			return;
		}
		const preview = await load_preview(frm, bank);
		if (preview && !preview.uses_cheque) {
			await clear_cheque(frm);
			return;
		}
		await suggest_cheque(frm);
	},

	hero_cheque_leaf(frm) {
		suggest_cheque(frm, true);
	},
});

function draws_cheque(frm) {
	return CHEQUE_PAYMENT_TYPES.includes(frm.doc.payment_type);
}

function forget_bank_account(frm) {
	frm.__cheque_bank_account = "";
	frm.__cheque_bank_for = "";
	frm.__cheque_bank_company = "";
	frm.__cheque_bank_resolved = false;
}

function known_bank_account(frm) {
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.bank_account || "";
	}
	if (frm.doc.payment_type !== "Internal Transfer") {
		return "";
	}
	if (frm.__cheque_bank_resolved && frm.__cheque_bank_for === (frm.doc.paid_from || "")) {
		return frm.__cheque_bank_account || "";
	}
	return frm.doc.paid_from_bank_account || "";
}

function bank_missing_message(frm) {
	if (frm.doc.payment_type === "Internal Transfer") {
		return __("Link Account Paid From to a Bank Account before assigning a cheque number.");
	}
	return __("Set the company bank account before assigning a cheque number.");
}

async function source_bank_account(frm) {
	if (frm.doc.payment_type === "Pay") {
		return frm.doc.bank_account || "";
	}
	if (frm.doc.payment_type !== "Internal Transfer") {
		return "";
	}
	const account = frm.doc.paid_from || "";
	const company = frm.doc.company || "";
	if (!account) {
		forget_bank_account(frm);
		return "";
	}
	if (
		frm.__cheque_bank_resolved &&
		frm.__cheque_bank_for === account &&
		frm.__cheque_bank_company === company
	) {
		return frm.__cheque_bank_account || "";
	}
	const filters = { account, disabled: 0 };
	if (company) {
		filters.company = company;
	}
	const response = await frappe.db.get_value("Bank Account", filters, "name");
	if (frm.doc.paid_from !== account || (frm.doc.company || "") !== company) {
		return "";
	}
	const name = (response && response.message && response.message.name) || "";
	frm.__cheque_bank_account = name;
	frm.__cheque_bank_for = account;
	frm.__cheque_bank_company = company;
	frm.__cheque_bank_resolved = true;
	return name;
}

async function clear_cheque(frm) {
	if (frm.__cheque_silent || (!frm.doc.hero_cheque_leaf && !frm.doc.hero_cheque_number)) {
		return;
	}
	frm.__cheque_silent = true;
	await frm.set_value("hero_cheque_leaf", "");
	await frm.set_value("hero_cheque_number", "");
	frm.__cheque_silent = false;
}

async function suggest_cheque(frm, leafChanged) {
	if (frm.__cheque_silent || frm.doc.docstatus !== 0 || !draws_cheque(frm)) {
		return;
	}
	frm.__cheque_generation = (frm.__cheque_generation || 0) + 1;
	const generation = frm.__cheque_generation;
	const bank = await source_bank_account(frm);
	if (frm.__cheque_silent || generation !== frm.__cheque_generation) {
		return;
	}
	if (!bank && !frm.doc.hero_cheque_leaf) {
		return;
	}
	const preview = await load_preview(frm, bank);
	if (frm.__cheque_silent || generation !== frm.__cheque_generation || !preview) {
		return;
	}
	if (preview.error && (frm.doc.hero_cheque_leaf || preview.uses_cheque)) {
		frappe.show_alert({ message: preview.error, indicator: "orange" });
	}
	frm.__cheque_silent = true;
	if (preview.leaf && !frm.doc.hero_cheque_leaf) {
		await frm.set_value("hero_cheque_leaf", preview.leaf);
	}
	if (leafChanged && !preview.cheque_number) {
		await frm.set_value("hero_cheque_number", "");
	} else if (preview.cheque_number && (leafChanged || !frm.doc.hero_cheque_number)) {
		await frm.set_value("hero_cheque_number", preview.cheque_number);
	}
	frm.__cheque_silent = false;
}

async function assign_cheque(frm) {
	if (!draws_cheque(frm)) {
		return;
	}
	const bank = await source_bank_account(frm);
	if (!bank) {
		frappe.msgprint(bank_missing_message(frm));
		return;
	}
	const preview = await load_preview(frm, bank);
	if (!preview || preview.error) {
		frappe.msgprint(
			(preview && preview.error) || __("Choose an active Cheque Leaf for this bank account.")
		);
		return;
	}
	if (!preview.available || !preview.available.length) {
		frappe.msgprint(__("This Cheque Leaf has no available cheque numbers."));
		return;
	}
	frappe.prompt(
		[
			{
				fieldname: "cheque_number",
				fieldtype: "Select",
				label: __("Cheque Number"),
				options: preview.available.join("\n"),
				reqd: 1,
				default: frm.doc.hero_cheque_number || preview.cheque_number,
			},
		],
		async (values) => {
			frm.__cheque_silent = true;
			await frm.set_value("hero_cheque_leaf", preview.leaf);
			await frm.set_value("hero_cheque_number", values.cheque_number);
			frm.__cheque_silent = false;
		},
		__("Assign Cheque Number"),
		__("Assign")
	);
}

function load_preview(frm, bank) {
	return frappe
		.call({
			method: "frappehero.finance_desk.cheque.suggest_cheque",
			args: {
				bank_account: bank || "",
				company: frm.doc.company,
				mode_of_payment: frm.doc.mode_of_payment,
				leaf: frm.doc.hero_cheque_leaf,
			},
		})
		.then((response) => response.message);
}
