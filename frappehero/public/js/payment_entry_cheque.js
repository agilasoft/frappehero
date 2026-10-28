// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		frm.set_query("hero_cheque_leaf", () => {
			const filters = { status: "Active" };
			if (frm.doc.bank_account) {
				filters.bank_account = frm.doc.bank_account;
			}
			if (frm.doc.company) {
				filters.company = frm.doc.company;
			}
			return { filters };
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.doc.payment_type !== "Pay") {
			return;
		}
		frm.add_custom_button(__("Assign Cheque Number"), () => assign_cheque(frm), __("Cheque"));
	},

	async payment_type(frm) {
		if (frm.doc.payment_type !== "Pay") {
			await clear_cheque(frm);
			return;
		}
		await suggest_cheque(frm);
	},

	async bank_account(frm) {
		await clear_cheque(frm);
		await suggest_cheque(frm);
	},

	async mode_of_payment(frm) {
		if (frm.__cheque_silent || frm.doc.docstatus !== 0 || frm.doc.payment_type !== "Pay") {
			return;
		}
		if (!frm.doc.bank_account) {
			return;
		}
		const preview = await load_preview(frm);
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
	if (frm.__cheque_silent || frm.doc.docstatus !== 0 || frm.doc.payment_type !== "Pay") {
		return;
	}
	if (!frm.doc.bank_account && !frm.doc.hero_cheque_leaf) {
		return;
	}
	const preview = await load_preview(frm);
	if (!preview) {
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
	if (frm.doc.payment_type !== "Pay") {
		return;
	}
	if (!frm.doc.bank_account) {
		frappe.msgprint(__("Set the company bank account before assigning a cheque number."));
		return;
	}
	const preview = await load_preview(frm);
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

function load_preview(frm) {
	return frappe
		.call({
			method: "frappehero.finance_desk.cheque.suggest_cheque",
			args: {
				bank_account: frm.doc.bank_account,
				company: frm.doc.company,
				mode_of_payment: frm.doc.mode_of_payment,
				leaf: frm.doc.hero_cheque_leaf,
			},
		})
		.then((response) => response.message);
}
