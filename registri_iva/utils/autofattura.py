"""
Generazione automatica del Documento Integrativo (autofattura TD17/18/19) alla
submit di una Purchase Invoice. Il registro acquisti e il registro vendite
"normale" NON hanno più una tabella intermedia: il report li legge live da
Purchase Invoice / Sales Invoice. Qui serve solo generare il documento che
altrimenti non esisterebbe affatto: l'integrazione IVA lato vendite.
"""

import frappe
from frappe import _

from registri_iva.utils.tax_breakdown import tax_breakdown

CLIENTE_GENERICO = "CLIENTE PER AUTOFATTURA"


def on_purchase_invoice_submit(doc, method=None):
	sezionale_autofattura = _trova_sezionale_autofattura(
		tipo_documento=getattr(doc, "custom_tipo_di_documento", None), company=doc.company
	)
	if not sezionale_autofattura:
		return

	aliquote = tax_breakdown(doc, detrazione=True, lato="debito")
	if not aliquote:
		frappe.msgprint(
			_(
				"Purchase Invoice {0}: tipo documento {1} riconosciuto come autofattura, "
				"ma nessuna riga IVA trovata da riportare nel documento integrativo. "
				"Verifica il template fiscale applicato."
			).format(doc.name, getattr(doc, "custom_tipo_di_documento", "")),
			alert=True,
			indicator="orange",
		)
		return

	di = frappe.new_doc("Documento Integrativo")
	di.sezionale = sezionale_autofattura
	di.company = doc.company
	di.posting_date = doc.posting_date
	di.invoice_date = doc.bill_date or doc.posting_date
	di.tipo_documento = getattr(doc, "custom_tipo_di_documento", None)
	di.purchase_invoice = doc.name
	di.cliente_nome = CLIENTE_GENERICO
	for riga in aliquote:
		di.append("aliquote", riga)

	di.insert(ignore_permissions=True)
	di.submit()


def on_purchase_invoice_cancel(doc, method=None):
	nomi = frappe.get_all(
		"Documento Integrativo",
		filters={"purchase_invoice": doc.name, "docstatus": 1},
		pluck="name",
	)
	for nome in nomi:
		di = frappe.get_doc("Documento Integrativo", nome)
		di.cancel()


def _trova_sezionale_autofattura(tipo_documento, company):
	if not tipo_documento:
		return None

	candidati = frappe.get_all(
		"Sezionale IVA",
		filters={"registro": "Vendite", "company": company, "auto_generato": 1, "disabled": 0},
		fields=["name", "tipo_documento_trigger"],
	)
	for c in candidati:
		trigger_list = [t.strip().upper() for t in (c.tipo_documento_trigger or "").split(",") if t.strip()]
		if tipo_documento.strip().upper() in trigger_list:
			return c.name
	return None
