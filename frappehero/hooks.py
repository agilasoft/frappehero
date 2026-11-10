app_name = "frappehero"
app_title = "Frappe Hero"
app_publisher = "Agilasoft"
app_description = "Group users and the documents they may use, map accounts, and review access, defaults, shares, dimensions, tax, opening entries, credit notes, debit notes, invoice disputes, multi-currency payments, BSP exchange rates, and cheque leaves."
app_email = "dev@agilasoft.com"
app_license = "mit"

required_apps = ["erpnext"]

app_logo_url = "/assets/frappehero/images/logo.svg"
app_color = "#2490ef"
app_home = "/desk/frappe-hero"

add_to_apps_screen = [
	{
		"name": "frappehero",
		"logo": app_logo_url,
		"title": "Frappe Hero",
		"route": app_home,
		"has_permission": "frappehero.api.has_app_permission",
		"sequence_id": 50,
	}
]

app_include_css = "/assets/frappehero/css/frappehero.css"
app_include_js = [
	"/assets/frappehero/js/frappehero.js",
	"/assets/frappehero/js/opening_invoice_creation_tool.js",
]

doctype_list_js = {
	"Hero Permission Group": "public/js/hero_permission_group_list.js",
}

doctype_js = {
	"Sales Invoice": "public/js/sales_invoice_dispute.js",
	"Payment Entry": [
		"public/js/payment_entry_cheque.js",
		"public/js/payment_entry_references.js",
		"public/js/payment_entry_multi.js",
	],
	"Opening Invoice Creation Tool": "public/js/opening_invoice_creation_tool.js",
}

# Credit Note uploads a return Sales Invoice. Debit Note uploads a return
# Purchase Invoice. ERPNext's own class still builds Sales and Purchase.
override_doctype_class = {
	"Opening Invoice Creation Tool": "frappehero.finance_desk.opening_invoice.OpeningInvoiceCreationTool",
	"Payment Entry": "frappehero.finance_desk.payment_entry.PaymentEntry",
}

after_install = "frappehero.install.after_install"
after_migrate = "frappehero.install.after_migrate"

doc_events = {
	"User Permission": {
		"validate": "frappehero.permissions.lock_hero_fields",
	},
	"GL Entry": {
		"validate": "frappehero.finance_desk.gl.apply_dimension_defaults",
	},
	"Currency Exchange": {
		"validate": "frappehero.finance_desk.sync.lock_bsp_rate",
	},
	"Payment Entry": {
		"before_validate": [
			"frappehero.finance_desk.payment_reference.set_invoice_currency",
			"frappehero.finance_desk.cheque.validate_payment",
			"frappehero.finance_desk.multi_currency_payment.apply_to_payment",
		],
		"validate": "frappehero.finance_desk.cheque.validate_payment",
		"on_submit": "frappehero.finance_desk.cheque.submit_payment",
		"on_cancel": "frappehero.finance_desk.cheque.cancel_payment",
		"on_trash": "frappehero.finance_desk.cheque.trash_payment",
	},
}

scheduler_events = {
	"daily": [
		"frappehero.access_desk.tasks.daily",
		"frappehero.finance_desk.tasks.daily_rates",
	],
}

# Permission Studio writes User Permissions. The ownership fields are read-only
# in the desk and are restored on validate unless the sync flag is set.
# BSP rates do the same for the BSP Rate check on Currency Exchange.
# Cheque Leaf reserves a number on Payment Entry before ERPNext asks for the
# bank reference, then marks it used, void, or free as the payment moves.
# Payment references also show the invoice currency and the invoice total in
# that currency. Grand Total, Outstanding, and Allocated stay in the party
# account currency.
# Payment Entry allocates one bank amount across several party accounts and
# invoice currencies. The party lines, advance, rate difference, and bank line
# post on that Payment Entry. A payment on one account is unchanged.
# Opening Invoice Creation Tool accepts a Credit Note upload as a return Sales
# Invoice and a Debit Note upload as a return Purchase Invoice.
