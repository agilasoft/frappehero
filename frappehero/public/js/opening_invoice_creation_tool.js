// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

// Credit Note and Debit Note on Opening Invoice Creation Tool.
// The posting rules live in frappehero/finance_desk/opening_invoice_logic.py.

frappe.provide("frappehero");

(() => {
	if (frappehero._opening_invoice_tool_registered) {
		return;
	}

	install_type_guard();

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

	// Same order as OPENING_SUMMARY_ROWS in opening_invoice_logic.py.
	frappehero.opening_summary_rows = () => [
		{ label: "Sales Invoice", doctype: "Sales Invoice", is_return: "0" },
		{ label: "Credit Note", doctype: "Sales Invoice", is_return: "1" },
		{ label: "Purchase Invoice", doctype: "Purchase Invoice", is_return: "0" },
		{ label: "Debit Note", doctype: "Purchase Invoice", is_return: "1" },
	];

	frappehero.opening_summary_route = (doctype, company, is_return) => ({
		doctype,
		filters: {
			is_opening: "Yes",
			company,
			docstatus: 1,
			is_return: String(is_return),
		},
	});

	const OPENING_SUMMARY_TEMPLATE = `
{% $.each(data, (company, summary) => { %}
<div style="margin: 15px 0px -10px 0px;"> {{ company }}</div>
<table class="table table-bordered small">
	<thead>
		<tr>
			<td style="width: 33%">{{ __("Invoice Type") }}</td>
			<td style="width: 33%" class="text-right">{{ __("Opening Invoices") }}</td>
			<td style="width: 33%" class="text-right">{{ __("Total Outstanding") }}</td>
		</tr>
	</thead>
	<tbody>
		{% $.each(rows, (idx, row) => { %}
		{% if summary[row.label] %}
		<tr>
			<td>
				<a class="invoice-link" data-type="{{ row.doctype }}" data-company="{{ company }}" data-return="{{ row.is_return }}">
					{{ __(row.label) }}</a>
			</td>
			<td class="text-right">
				{{ summary[row.label].total_invoices }}
			</td>
			<td class="text-right">
				{{ format_currency(summary[row.label].outstanding_amount, summary.currency, 2) }}
			</td>
		</tr>
		{% endif %}
		{% }); %}
	</tbody>
</table>
{% }); %}`;

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
			install_type_guard();
			extend_invoice_types(frm);
			install_note_alert();
			install_summary_handler();
		},

		refresh(frm) {
			install_type_guard();
			extend_invoice_types(frm);
			watch_grid(frm);
			install_note_alert();
			install_summary_handler();
			// ERPNext sets the button and party labels in its own refresh handler.
			// Paint again after that, in case the select was rebuilt from Sales and Purchase.
			setTimeout(() => {
				paint_opening_select(frm.fields_dict && frm.fields_dict.invoice_type);
				prepare_form(frm);
				render_opening_summary(frm);
			}, 0);
		},

		onload_post_render(frm) {
			extend_invoice_types(frm);
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

	install_type_guard();
	frappehero._opening_invoice_tool_registered = true;

	function install_summary_handler() {
		const form_ui = frappe.ui && frappe.ui.form;
		if (!form_ui || !form_ui.off || !form_ui.on) {
			return;
		}
		// ERPNext's summary only lists Sales Invoice and Purchase Invoice.
		form_ui.off("Opening Invoice Creation Tool", "make_dashboard");
		form_ui.on("Opening Invoice Creation Tool", "make_dashboard", (frm) => {
			render_opening_summary(frm);
		});
	}

	function render_opening_summary(frm) {
		if (!frm || !frm.dashboard || !frm.doc || frm.doc.import_in_progress || !frm.doc.__onload) {
			return;
		}
		const data = frm.doc.__onload.opening_invoices_summary;
		const empty =
			!data ||
			(typeof $ !== "undefined" && $.isEmptyObject && $.isEmptyObject(data)) ||
			!Object.keys(data).length;
		if (frm.dashboard.parent) {
			frm.dashboard.parent.find(".custom").remove();
		}
		if (empty) {
			return;
		}
		const section = frm.dashboard.add_section(
			frappe.render_template(OPENING_SUMMARY_TEMPLATE, {
				data,
				rows: frappehero.opening_summary_rows(),
			}),
			__("Opening Invoices Summary")
		);
		section.on("click", ".invoice-link", function () {
			const link = $(this);
			const route = frappehero.opening_summary_route(
				link.attr("data-type"),
				link.attr("data-company"),
				link.attr("data-return")
			);
			frappe.set_route("List", route.doctype, route.filters);
		});
		if (frm.dashboard.show) {
			frm.dashboard.show();
		}
	}

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
		const field = frm.fields_dict && frm.fields_dict.invoice_type;
		if (!field || !field.df) {
			return;
		}
		const options = options_with_notes(field.df.options);
		// set_df_property writes the per-document copy. The rendered select can
		// still be holding the base field, which only lists Sales and Purchase.
		stamp_option_sources(frm, options);
		frm.set_df_property("invoice_type", "options", options);
		stamp_option_sources(frm, options);
		field.last_options = null;
		paint_opening_select(field);
		frm.refresh_field("invoice_type");
		paint_opening_select(field);
	}

	function option_label(option) {
		if (option && typeof option === "object") {
			return option.value == null ? option.label : option.value;
		}
		return option;
	}

	function options_with_notes(current) {
		const source = Array.isArray(current) ? current : String(current || "").split(/\r?\n/);
		const list = [];
		source.forEach((option) => {
			const text = String(option_label(option) || "").trim();
			if (text && !list.includes(text)) {
				list.push(text);
			}
		});
		["Credit Note", "Debit Note"].forEach((option) => {
			if (!list.includes(option)) {
				list.push(option);
			}
		});
		return list.join("\n");
	}

	function paint_opening_select(field) {
		const input = select_element(field);
		if (!input || typeof input.appendChild !== "function" || !input.ownerDocument) {
			return;
		}
		const wanted = options_with_notes(
			Array.from(input.options || []).map((option) => option.value)
		).split("\n");
		const current = Array.from(input.options || []).map((option) => option.value);
		if (current.join("\n") === wanted.join("\n")) {
			return;
		}
		const selected = input.value;
		while (input.firstChild) {
			input.removeChild(input.firstChild);
		}
		wanted.forEach((label) => {
			const option = input.ownerDocument.createElement("option");
			option.value = label;
			option.text = label;
			input.appendChild(option);
		});
		if (wanted.includes(selected)) {
			input.value = selected;
		}
		field.last_options = null;
		if (field.df) {
			field.df.options = wanted.join("\n");
		}
	}

	function select_element(field) {
		const input = field && field.$input;
		if (!input) {
			return null;
		}
		const element = input.jquery ? input.get(0) : input;
		if (!element || String(element.tagName || "").toUpperCase() !== "SELECT") {
			return null;
		}
		return element;
	}

	function stamp_option_sources(frm, options) {
		const field = frm.fields_dict && frm.fields_dict.invoice_type;
		if (field && field.df) {
			field.df.options = options;
		}
		const meta = frappe.meta;
		if (!meta) {
			return;
		}
		const map = meta.docfield_map && meta.docfield_map[frm.doctype];
		if (map && map.invoice_type) {
			map.invoice_type.options = options;
		}
		const copies = meta.docfield_copy && meta.docfield_copy[frm.doctype];
		if (!copies) {
			return;
		}
		Object.keys(copies).forEach((name) => {
			const df = copies[name] && copies[name].invoice_type;
			if (df) {
				df.options = options;
			}
		});
	}

	function install_type_guard() {
		const form_ui = frappe.ui && frappe.ui.form;
		if (!form_ui) {
			return;
		}
		const Control = form_ui.ControlSelect;
		if (
			Control &&
			Control.prototype &&
			!Control.prototype._hero_opening_types &&
			typeof Control.prototype.set_options === "function"
		) {
			const original = Control.prototype.set_options;
			Control.prototype.set_options = function (value) {
				if (is_opening_type_control(this)) {
					const options = options_with_notes(this.df && this.df.options);
					if (!this.df || this.df.options !== options || select_missing_notes(this)) {
						if (this.df) {
							this.df.options = options;
						}
						this.last_options = null;
					}
				}
				return original.call(this, value);
			};
			Control.prototype._hero_opening_types = true;
		}
		if (typeof form_ui.add_options === "function" && !form_ui.add_options._hero_opening_types) {
			const original_add = form_ui.add_options;
			const add_options = function (input, options_list, sort, doctype) {
				const control = opening_select_control(input);
				if (control) {
					const options = options_with_notes(options_list);
					options_list = options.split("\n");
					if (control.df) {
						control.df.options = options;
					}
					control.last_options = null;
				}
				return original_add.call(this, input, options_list, sort, doctype);
			};
			add_options._hero_opening_types = true;
			form_ui.add_options = add_options;
		}
	}

	function select_missing_notes(control) {
		const input = select_element(control);
		if (!input || !input.options) {
			return false;
		}
		const values = Array.from(input.options).map((option) => option.value);
		return !values.includes("Credit Note") || !values.includes("Debit Note");
	}

	function opening_select_control(input) {
		const element = input && input.jquery ? input.get(0) : input;
		if (!element || typeof element.closest !== "function") {
			return null;
		}
		const wrapper = element.closest(".frappe-control");
		const control = wrapper && wrapper.fieldobj;
		return is_opening_type_control(control) ? control : null;
	}

	function is_opening_type_control(control) {
		if (!control || !control.df || control.df.fieldname !== "invoice_type") {
			return false;
		}
		const doctype = (control.frm && control.frm.doctype) || control.df.parent;
		return doctype === "Opening Invoice Creation Tool";
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
})();
