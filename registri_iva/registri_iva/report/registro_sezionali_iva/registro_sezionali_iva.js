frappe.query_reports["Registro Sezionali IVA"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1,
		},
		{
			"fieldname": "registro",
			"label": __("Registro"),
			"fieldtype": "Select",
			"options": "\nAcquisti\nVendite\nCorrispettivi",
			"reqd": 0,
		},
		{
			"fieldname": "sezionale",
			"label": __("Sezionale"),
			"fieldtype": "Link",
			"options": "Sezionale IVA",
			"get_query": function () {
				const registro = frappe.query_report.get_filter_value("registro");
				return {
					filters: registro ? { registro: registro } : {},
				};
			},
		},
		{
			"fieldname": "from_date",
			"label": __("Da Data"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 1,
		},
		{
			"fieldname": "to_date",
			"label": __("A Data"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1,
		},
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "note" && data && data.note) {
			value = `<span style="color: #ff6b6b; font-weight: bold;">${data.note}</span>`;
		}
		return value;
	},
};
