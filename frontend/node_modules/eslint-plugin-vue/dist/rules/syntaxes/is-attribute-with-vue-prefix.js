"use strict";
//#region lib/rules/syntaxes/is-attribute-with-vue-prefix.js
/**
* @author Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_is_attribute_with_vue_prefix = /* @__PURE__ */ require("../../_virtual/_rolldown/runtime.js").__commonJSMin(((exports, module) => {
	module.exports = {
		supported: ">=3.1.0",
		/** @param {RuleContext} context @returns {TemplateListener} */
		createTemplateBodyVisitor(context) {
			return { 
			/** @param {VAttribute} node */
"VAttribute[directive=false][key.name='is']"(node) {
				if (!node.value) return;
				if (node.value.value.startsWith("vue:")) context.report({
					node: node.value,
					messageId: "forbiddenIsAttributeWithVuePrefix"
				});
			} };
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_is_attribute_with_vue_prefix();
	}
});
