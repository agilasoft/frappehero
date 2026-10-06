// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		if (!frappe.user.has_role("System Manager") && !frappe.user.has_role("Accounts Manager")) {
			return;
		}
		if (frm.doc.hero_dispute_status === "Open" && frm.doc.hero_dispute) {
			frm.add_custom_button(
				__("Open Dispute"),
				() => frappe.set_route("Form", "Hero Dispute", frm.doc.hero_dispute),
				__("Dispute")
			);
			return;
		}
		frm.add_custom_button(__("Raise Dispute"), () => raise_dispute(frm), __("Dispute"));
	},
});

function raise_dispute(frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				reqd: 1,
			},
		],
		async (values) => {
			const dispute = await frappe.call({
				method: "frappehero.dispute_desk.api.raise_dispute",
				args: {
					reference_doctype: "Sales Invoice",
					reference_name: frm.doc.name,
					sales_invoice: frm.doc.name,
					company: frm.doc.company,
					customer: frm.doc.customer,
					reason: values.reason,
					source_module: "ERPNext",
				},
			});
			await frm.reload_doc();
			frappe.show_alert({
				message: __("Dispute opened. Holds, collection, and dunning on this invoice were released."),
				indicator: "green",
			});
			if (dispute.message && dispute.message.name) {
				frappe.set_route("Form", "Hero Dispute", dispute.message.name);
			}
		},
		__("Raise Dispute"),
		__("Raise")
	);
}
