"""Automatismi per il sezionale Corrispettivi (Sales Invoice cumulativa di
fine giornata, es. naming series DR/.YY./)."""

import frappe


def escludi_da_sdi_se_corrispettivo(doc, method=None):
	"""Se questa Sales Invoice appartiene a un Sezionale IVA di tipo
	Corrispettivi:
	- spunta da sola 'custom_escludi_da_sdi' (se il campo esiste: non fa nulla
	  finché non è stato applicato il fix su italian_invoice/before_submit.py
	  che lo rispetta);
	- azzera 'custom_tipo_di_documento': i corrispettivi non hanno un codice
	  TD (non sono fatture elettroniche SDI), ma il JS del form lo precompila
	  comunque in base al cliente selezionato (es. TD24), quindi va tolto qui
	  lato server dopo che il client l'ha già impostato.
	Non tocca 'custom_escludi_da_sdi' se l'utente l'ha già impostata
	manualmente a 0 di proposito."""
	e_corrispettivo = frappe.db.exists(
		"Sezionale IVA",
		{
			"naming_series_prefix": doc.naming_series,
			"registro": "Corrispettivi",
			"company": doc.company,
			"disabled": 0,
		},
	)
	if not e_corrispettivo:
		return

	if doc.meta.has_field("custom_escludi_da_sdi") and not doc.get("custom_escludi_da_sdi"):
		doc.custom_escludi_da_sdi = 1

	if doc.meta.has_field("custom_tipo_di_documento") and doc.get("custom_tipo_di_documento"):
		doc.custom_tipo_di_documento = None
