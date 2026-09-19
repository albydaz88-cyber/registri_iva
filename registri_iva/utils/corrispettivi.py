"""Automatismi per il sezionale Corrispettivi (Sales Invoice cumulativa di
fine giornata, es. naming series DR/.YY./)."""

import frappe


def escludi_da_sdi_se_corrispettivo(doc, method=None):
	"""Se questa Sales Invoice appartiene a un Sezionale IVA di tipo
	Corrispettivi, spunta da sola 'custom_escludi_da_sdi' (se il campo esiste:
	non fa nulla finché non è stato applicato il fix su italian_invoice/
	before_submit.py che lo rispetta). Non tocca la spunta se l'utente l'ha
	già impostata manualmente a 0 di proposito."""
	if not doc.meta.has_field("custom_escludi_da_sdi"):
		return
	if doc.get("custom_escludi_da_sdi"):
		return

	e_corrispettivo = frappe.db.exists(
		"Sezionale IVA",
		{
			"naming_series_prefix": doc.naming_series,
			"registro": "Corrispettivi",
			"company": doc.company,
			"disabled": 0,
		},
	)
	if e_corrispettivo:
		doc.custom_escludi_da_sdi = 1
