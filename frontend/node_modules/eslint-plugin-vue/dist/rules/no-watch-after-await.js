"use strict";
const require_runtime = require("../_virtual/_rolldown/runtime.js");
const require_index = require("../utils/index.js");
//#region lib/rules/no-watch-after-await.js
/**
* @author Yosuke Ota
* See LICENSE file in root directory for full license.
*/
var require_no_watch_after_await = /* @__PURE__ */ require_runtime.__commonJSMin(((exports, module) => {
	const { ReferenceTracker } = require("@eslint-community/eslint-utils");
	const utils = require_index.default;
	/**
	* @param {CallExpression | ChainExpression} node
	* @returns {boolean}
	*/
	function isMaybeUsedStopHandle(node) {
		const parent = node.parent;
		if (parent) {
			if (parent.type === "VariableDeclarator") return true;
			if (parent.type === "AssignmentExpression") return true;
			if (parent.type === "CallExpression") return true;
			if (parent.type === "Property") return true;
			if (parent.type === "ArrayExpression") return true;
			if (parent.type === "ChainExpression") return isMaybeUsedStopHandle(parent);
		}
		return false;
	}
	module.exports = {
		meta: {
			type: "suggestion",
			docs: {
				description: "disallow asynchronously registered `watch`",
				categories: ["vue3-essential"],
				url: "https://eslint.vuejs.org/rules/no-watch-after-await.html"
			},
			fixable: null,
			schema: [],
			messages: { forbidden: "`watch` is forbidden after an `await` expression." }
		},
		/** @param {RuleContext} context */
		create(context) {
			const watchCallNodes = /* @__PURE__ */ new Set();
			/**
			* @typedef {object} SetupScopeData
			* @property {boolean} afterAwait
			* @property {[number,number]} range
			*/
			/** @type {Map<FunctionExpression | ArrowFunctionExpression | FunctionDeclaration, SetupScopeData>} */
			const setupScopes = /* @__PURE__ */ new Map();
			/**
			* @typedef {object} ScopeStack
			* @property {ScopeStack | null} upper
			* @property {FunctionExpression | ArrowFunctionExpression | FunctionDeclaration} scopeNode
			*/
			/** @type {ScopeStack | null} */
			let scopeStack = null;
			return utils.compositingVisitors({ 
			/** @param {Program} program */
Program(program) {
				const tracker = new ReferenceTracker(utils.getScope(context, program));
				const watchRefs = utils.iterateReferencesTraceMap(tracker, {
					watch: { [ReferenceTracker.CALL]: true },
					watchEffect: { [ReferenceTracker.CALL]: true }
				});
				for (const { node } of watchRefs) watchCallNodes.add(node);
			} }, utils.defineVueVisitor(context, {
				onSetupFunctionEnter(node) {
					setupScopes.set(node, {
						afterAwait: false,
						range: node.range
					});
				},
				/** @param {FunctionExpression | ArrowFunctionExpression | FunctionDeclaration} node */
				":function"(node) {
					scopeStack = {
						upper: scopeStack,
						scopeNode: node
					};
				},
				":function:exit"() {
					scopeStack &&= scopeStack.upper;
				},
				/** @param {AwaitExpression} node */
				AwaitExpression(node) {
					if (!scopeStack) return;
					const setupScope = setupScopes.get(scopeStack.scopeNode);
					if (!setupScope || !utils.inRange(setupScope.range, node)) return;
					setupScope.afterAwait = true;
				},
				/** @param {CallExpression} node */
				CallExpression(node) {
					if (!scopeStack) return;
					const setupScope = setupScopes.get(scopeStack.scopeNode);
					if (!setupScope || !setupScope.afterAwait || !utils.inRange(setupScope.range, node)) return;
					if (watchCallNodes.has(node) && !isMaybeUsedStopHandle(node)) context.report({
						node,
						messageId: "forbidden"
					});
				},
				onSetupFunctionExit(node) {
					setupScopes.delete(node);
				}
			}));
		}
	};
}));
//#endregion
Object.defineProperty(exports, "default", {
	enumerable: true,
	get: function() {
		return require_no_watch_after_await();
	}
});
