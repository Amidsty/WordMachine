"use strict";
//#region lib/rules/syntaxes/dynamic-directive-arguments.js
/**
* @author Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_dynamic_directive_arguments = /* @__PURE__ */ require("../../_virtual/_rolldown/runtime.js").__commonJSMin(((exports, module) => {
	module.exports = {
		supported: ">=2.6.0",
		/** @param {RuleContext} context @returns {TemplateListener} */
		createTemplateBodyVisitor(context) {
			/**
			* Reports dynamic argument node
			* @param {VExpressionContainer} dynamicArgument node of dynamic argument
			* @returns {void}
			*/
			function reportDynamicArgument(dynamicArgument) {
				context.report({
					node: dynamicArgument,
					messageId: "forbiddenDynamicDirectiveArguments"
				});
			}
			return { "VAttribute[directive=true] > VDirectiveKey > VExpressionContainer": reportDynamicArgument };
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_dynamic_directive_arguments();
	}
});
