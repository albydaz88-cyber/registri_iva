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

	aliquote = _tax_breakdown(doc, "Purchase Taxes and Charges", detrazione=True, lato="credito")
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
		numero_documento_originale=doc.bill_no,
		data_documento_originale=doc.bill_date,
	)

	# --- Autofattura: doppia annotazione nel registro vendite -------------
	sezionale_autofattura = _trova_sezionale_autofattura(
		tipo_documento=getattr(doc, "custom_tipo_di_documento", None), company=doc.company
	)
	if sezionale_autofattura:
		aliquote_debito = _tax_breakdown(
			doc, "Purchase Taxes and Charges", detrazione=True, lato="debito"
		) or aliquote
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
			aliquote=aliquote_debito,
			generata_automaticamente=1,
			numero_documento_originale=doc.bill_no,
			data_documento_originale=doc.bill_date,
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

	aliquote = _tax_breakdown(doc, "Sales Taxes and Charges", detrazione=False, lato="debito")
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
		numero_documento_originale=doc.name,
		data_documento_originale=doc.posting_date,
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


def _tax_breakdown(doc, taxes_table_fieldname, detrazione, lato="credito"):
	"""Scompone le righe tasse del documento per aliquota, restituendo una lista
	di dict pronti per il child table 'Registrazione IVA Aliquota'.

	lato: "credito" -> registro acquisti (si usa la faccia a credito dell'IVA)
	      "debito"  -> sezionale autofattura nel registro vendite (faccia a debito)

	Nel template reverse charge italiano la stessa imposta compare due volte
	sulla Purchase Invoice: una riga ADD (IVA su acquisti, a credito) e una riga
	DEDUCT (IVA su vendite, a debito) di pari importo, che si compensano nel
	grand total. NON vanno sommate: farlo raddoppia l'imposta. E la riga DEDUCT
	non è "IVA non detraibile" (concetto diverso: IVA che non si può recuperare).
	"""
	righe_add = []
	righe_deduct = []

	for tax in doc.get("taxes") or []:
		descrizione = tax.description or ""
		# Le coppie generate da fatture_passive per natura N6.x si riconoscono
		# dalla descrizione invece che da add_deduct_tax (lì sono entrambe
		# "Actual" con importo di segno opposto).
		if RC_DEBITO_RE.search(descrizione):
			righe_deduct.append(tax)
			continue
		if RC_CREDITO_RE.search(descrizione):
			righe_add.append(tax)
			continue

		if getattr(tax, "add_deduct_tax", None) == "Deduct":
			righe_deduct.append(tax)
		else:
			righe_add.append(tax)

	# Reverse charge / autofattura: esiste una riga DEDUCT che specchia una ADD
	# di pari aliquota e importo. In quel caso le due facce sono la stessa
	# imposta e si sceglie quella pertinente al registro che stiamo scrivendo.
	e_reverse_charge = bool(righe_deduct) and _sono_speculari(righe_add, righe_deduct)

	if e_reverse_charge:
		righe_da_usare = righe_deduct if lato == "debito" else righe_add
		etichetta_forzata = "Reverse Charge"
	else:
		# Nessuna coppia speculare: le righe DEDUCT sono davvero decurtazioni
		# (es. IVA indetraibile) e vanno tenute distinte.
		righe_da_usare = righe_add
		etichetta_forzata = None

	risultato = {}
	for tax in righe_da_usare:
		rate = flt(tax.rate)
		tax_amount = abs(flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None)))
		base_amount = _base_amount_da_riga(tax)
		descrizione = tax.description or ""

		if base_amount == 0 and tax_amount == 0:
			continue

		if etichetta_forzata:
			tipo = etichetta_forzata
		elif rate in (22, 10, 5, 4):
			tipo = f"{int(rate)}%"
		elif rate == 0:
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
		riga = risultato.setdefault(
			chiave, {"tipo_imposta": tipo, "aliquota": rate, "imponibile": 0, "imposta": 0}
		)
		riga["imponibile"] += base_amount
		if tipo not in TIPI_SENZA_IMPOSTA:
			riga["imposta"] += tax_amount

	# Righe DEDUCT non speculari (IVA realmente indetraibile): le riportiamo a
	# parte, solo nel registro acquisti.
	if not e_reverse_charge and detrazione and lato == "credito":
		for tax in righe_deduct:
			importo = abs(flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None)))
			if not importo:
				continue
			chiave = ("Non Detraibile", flt(tax.rate))
			riga = risultato.setdefault(
				chiave,
				{"tipo_imposta": "Non Detraibile", "aliquota": flt(tax.rate), "imponibile": 0, "imposta": 0},
			)
			riga["imponibile"] += _base_amount_da_riga(tax)
			riga["imposta"] += importo

	return list(risultato.values())


def _sono_speculari(righe_add, righe_deduct):
	"""True se ogni riga DEDUCT ha una ADD di pari aliquota e pari importo
	assoluto: è la firma del template reverse charge / autofattura."""
	if not righe_add or not righe_deduct:
		return False

	def chiavi(righe):
		out = []
		for t in righe:
			importo = abs(flt(getattr(t, "tax_amount", None) or getattr(t, "base_tax_amount", None)))
			out.append((flt(t.rate), round(importo, 2)))
		return sorted(out)

	k_add = chiavi(righe_add)
	k_ded = chiavi(righe_deduct)
	# Ogni deduct deve trovare corrispondenza in add.
	return all(k in k_add for k in k_ded)


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
	numero_documento_originale=None,
	data_documento_originale=None,
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
	reg.numero_documento_originale = numero_documento_originale
	reg.data_documento_originale = data_documento_originale
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
