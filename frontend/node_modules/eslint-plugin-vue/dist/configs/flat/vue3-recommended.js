//#region lib/configs/flat/vue3-recommended.ts
var vue3_recommended_default = [...require("./vue3-strongly-recommended.js"), {
	name: "vue/recommended/rules",
	rules: {
		"vue/attributes-order": "warn",
		"vue/block-order": "warn",
		"vue/no-lone-template": "warn",
		"vue/no-multiple-slot-args": "warn",
		"vue/no-required-prop-with-default": "warn",
		"vue/no-v-html": "warn",
		"vue/order-in-components": "warn",
		"vue/this-in-template": "warn"
	}
}];
//#endregion
module.exports = vue3_recommended_default;
