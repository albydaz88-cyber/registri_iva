app_name = "registri_iva"
app_title = "Registri IVA"
app_publisher = "Il tuo nome"
app_description = "Registri IVA italiani (acquisti, vendite, corrispettivi), sezionali e autofatture intra-UE per ERPNext"
app_icon = "octicon octicon-book"
app_color = "grey"
app_email = "you@example.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext", "italian_invoice"]

# Hook sui documenti sorgente: generano automaticamente le Registrazione IVA
doc_events = {
	"Purchase Invoice": {
		"on_submit": "registri_iva.utils.autofattura.on_purchase_invoice_submit",
		"on_cancel": "registri_iva.utils.autofattura.on_purchase_invoice_cancel",
	},
	"Sales Invoice": {
		"on_submit": "registri_iva.utils.autofattura.on_sales_invoice_submit",
		"on_cancel": "registri_iva.utils.autofattura.on_sales_invoice_cancel",
	},
}
