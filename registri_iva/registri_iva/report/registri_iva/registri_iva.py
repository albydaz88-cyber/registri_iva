import frappe
from frappe import _
from frappe.utils import flt, formatdate

from registri_iva.utils.tax_breakdown import tax_breakdown, totale_documento
from registri_iva.utils.tipo_documento import codici_tipologia, tipi_acquisti

def execute(filters=None):
	filters = filters or {}

	if not filters.get("sezionale"):
		frappe.msgprint(_("Seleziona un Sezionale per generare il registro."))
		return get_columns(), []

	sezionale = frappe.get_doc("Sezionale IVA", filters["sezionale"])
	columns = get_columns(sezionale)
	data = get_data(sezionale, filters)
	return columns, data


def get_columns(sezionale=None):
    columns = [
        {"fieldname": "posting_date", "label": _("Data Registrazione"), "fieldtype": "Date", "width": 100},
    ]

    if not sezionale or sezionale.registro != "Corrispettivi":
        columns.append(
            {"fieldname": "tipo_documento", "label": _("Tipo Documento"), "fieldtype": "Data", "width": 90}
        )

    columns.append(
        {"fieldname": "numero_documento_originale", "label": _("N. Documento Originale"), "fieldtype": "Data", "width": 140}
    )

    if not sezionale or sezionale.registro != "Corrispettivi":
        columns += [
            {"fieldname": "ragione_sociale", "label": _("Ragione Sociale"), "fieldtype": "Data", "width": 200},
            {"fieldname": "tax_id", "label": _("P.IVA/CF"), "fieldtype": "Data", "width": 130},
        ]

    columns += [
        {"fieldname": "numero_documento", "label": _("N. Documento (Protocollo)"), "fieldtype": "Dynamic Link",
         "options": "doctype_origine", "width": 150},
        {"fieldname": "data_documento", "label": _("Data Documento"), "fieldtype": "Date", "width": 100},
        {"fieldname": "imponibile", "label": _("Imponibile"), "fieldtype": "Currency", "width": 110},
        {"fieldname": "tipo_imposta", "label": _("Tipo Imposta"), "fieldtype": "Data", "width": 130},
        {"fieldname": "imposta", "label": _("Imposta"), "fieldtype": "Currency", "width": 110},
        {"fieldname": "totale_documento", "label": _("Totale Documento"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 350},
    ]

    return columns



def get_data(sezionale, filters):
	if sezionale.registro == "Acquisti":
		righe = _righe_da_purchase_invoice(sezionale, filters)
	elif sezionale.registro == "Vendite" and sezionale.auto_generato:
		righe = _righe_da_documento_integrativo(sezionale, filters)
	else:
		# Vendite (sezionali normali, es. SINV) e Corrispettivi (es. DR, Sales
		# Invoice cumulativa di fine giornata con Update Stock) leggono
		# entrambi da Sales Invoice: stessa logica, cambia solo la naming
		# series del sezionale scelto.
		righe = _righe_da_sales_invoice(sezionale, filters)

	# sort stabile: le righe dello stesso documento restano nell'ordine in cui
	# sono state create, quindi "ultima riga del documento" resta l'ultima.
	righe.sort(key=lambda r: (r["numero_documento"] or ""))
	return righe


def _accoda_righe(righe, base, aliquote, totale, nota_rc="", nota_totale="", nota_su_tutte=False):
	"""Aggiunge al registro una riga per ogni aliquota/natura del documento.

	Il Totale Documento compare solo sull'ULTIMA riga del documento; sulle
	precedenti la cella resta vuota (None, non 0), cosi' la somma della colonna
	e' corretta e non ci sono "0,00" a disturbare la lettura."""
	ultima = len(aliquote) - 1
	for i, a in enumerate(aliquote):
		nota = nota_rc if (nota_su_tutte or a.get("reverse_charge")) else ""
		if i == ultima and nota_totale:
			nota = f"{nota} {nota_totale}".strip()

		riga = dict(base)
		riga.update({
			"imponibile": flt(a["imponibile"]),
			"tipo_imposta": a["tipo_imposta"],
			"imposta": flt(a["imposta"]),
			"totale_documento": totale if i == ultima else None,
			"note": nota,
		})
		righe.append(riga)


def _nota_inversione_contabile(numero_pi, data_pi, supplier_name, tax_id):
	data_str = formatdate(data_pi, "dd/mm/yyyy") if data_pi else "?"
	return _("Inversione contabile su doc. n. {0} del {1} emesso da {2} ({3})").format(
		numero_pi, data_str, supplier_name or "?", tax_id or "?"
	)


def _base_filters(sezionale, filters, date_field="posting_date"):
	f = {
		"naming_series": sezionale.naming_series_prefix,
		"company": filters["company"],
		"docstatus": 1,
	}
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date and to_date:
		f[date_field] = ["between", [from_date, to_date]]
	elif from_date:
		f[date_field] = [">=", from_date]
	elif to_date:
		f[date_field] = ["<=", to_date]
	return f


def _righe_da_purchase_invoice(sezionale, filters):
	pi_filters = _base_filters(sezionale, filters)
	nomi = frappe.get_all("Purchase Invoice", filters=pi_filters, pluck="name")

	# Recupera il tipo documento per le fatture passive
	tipi = tipi_acquisti(nomi)

	righe = []
	for nome in nomi:
		pi = frappe.get_doc("Purchase Invoice", nome)
		aliquote = tax_breakdown(pi, detrazione=True, lato="credito")
		tax_id = pi.get("tax_id") or frappe.db.get_value("Supplier", pi.supplier, "tax_id")
		data_doc = pi.bill_date or pi.posting_date

		nota_verifica = ""
		if not aliquote and flt(pi.get("base_net_total")):
			# Nessuna riga IVA riconoscibile: meglio una riga da verificare che un
			# documento che sparisce in silenzio dal registro.
			aliquote = [{
				"tipo_imposta": _("Da verificare"),
				"aliquota": 0,
				"imponibile": flt(pi.base_net_total),
				"imposta": 0,
				"reverse_charge": False,
			}]
			nota_verifica = _("Nessuna riga IVA riconoscibile nel documento: verificare")

		# Totale del documento: ImportoTotaleDocumento dell'XML del fornitore se
		# disponibile, altrimenti imponibile+imposta di QUESTA fattura (non
		# pi.grand_total: sulle fatture in reverse charge le righe ADD/DEDUCT si
		# autocompensano e grand_total riflette solo il netto dovuto al fornitore).
		somma = sum(flt(a["imponibile"]) + flt(a["imposta"]) for a in aliquote)
		totale = totale_documento(pi, aliquote)

		nota_totale = nota_verifica
		if abs(totale - somma) > 0.005:
			nota_totale = (
				f"{nota_totale} " if nota_totale else ""
			) + _("Totale da XML: {0} differisce da imponibile+imposta ({1})").format(
				frappe.format_value(totale, {"fieldtype": "Currency"}),
				frappe.format_value(somma, {"fieldtype": "Currency"}),
			)

		nota = ""
		if any(a.get("reverse_charge") for a in aliquote):
			nota = _nota_inversione_contabile(pi.name, data_doc, pi.supplier_name, tax_id)

		base = {
			"posting_date": pi.posting_date,
			"tipo_documento": tipi.get(pi.name),
			"numero_documento_originale": pi.bill_no or pi.name,
			"ragione_sociale": pi.supplier_name,
			"tax_id": tax_id,
			"numero_documento": pi.name,
			"doctype_origine": "Purchase Invoice",
			"data_documento": data_doc,
		}
		_accoda_righe(righe, base, aliquote, totale, nota_rc=nota, nota_totale=nota_totale.strip())
	return righe


def _righe_da_sales_invoice(sezionale, filters):
	si_filters = _base_filters(sezionale, filters)
	nomi = frappe.get_all("Sales Invoice", filters=si_filters, pluck="name")

	codici = codici_tipologia()

	righe = []
	for nome in nomi:
		si = frappe.get_doc("Sales Invoice", nome)
		aliquote = tax_breakdown(si, detrazione=False, lato="debito")
		tax_id = si.get("tax_id") or frappe.db.get_value("Customer", si.customer, "tax_id")
		totale = sum(flt(a["imponibile"]) + flt(a["imposta"]) for a in aliquote)

		base = {
			"posting_date": si.posting_date,
			"tipo_documento": codici.get(si.get("custom_tipo_di_documento"), si.get("custom_tipo_di_documento")),
			"numero_documento_originale": si.name,  # coincidono, come da requisito
			"ragione_sociale": si.customer_name,
			"tax_id": tax_id,
			"numero_documento": si.name,
			"doctype_origine": "Sales Invoice",
			"data_documento": si.posting_date,
		}
		_accoda_righe(righe, base, aliquote, totale)
	return righe


def _righe_da_documento_integrativo(sezionale, filters):
	di_filters = _base_filters(sezionale, filters)
	rows = frappe.get_all(
		"Documento Integrativo",
		filters=di_filters,
		fields=["name", "posting_date", "invoice_date", "cliente_nome", "cliente_tax_id",
			"totale_documento", "purchase_invoice", "tipo_documento"],
	)

	righe = []
	for row in rows:
		aliquote = frappe.get_all(
			"Documento Integrativo Aliquota",
			filters={"parent": row["name"]},
			fields=["tipo_imposta", "imponibile", "imposta"],
			order_by="idx asc",
		)

		nota = ""
		if row.get("purchase_invoice"):
			pi = frappe.db.get_value(
				"Purchase Invoice", row["purchase_invoice"],
				["name", "bill_date", "posting_date", "supplier_name", "tax_id", "supplier"],
				as_dict=True,
			)
			if pi:
				tax_id = pi.tax_id or frappe.db.get_value("Supplier", pi.supplier, "tax_id")
				nota = _nota_inversione_contabile(
					pi.name, pi.bill_date or pi.posting_date, pi.supplier_name, tax_id
				)

		base = {
			"posting_date": row["posting_date"],
			"numero_documento_originale": row["name"],  # coincidono, come da requisito
			"ragione_sociale": row["cliente_nome"],
			"tax_id": row["cliente_tax_id"],
			"numero_documento": row["name"],
			"doctype_origine": "Documento Integrativo",
			"data_documento": row["invoice_date"],
			"tipo_documento": row["tipo_documento"],
		}
		_accoda_righe(righe, base, aliquote, row["totale_documento"], nota_rc=nota, nota_su_tutte=True)
	return righe
