frappe.ui.form.on("Sezionale IVA", {
	onload(frm) {
		// Popola il menu a tendina del prefisso con le naming series esistenti
		frappe.call({
			method: "registri_iva.registri_iva.doctype.sezionale_iva.sezionale_iva.get_prefissi_options",
			callback(r) {
				if (r.message) {
					frm.set_df_property(
						"naming_series_prefix",
						"options",
						r.message.map((x) => (Array.isArray(x) ? x[0] : x))
					);
				}
			},
		});
	},
});
