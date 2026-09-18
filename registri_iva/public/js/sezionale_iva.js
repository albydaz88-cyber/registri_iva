frappe.ui.form.on("Sezionale IVA", {
	refresh(frm) {
		popola_prefissi(frm);
	},
});

function popola_prefissi(frm) {
	frappe.call({
		method: "registri_iva.registri_iva.doctype.sezionale_iva.sezionale_iva.get_prefissi_options",
		args: { txt: "" },
		callback(r) {
			console.log("[registri_iva] prefissi ricevuti:", r);
			if (!r || !r.message) return;
			const opzioni = r.message.map((x) => (Array.isArray(x) ? x[0] : x));
			// Il controllo Autocomplete legge 'options' in modo più affidabile
			// come stringa separata da \n che come array in alcune versioni.
			frm.set_df_property("naming_series_prefix", "options", opzioni.join("\n"));
			frm.refresh_field("naming_series_prefix");
		},
		error(err) {
			console.error("[registri_iva] errore nel recupero prefissi:", err);
		},
	});
}
