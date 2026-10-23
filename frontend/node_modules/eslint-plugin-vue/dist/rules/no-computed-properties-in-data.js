"use strict";
const require_runtime = require("../_virtual/_rolldown/runtime.js");
const require_index = require("../utils/index.js");
//#region lib/rules/no-computed-properties-in-data.js
/**
* @author  Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_no_computed_properties_in_data = /* @__PURE__ */ require_runtime.__commonJSMin(((exports, module) => {
	const utils = require_index.default;
	/**
	* @typedef {import('../utils').VueObjectData} VueObjectData
	*/
	module.exports = {
		meta: {
			type: "problem",
			docs: {
				description: "disallow accessing computed properties in `data`",
				categories: ["vue3-essential", "vue2-essential"],
				url: "https://eslint.vuejs.org/rules/no-computed-properties-in-data.html"
			},
			fixable: null,
			schema: [],
			messages: { cannotBeUsed: "The computed property cannot be used in `data()` because it is before initialization." }
		},
		/** @param {RuleContext} context */
		create(context) {
			/** @type {Map<ObjectExpression, {data: FunctionExpression | ArrowFunctionExpression, computedNames:Set<string>}>} */
			const contextMap = /* @__PURE__ */ new Map();
			/**
			* @typedef {object} ScopeStack
			* @property {ScopeStack | null} upper
			* @property {FunctionExpression | FunctionDeclaration | ArrowFunctionExpression} node
			*/
			/** @type {ScopeStack | null} */
			let scopeStack = null;
			return utils.compositingVisitors({
				/**
				* @param {FunctionExpression | FunctionDeclaration | ArrowFunctionExpression} node
				*/
				":function"(node) {
					scopeStack = {
						upper: scopeStack,
						node
					};
				},
				":function:exit"() {
					scopeStack &&= scopeStack.upper;
				}
			}, utils.defineVueVisitor(context, {
				onVueObjectEnter(node) {
					const dataProperty = utils.findProperty(node, "data");
					if (!dataProperty || dataProperty.value.type !== "FunctionExpression" && dataProperty.value.type !== "ArrowFunctionExpression") return;
					const computedNames = /* @__PURE__ */ new Set();
					const computedProperties = utils.iterateProperties(node, /* @__PURE__ */ new Set(["computed"]));
					for (const computed of computedProperties) computedNames.add(computed.name);
					contextMap.set(node, {
						data: dataProperty.value,
						computedNames
					});
				},
				/**
				* @param {MemberExpression} node
				* @param {VueObjectData} vueData
				*/
				MemberExpression(node, vueData) {
					if (!scopeStack || !utils.isThis(node.object, context)) return;
					const ctx = contextMap.get(vueData.node);
					if (!ctx || ctx.data !== scopeStack.node) return;
					const name = utils.getStaticPropertyName(node);
					if (!name || !ctx.computedNames.has(name)) return;
					context.report({
						node,
						messageId: "cannotBeUsed"
					});
				}
			}));
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_no_computed_properties_in_data();
	}
});
