app_name = "registri_iva"
app_title = "Registri IVA"
app_publisher = "Il tuo nome"
app_description = "Registri IVA italiani (acquisti, vendite, corrispettivi), sezionali e autofatture intra-UE per ERPNext"
app_icon = "octicon octicon-book"
app_color = "grey"
app_email = "you@example.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext", "italian_invoice"]

doctype_js = {
	"Sezionale IVA": "public/js/sezionale_iva.js",
}

# Il Custom Field "Escludi da Fatturazione Elettronica (SDI)" su Sales Invoice
# (usato per i corrispettivi cumulativi) va installato/aggiornato via fixtures.
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["module", "=", "Registri IVA"]],
	},
]

# Il registro acquisti e il registro vendite "normale" sono letti live dal
# report direttamente da Purchase Invoice / Sales Invoice: nessun hook serve
# per quelli. Gli hook qui servono per due cose che non esisterebbero altrimenti:
# 1) il Documento Integrativo (autofattura TD17/18/19), generato alla submit
#    della Purchase Invoice;
# 2) l'esclusione automatica da SDI delle Sales Invoice cumulative dei
#    corrispettivi (vedi utils/corrispettivi.py).
doc_events = {
	"Purchase Invoice": {
		"on_submit": "registri_iva.utils.autofattura.on_purchase_invoice_submit",
		"before_cancel": "registri_iva.utils.autofattura.on_purchase_invoice_before_cancel",
	},
	"Sales Invoice": {
		"validate": "registri_iva.utils.corrispettivi.escludi_da_sdi_se_corrispettivo",
	},
}
