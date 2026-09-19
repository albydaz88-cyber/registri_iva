frappe.query_reports["Registri IVA"] = {
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
			"reqd": 1,
			"get_query": function () {
				const registro = frappe.query_report.get_filter_value("registro");
				const company = frappe.query_report.get_filter_value("company");
				const filters = { disabled: 0 };
				if (registro) filters.registro = registro;
				if (company) filters.company = company;
				return { filters: filters };
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
};
