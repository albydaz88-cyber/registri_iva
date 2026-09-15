"""
Logica di generazione automatica delle Registrazione IVA a partire da
Purchase Invoice e Sales Invoice, incluse le autofatture intra-UE
(doppia annotazione: sezionale acquisti + sezionale dedicato in vendite).
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import flt

TIPI_SENZA_IMPOSTA = {"Esente", "Non Imponibile", "Non Soggetta", "Non Imponibile/Esente (verificare)"}

# italian_invoice.utilities.fatture_passive.prepare_invoice_taxes genera, per le
# righe con natura N6.x, due righe di tassa "gemelle" con importo opposto
# (autocompensazione IVA a credito/debito tutta interna alla Purchase Invoice).
# Le riconosciamo dalla descrizione, che è generata sempre nello stesso formato
# da quella funzione: "IVA {rate}% RC credito ({natura})" / "... RC debito ...".
RC_CREDITO_RE = re.compile(r"RC credito", re.IGNORECASE)
RC_DEBITO_RE = re.compile(r"RC debito", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Purchase Invoice
# ---------------------------------------------------------------------------

def on_purchase_invoice_submit(doc, method=None):
	sezionale_acquisti = _trova_sezionale_per_naming_series(
		naming_series=doc.naming_series, registro="Acquisti", company=doc.company
	)
	if not sezionale_acquisti:
		# Nessun sezionale mappato su questa naming series: non blocchiamo il
		# submit della fattura, semplicemente non generiamo il registro.
		frappe.msgprint(
			_(
				"Nessun Sezionale IVA (Acquisti) collegato alla naming series '{0}': "
				"nessuna Registrazione IVA generata per {1}."
			).format(doc.naming_series, doc.name),
			alert=True,
			indicator="orange",
		)
		return

	aliquote = _tax_breakdown(doc, "Purchase Taxes and Charges", detrazione=True)
	if not aliquote:
		return

	reg_acquisti = _crea_registrazione_iva(
		sezionale=sezionale_acquisti,
		company=doc.company,
		posting_date=doc.posting_date,
		tipo_documento=getattr(doc, "custom_tipo_di_documento", None),
		riferimento_doctype="Purchase Invoice",
		riferimento=doc.name,
		controparte_tipo="Supplier",
		controparte=doc.supplier,
		controparte_nome=doc.supplier_name,
		tax_id=getattr(doc, "tax_id", None) or frappe.db.get_value("Supplier", doc.supplier, "tax_id"),
		totale_documento=doc.grand_total,
		aliquote=aliquote,
		generata_automaticamente=1,
	)

	# --- Autofattura: doppia annotazione nel registro vendite -------------
	sezionale_autofattura = _trova_sezionale_autofattura(
		tipo_documento=getattr(doc, "custom_tipo_di_documento", None), company=doc.company
	)
	if sezionale_autofattura:
		reg_vendite = _crea_registrazione_iva(
			sezionale=sezionale_autofattura,
			company=doc.company,
			posting_date=doc.posting_date,
			tipo_documento=getattr(doc, "custom_tipo_di_documento", None),
			riferimento_doctype="Purchase Invoice",
			riferimento=doc.name,
			controparte_tipo="Supplier",
			controparte=doc.supplier,
			controparte_nome=doc.supplier_name,
			tax_id=getattr(doc, "tax_id", None) or frappe.db.get_value("Supplier", doc.supplier, "tax_id"),
			totale_documento=doc.grand_total,
			aliquote=aliquote,
			generata_automaticamente=1,
			note=_("Integrazione IVA (autofattura) generata automaticamente da {0}").format(doc.name),
		)
		# Collegamento bidirezionale tra le due registrazioni gemelle
		frappe.db.set_value("Registrazione IVA", reg_acquisti.name, "registrazione_collegata", reg_vendite.name)
		frappe.db.set_value("Registrazione IVA", reg_vendite.name, "registrazione_collegata", reg_acquisti.name)


def on_purchase_invoice_cancel(doc, method=None):
	_cancella_registrazioni_collegate("Purchase Invoice", doc.name)


# ---------------------------------------------------------------------------
# Sales Invoice
# ---------------------------------------------------------------------------

def on_sales_invoice_submit(doc, method=None):
	sezionale_vendite = _trova_sezionale_per_naming_series(
		naming_series=doc.naming_series, registro="Vendite", company=doc.company
	)
	if not sezionale_vendite:
		return

	aliquote = _tax_breakdown(doc, "Sales Taxes and Charges", detrazione=False)
	if not aliquote:
		return

	_crea_registrazione_iva(
		sezionale=sezionale_vendite,
		company=doc.company,
		posting_date=doc.posting_date,
		tipo_documento=getattr(doc, "custom_tipo_di_documento", None),
		riferimento_doctype="Sales Invoice",
		riferimento=doc.name,
		controparte_tipo="Customer",
		controparte=doc.customer,
		controparte_nome=doc.customer_name,
		tax_id=getattr(doc, "tax_id", None) or frappe.db.get_value("Customer", doc.customer, "tax_id"),
		totale_documento=doc.grand_total,
		aliquote=aliquote,
		generata_automaticamente=1,
	)


def on_sales_invoice_cancel(doc, method=None):
	_cancella_registrazioni_collegate("Sales Invoice", doc.name)


# ---------------------------------------------------------------------------
# Helper condivisi
# ---------------------------------------------------------------------------

def _trova_sezionale_per_naming_series(naming_series, registro, company):
	return frappe.db.get_value(
		"Sezionale IVA",
		{
			"naming_series_prefix": naming_series,
			"registro": registro,
			"company": company,
			"disabled": 0,
		},
		"name",
	)


def _trova_sezionale_autofattura(tipo_documento, company):
	"""Cerca un Sezionale IVA (Vendite, auto_generato=1) il cui elenco
	tipo_documento_trigger contenga il tipo documento passato (es. TD17)."""
	if not tipo_documento:
		return None

	candidati = frappe.get_all(
		"Sezionale IVA",
		filters={
			"registro": "Vendite",
			"company": company,
			"auto_generato": 1,
			"disabled": 0,
		},
		fields=["name", "tipo_documento_trigger"],
	)
	for c in candidati:
		trigger_list = [t.strip().upper() for t in (c.tipo_documento_trigger or "").split(",") if t.strip()]
		if tipo_documento.strip().upper() in trigger_list:
			return c.name
	return None


def _tax_breakdown(doc, taxes_table_fieldname, detrazione):
	"""Scompone le righe tasse del documento (doc.taxes) per aliquota,
	restituendo una lista di dict pronti per popolare il child table
	'Registrazione IVA Aliquota'. Riusa la stessa euristica già presente
	nei report registro_iva_acquisti/vendite di italian_invoice
	(item_wise_tax_detail se disponibile, altrimenti tax_amount/rate),
	con gestione dedicata delle coppie RC credito/debito generate da
	fatture_passive.prepare_invoice_taxes per le righe natura N6.x."""
	risultato = {}  # chiave = (tipo_imposta, aliquota) -> dict accumulato

	for tax in doc.get("taxes") or []:
		descrizione = tax.description or ""
		rate = flt(tax.rate)
		tax_amount = flt(tax.tax_amount if hasattr(tax, "tax_amount") else tax.base_tax_amount)

		# La riga "RC debito" è solo lo specchio contabile della "RC credito"
		# (stesso imponibile, importo opposto): la saltiamo per non raddoppiare
		# l'imponibile e non azzerare l'imposta sommandole nello stesso bucket.
		if RC_DEBITO_RE.search(descrizione):
			continue

		if RC_CREDITO_RE.search(descrizione):
			# Qui rate è sempre != 0 (è l'aliquota RC, es. 22), quindi il
			# ricalcolo tax_amount/rate è affidabile.
			base_amount = _base_amount_da_riga(tax)
			chiave = ("Reverse Charge", rate)
			riga = risultato.setdefault(
				chiave, {"tipo_imposta": "Reverse Charge", "aliquota": rate, "imponibile": 0, "imposta": 0}
			)
			riga["imponibile"] += base_amount
			riga["imposta"] += abs(tax_amount)
			continue

		base_amount = _base_amount_da_riga(tax)
		if base_amount == 0 and tax_amount == 0:
			continue

		non_detraibile = detrazione and getattr(tax, "add_deduct_tax", None) == "Deduct"
		if non_detraibile:
			chiave = ("Non Detraibile", 0)
			riga = risultato.setdefault(chiave, {"tipo_imposta": "Non Detraibile", "aliquota": 0, "imponibile": 0, "imposta": 0})
			riga["imposta"] += tax_amount
			continue

		if rate in (22, 10, 5, 4):
			tipo = f"{int(rate)}%"
		elif rate == 0:
			# Riga a aliquota 0 senza coppia RC (es. natura N4 esente, N3 non
			# imponibile...). Qui il documento è quasi sempre creato a mano
			# (template fiscale scelto in form, non importato da XML), quindi
			# la descrizione del template è di solito parlante: la usiamo
			# come primo criterio, con fallback esplicito se ambigua.
			descrizione_lower = descrizione.lower()
			if "esent" in descrizione_lower:
				tipo = "Esente"
			elif "non impon" in descrizione_lower:
				tipo = "Non Imponibile"
			elif "non sogget" in descrizione_lower:
				tipo = "Non Soggetta"
			else:
				tipo = "Non Imponibile/Esente (verificare)"
			base_amount = base_amount or flt(getattr(tax, "total", 0))
		else:
			tipo = f"{rate}%"

		chiave = (tipo, rate)
		riga = risultato.setdefault(chiave, {"tipo_imposta": tipo, "aliquota": rate, "imponibile": 0, "imposta": 0})
		riga["imponibile"] += base_amount
		if tipo not in TIPI_SENZA_IMPOSTA:
			riga["imposta"] += tax_amount

	return list(risultato.values())


def _base_amount_da_riga(tax):
	base_amount = 0
	item_wise = getattr(tax, "item_wise_tax_detail", None)
	if item_wise:
		try:
			parsed = json.loads(item_wise)
			for _item_code, tax_data in parsed.items():
				if isinstance(tax_data, list) and len(tax_data) >= 2:
					base_amount += flt(tax_data[1])
		except (ValueError, TypeError):
			pass

	tax_amount = flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None))
	rate = flt(tax.rate)
	if base_amount == 0 and tax_amount != 0 and rate != 0:
		base_amount = tax_amount / (rate / 100)

	return base_amount


def _crea_registrazione_iva(
	sezionale,
	company,
	posting_date,
	tipo_documento,
	riferimento_doctype,
	riferimento,
	controparte_tipo,
	controparte,
	controparte_nome,
	tax_id,
	totale_documento,
	aliquote,
	generata_automaticamente=0,
	note=None,
):
	reg = frappe.new_doc("Registrazione IVA")
	reg.sezionale = sezionale
	reg.company = company
	reg.posting_date = posting_date
	reg.tipo_documento = tipo_documento
	reg.riferimento_doctype = riferimento_doctype
	reg.riferimento = riferimento
	reg.controparte_tipo = controparte_tipo
	reg.controparte = controparte
	reg.controparte_nome = controparte_nome
	reg.tax_id = tax_id
	reg.totale_documento = totale_documento
	reg.generata_automaticamente = generata_automaticamente
	if note:
		reg.note = note

	for riga in aliquote:
		reg.append("aliquote", riga)

	reg.insert(ignore_permissions=True)
	reg.submit()
	return reg


def _cancella_registrazioni_collegate(riferimento_doctype, riferimento):
	nomi = frappe.get_all(
		"Registrazione IVA",
		filters={
			"riferimento_doctype": riferimento_doctype,
			"riferimento": riferimento,
			"docstatus": 1,
		},
		pluck="name",
	)
	for nome in nomi:
		reg = frappe.get_doc("Registrazione IVA", nome)
		if reg.docstatus == 1:
			reg.flags.ignore_linked_doctypes = True
			reg.cancel()
