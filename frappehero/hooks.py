app_name = "frappehero"
app_title = "Frappe Hero"
app_publisher = "Agilasoft"
app_description = "Group users and the documents they may use, map accounts, and review access, defaults, shares, dimensions, tax, opening entries, invoice disputes, BSP exchange rates, and cheque leaves."
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
app_include_js = "/assets/frappehero/js/frappehero.js"

doctype_list_js = {
	"Hero Permission Group": "public/js/hero_permission_group_list.js",
}

doctype_js = {
	"Sales Invoice": "public/js/sales_invoice_dispute.js",
	"Payment Entry": "public/js/payment_entry_cheque.js",
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
		"before_validate": "frappehero.finance_desk.cheque.validate_payment",
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
