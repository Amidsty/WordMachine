//#region lib/configs/flat/vue2-recommended-error.ts
var vue2_recommended_error_default = [...require("./vue2-strongly-recommended-error.js"), {
	name: "vue/vue2-recommended-error/rules",
	rules: {
		"vue/attributes-order": "error",
		"vue/block-order": "error",
		"vue/no-lone-template": "error",
		"vue/no-multiple-slot-args": "error",
		"vue/no-required-prop-with-default": "error",
		"vue/no-v-html": "error",
		"vue/order-in-components": "error",
		"vue/this-in-template": "error"
	}
}];
//#endregion
module.exports = vue2_recommended_error_default;
