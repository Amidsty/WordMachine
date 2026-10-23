//#region lib/configs/index.ts
const configs = {
	base: require("./base.js"),
	"vue2-essential": require("./vue2-essential.js"),
	"vue2-strongly-recommended": require("./vue2-strongly-recommended.js"),
	"vue2-strongly-recommended-error": require("./vue2-strongly-recommended-error.js"),
	"vue2-recommended": require("./vue2-recommended.js"),
	"vue2-recommended-error": require("./vue2-recommended-error.js"),
	essential: require("./vue3-essential.js"),
	"strongly-recommended": require("./vue3-strongly-recommended.js"),
	"strongly-recommended-error": require("./vue3-strongly-recommended-error.js"),
	recommended: require("./vue3-recommended.js"),
	"recommended-error": require("./vue3-recommended-error.js"),
	"flat/base": require("./flat/base.js"),
	"flat/vue2-essential": require("./flat/vue2-essential.js"),
	"flat/vue2-strongly-recommended": require("./flat/vue2-strongly-recommended.js"),
	"flat/vue2-strongly-recommended-error": require("./flat/vue2-strongly-recommended-error.js"),
	"flat/vue2-recommended": require("./flat/vue2-recommended.js"),
	"flat/vue2-recommended-error": require("./flat/vue2-recommended-error.js"),
	"flat/essential": require("./flat/vue3-essential.js"),
	"flat/strongly-recommended": require("./flat/vue3-strongly-recommended.js"),
	"flat/strongly-recommended-error": require("./flat/vue3-strongly-recommended-error.js"),
	"flat/recommended": require("./flat/vue3-recommended.js"),
	"flat/recommended-error": require("./flat/vue3-recommended-error.js"),
	"no-layout-rules": require("./no-layout-rules.js")
};
//#endregion
module.exports = configs;
