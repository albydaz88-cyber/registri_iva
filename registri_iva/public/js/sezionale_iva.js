frappe.ui.form.on("Sezionale IVA", {
	onload(frm) {
		popola_prefissi(frm);
	},
});

function popola_prefissi(frm) {
	frappe.call({
		method: "registri_iva.registri_iva.doctype.sezionale_iva.sezionale_iva.get_prefissi_options",
		args: { txt: "" },
		callback(r) {
			if (!r || !r.message) return;
			const opzioni = r.message.map((x) => (Array.isArray(x) ? x[0] : x));
			// Il campo è un Select: il valore corrente va incluso nelle
			// opzioni, altrimenti Frappe lo svuota al primo refresh se non
			// combacia esattamente con la lista appena impostata.
			if (frm.doc.naming_series_prefix && !opzioni.includes(frm.doc.naming_series_prefix)) {
				opzioni.push(frm.doc.naming_series_prefix);
			}
			frm.set_df_property("naming_series_prefix", "options", [""].concat(opzioni));
			frm.refresh_field("naming_series_prefix");
		},
	});
}
