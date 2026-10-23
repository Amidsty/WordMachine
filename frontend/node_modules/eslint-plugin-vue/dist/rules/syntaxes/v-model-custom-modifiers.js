"use strict";
//#region lib/rules/syntaxes/v-model-custom-modifiers.js
/**
* @author Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_v_model_custom_modifiers = /* @__PURE__ */ require("../../_virtual/_rolldown/runtime.js").__commonJSMin(((exports, module) => {
	const BUILTIN_MODIFIERS = /* @__PURE__ */ new Set([
		"lazy",
		"number",
		"trim"
	]);
	module.exports = {
		supported: ">=3.0.0",
		/** @param {RuleContext} context @returns {TemplateListener} */
		createTemplateBodyVisitor(context) {
			return { 
			/** @param {VDirectiveKey} node */
"VAttribute[directive=true] > VDirectiveKey[name.name='model'][modifiers.length>0]"(node) {
				for (const modifier of node.modifiers) if (!BUILTIN_MODIFIERS.has(modifier.name)) context.report({
					node: modifier,
					messageId: "forbiddenVModelCustomModifiers"
				});
			} };
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_v_model_custom_modifiers();
	}
});
