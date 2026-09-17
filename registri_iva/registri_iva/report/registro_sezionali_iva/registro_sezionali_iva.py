import frappe
from frappe import _
from frappe.utils import flt

from registri_iva.utils.tax_breakdown import tax_breakdown


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()

	if not filters.get("sezionale"):
		frappe.msgprint(_("Seleziona un Sezionale per generare il registro."))
		return columns, []

	sezionale = frappe.get_doc("Sezionale IVA", filters["sezionale"])
	data = get_data(sezionale, filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "posting_date", "label": _("Data Registrazione"), "fieldtype": "Date", "width": 100},
		{"fieldname": "numero_documento_originale", "label": _("N. Documento Originale"), "fieldtype": "Data", "width": 140},
		{"fieldname": "ragione_sociale", "label": _("Ragione Sociale"), "fieldtype": "Data", "width": 200},
		{"fieldname": "tax_id", "label": _("P.IVA/CF"), "fieldtype": "Data", "width": 130},
		{"fieldname": "numero_documento", "label": _("N. Documento (Protocollo)"), "fieldtype": "Dynamic Link",
		 "options": "doctype_origine", "width": 150},
		{"fieldname": "data_documento", "label": _("Data Documento"), "fieldtype": "Date", "width": 100},
		{"fieldname": "imponibile", "label": _("Imponibile"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "tipo_imposta", "label": _("Tipo Imposta"), "fieldtype": "Data", "width": 130},
		{"fieldname": "imposta", "label": _("Imposta"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "totale_documento", "label": _("Totale Documento"), "fieldtype": "Currency", "width": 130},
	]


def get_data(sezionale, filters):
	if sezionale.registro == "Acquisti":
		righe = _righe_da_purchase_invoice(sezionale, filters)
	elif sezionale.registro == "Vendite" and sezionale.auto_generato:
		righe = _righe_da_documento_integrativo(sezionale, filters)
	elif sezionale.registro == "Vendite":
		righe = _righe_da_sales_invoice(sezionale, filters)
	else:
		# Corrispettivi: non ancora implementato in questa versione.
		frappe.msgprint(_("Registro Corrispettivi non ancora implementato."), alert=True, indicator="orange")
		righe = []

	righe.sort(key=lambda r: (r["numero_documento"] or ""))
	return righe


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

	righe = []
	for nome in nomi:
		pi = frappe.get_doc("Purchase Invoice", nome)
		aliquote = tax_breakdown(pi, detrazione=True, lato="credito")
		tax_id = pi.get("tax_id") or frappe.db.get_value("Supplier", pi.supplier, "tax_id")
		for a in aliquote:
			righe.append({
				"posting_date": pi.posting_date,
				"numero_documento_originale": pi.bill_no or pi.name,
				"ragione_sociale": pi.supplier_name,
				"tax_id": tax_id,
				"numero_documento": pi.name,
				"doctype_origine": "Purchase Invoice",
				"data_documento": pi.bill_date or pi.posting_date,
				"imponibile": flt(a["imponibile"]),
				"tipo_imposta": a["tipo_imposta"],
				"imposta": flt(a["imposta"]),
				"totale_documento": pi.grand_total,
			})
	return righe


def _righe_da_sales_invoice(sezionale, filters):
	si_filters = _base_filters(sezionale, filters)
	nomi = frappe.get_all("Sales Invoice", filters=si_filters, pluck="name")

	righe = []
	for nome in nomi:
		si = frappe.get_doc("Sales Invoice", nome)
		aliquote = tax_breakdown(si, detrazione=False, lato="debito")
		tax_id = si.get("tax_id") or frappe.db.get_value("Customer", si.customer, "tax_id")
		for a in aliquote:
			righe.append({
				"posting_date": si.posting_date,
				"numero_documento_originale": si.name,  # coincidono, come da requisito
				"ragione_sociale": si.customer_name,
				"tax_id": tax_id,
				"numero_documento": si.name,
				"doctype_origine": "Sales Invoice",
				"data_documento": si.posting_date,
				"imponibile": flt(a["imponibile"]),
				"tipo_imposta": a["tipo_imposta"],
				"imposta": flt(a["imposta"]),
				"totale_documento": si.grand_total,
			})
	return righe


def _righe_da_documento_integrativo(sezionale, filters):
	di_filters = _base_filters(sezionale, filters)
	rows = frappe.get_all(
		"Documento Integrativo",
		filters=di_filters,
		fields=["name", "posting_date", "invoice_date", "cliente_nome", "cliente_tax_id", "totale_documento"],
	)

	righe = []
	for row in rows:
		aliquote = frappe.get_all(
			"Documento Integrativo Aliquota",
			filters={"parent": row["name"]},
			fields=["tipo_imposta", "imponibile", "imposta"],
		)
		for a in aliquote:
			righe.append({
				"posting_date": row["posting_date"],
				"numero_documento_originale": row["name"],  # coincidono, come da requisito
				"ragione_sociale": row["cliente_nome"],
				"tax_id": row["cliente_tax_id"],
				"numero_documento": row["name"],
				"doctype_origine": "Documento Integrativo",
				"data_documento": row["invoice_date"],
				"imponibile": flt(a["imponibile"]),
				"tipo_imposta": a["tipo_imposta"],
				"imposta": flt(a["imposta"]),
				"totale_documento": row["totale_documento"],
			})
	return righe
