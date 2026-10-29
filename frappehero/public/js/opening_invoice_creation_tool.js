// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

// Credit Note and Debit Note on Opening Invoice Creation Tool.
// The posting rules live in frappehero/finance_desk/opening_invoice_logic.py.

frappe.provide("frappehero");

const NOTE_TYPES = {
	"Credit Note": {
		party_type: "Customer",
		id_label: "Customer ID",
		name_label: "Customer Name",
		item_name: "Opening Credit Note",
		banner: __(
			"Each row becomes a Credit Note: a return Sales Invoice. Enter the amount as a positive number. Against Invoice links a submitted sales invoice in this company. Any other number is stored on the note."
		),
		created: __("Opening Credit Notes have been created."),
		freeze: __("Creating Credit Notes ..."),
	},
	"Debit Note": {
		party_type: "Supplier",
		id_label: "Supplier ID",
		name_label: "Supplier Name",
		item_name: "Opening Debit Note",
		banner: __(
			"Each row becomes a Debit Note: a return Purchase Invoice. Enter the amount as a positive number. Against Invoice links a submitted purchase invoice in this company. Any other number is stored on the note."
		),
		created: __("Opening Debit Notes have been created."),
		freeze: __("Creating Debit Notes ..."),
	},
};

const PARTY_TYPES = {
	Sales: {
		party_type: "Customer",
		id_label: "Customer ID",
		name_label: "Customer Name",
		missing: __("If party does not exist, create it using the Customer Name field."),
		freeze: __("Creating Sales Invoices ..."),
	},
	Purchase: {
		party_type: "Supplier",
		id_label: "Supplier ID",
		name_label: "Supplier Name",
		missing: __("If party does not exist, create it using the Supplier Name field."),
		freeze: __("Creating Purchase Invoices ..."),
	},
};

frappe.ui.form.on("Opening Invoice Creation Tool", {
	setup(frm) {
		extend_invoice_types(frm);
		install_note_alert();
	},

	refresh(frm) {
		extend_invoice_types(frm);
		watch_grid(frm);
		install_note_alert();
		// ERPNext sets the button and party labels in its own refresh handler.
		setTimeout(() => prepare_form(frm), 0);
	},

	invoice_type(frm) {
		setTimeout(() => prepare_form(frm), 0);
	},
});

frappe.ui.form.on("Opening Invoice Creation Tool Item", {
	invoices_add(frm) {
		setTimeout(() => prepare_form(frm), 0);
	},
});

function prepare_form(frm) {
	if (!frm.doc) {
		return;
	}
	frappehero.opening_invoice_type = frm.doc.invoice_type;
	set_primary_action(frm);
	set_banner(frm);
	const grid = invoice_grid(frm);
	if (grid && grid._hero_notes) {
		grid.refresh();
		return;
	}
	apply_rows(frm);
	frm.refresh_field("invoices");
}

function extend_invoice_types(frm) {
	const field = frm.fields_dict.invoice_type;
	if (!field) {
		return;
	}
	const current = field.df.options || "";
	const list = Array.isArray(current) ? current.slice() : String(current).split("\n");
	["Credit Note", "Debit Note"].forEach((option) => {
		if (!list.includes(option)) {
			list.push(option);
		}
	});
	frm.set_df_property("invoice_type", "options", list.filter(Boolean).join("\n"));
}

function set_primary_action(frm) {
	const party = party_for(frm.doc.invoice_type);
	frm.page.set_primary_action(__("Create Invoices"), () => {
		return frm.call({
			doc: frm.doc,
			btn: frm.page.btn_primary.get(0),
			method: "make_invoices",
			freeze: 1,
			freeze_message: party.freeze,
		});
	});
}

