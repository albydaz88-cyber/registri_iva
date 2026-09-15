import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "name", "label": _("N. Registrazione"), "fieldtype": "Link",
		 "options": "Registrazione IVA", "width": 150},
		{"fieldname": "sezionale", "label": _("Sezionale"), "fieldtype": "Link",
		 "options": "Sezionale IVA", "width": 150},
		{"fieldname": "posting_date", "label": _("Data"), "fieldtype": "Date", "width": 100},
		{"fieldname": "riferimento", "label": _("Documento"), "fieldtype": "Dynamic Link",
		 "options": "riferimento_doctype", "width": 150},
		{"fieldname": "controparte_nome", "label": _("Controparte"), "fieldtype": "Data", "width": 200},
		{"fieldname": "tax_id", "label": _("P.IVA/CF"), "fieldtype": "Data", "width": 130},
		{"fieldname": "tipo_imposta", "label": _("Tipo Imposta"), "fieldtype": "Data", "width": 130},
		{"fieldname": "imponibile", "label": _("Imponibile"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "imposta", "label": _("Imposta"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "totale_documento", "label": _("Totale Documento"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 200},
	]


def get_data(filters):
	conditions, values = get_conditions(filters)

	rows = frappe.db.sql(
		f"""
		SELECT
			r.name,
			r.sezionale,
			r.posting_date,
			r.riferimento_doctype,
			r.riferimento,
			r.controparte_nome,
			r.tax_id,
			r.totale_documento,
			r.note,
			a.tipo_imposta,
			a.imponibile,
			a.imposta
		FROM `tabRegistrazione IVA` r
		INNER JOIN `tabRegistrazione IVA Aliquota` a ON a.parent = r.name
		WHERE r.docstatus = 1
		{conditions}
		ORDER BY r.posting_date, r.sezionale, r.name, a.idx
		""",
		values,
		as_dict=1,
	)

	for row in rows:
		row["imponibile"] = flt(row.get("imponibile"))
		row["imposta"] = flt(row.get("imposta"))

	return rows


def get_conditions(filters):
	conditions = []
	values = {}

	if filters.get("company"):
		conditions.append("r.company = %(company)s")
		values["company"] = filters["company"]

	if filters.get("from_date"):
		conditions.append("r.posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("r.posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("sezionale"):
		conditions.append("r.sezionale = %(sezionale)s")
		values["sezionale"] = filters["sezionale"]
	elif filters.get("registro"):
		conditions.append(
			"r.sezionale IN (SELECT name FROM `tabSezionale IVA` WHERE registro = %(registro)s)"
		)
		values["registro"] = filters["registro"]

	condizioni_sql = " AND " + " AND ".join(conditions) if conditions else ""
	return condizioni_sql, values
