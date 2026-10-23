"use strict";
//#region lib/rules/syntaxes/v-model-argument.js
/**
* @author Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_v_model_argument = /* @__PURE__ */ require("../../_virtual/_rolldown/runtime.js").__commonJSMin(((exports, module) => {
	module.exports = {
		supported: ">=3.0.0",
		/** @param {RuleContext} context @returns {TemplateListener} */
		createTemplateBodyVisitor(context) {
			return { 
			/** @param {VDirectiveKey & { argument: VExpressionContainer | VIdentifier }} node */
"VAttribute[directive=true] > VDirectiveKey[name.name='model'][argument!=null]"(node) {
				context.report({
					node: node.argument,
					messageId: "forbiddenVModelArgument"
				});
			} };
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_v_model_argument();
	}
});