function apply_rows(frm) {
	const note = NOTE_TYPES[frm.doc.invoice_type];
	const party = party_for(frm.doc.invoice_type);
	(frm.doc.invoices || []).forEach((row) => {
		row.party_type = party.party_type;
		if (!note) {
			return;
		}
		const name = (row.item_name || "").trim();
		if (!name || name.toLowerCase() === "opening invoice item") {
			row.item_name = note.item_name;
		}
	});
	const grid = invoice_grid(frm);
	if (!grid) {
		return;
	}
	set_grid_property(grid, "party", "label", party.id_label);
	set_grid_property(grid, "party_name", "label", party.name_label);
	frm.set_df_property("create_missing_party", "description", party.missing);
	set_grid_property(grid, "hero_against_invoice", "in_list_view", note ? 1 : 0);
	const amount = grid_field(grid, "outstanding_amount");
	if (amount && amount._hero_description === undefined) {
		amount._hero_description = amount.description || "";
	}
	set_grid_property(
		grid,
		"outstanding_amount",
		"description",
		note
			? __("Enter a positive amount. The note is posted as a return, so this reduces the party balance.")
			: (amount && amount._hero_description) || ""
	);
	if (grid_field(grid, "supplier_invoice_date")) {
		set_grid_property(
			grid,
			"supplier_invoice_date",
			"depends_on",
			'eval:parent.invoice_type=="Purchase" || parent.invoice_type=="Debit Note"'
		);
	}
}

function set_banner(frm) {
	if (!frm.dashboard || !frm.dashboard.set_headline) {
		return;
	}
	const note = NOTE_TYPES[frm.doc.invoice_type];
	if (note) {
		frm.dashboard.set_headline(note.banner, "blue");
		frm._hero_note_banner = true;
		return;
	}
	if (frm._hero_note_banner && frm.dashboard.clear_headline) {
		frm.dashboard.clear_headline();
		frm._hero_note_banner = false;
	}
}

function watch_grid(frm) {
	const grid = invoice_grid(frm);
	if (!grid || grid._hero_notes) {
		return;
	}
	grid._hero_notes = true;
	const refresh = grid.refresh.bind(grid);
	grid.refresh = () => {
		if (grid._hero_rendering) {
			return refresh();
		}
		grid._hero_rendering = true;
		try {
			apply_rows(frm);
			return refresh();
		} finally {
			grid._hero_rendering = false;
		}
	};
}

function party_for(invoiceType) {
	const note = NOTE_TYPES[invoiceType];
	if (note) {
		const base = note.party_type === "Customer" ? PARTY_TYPES.Sales : PARTY_TYPES.Purchase;
		return {
			party_type: note.party_type,
			id_label: note.id_label,
			name_label: note.name_label,
			missing: base.missing,
			freeze: note.freeze,
		};
	}
	return PARTY_TYPES[invoiceType] || PARTY_TYPES.Purchase;
}

function invoice_grid(frm) {
	return frm.fields_dict.invoices && frm.fields_dict.invoices.grid;
}

function grid_field(grid, fieldname) {
	return (grid.docfields || []).find((df) => df.fieldname === fieldname) || null;
}

function set_grid_property(grid, fieldname, property, value) {
	if (!grid_field(grid, fieldname) || !grid.update_docfield_property) {
		return;
	}
	grid.update_docfield_property(fieldname, property, value);
}

function install_note_alert() {
	if (frappehero._opening_note_alert) {
		return;
	}
	const purchase_created = __("Opening Purchase Invoice(s) have been created.");
	frappehero._opening_note_alert = frappe.show_alert;
	frappe.show_alert = function (message, seconds) {
		const text = message && typeof message === "object" ? message.message : message;
		const note = on_opening_tool() ? NOTE_TYPES[frappehero.opening_invoice_type] : null;
		if (note && text === purchase_created) {
			if (message && typeof message === "object") {
				message = Object.assign({}, message, { message: note.created });
			} else {
				message = note.created;
			}
		}
		return frappehero._opening_note_alert.call(this, message, seconds);
	};
}

function on_opening_tool() {
	if (!frappe.get_route) {
		return false;
	}
	const route = frappe.get_route() || [];
	return route[0] === "Form" && route[1] === "Opening Invoice Creation Tool";
}
