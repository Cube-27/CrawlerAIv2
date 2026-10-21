// openapi-typescript drives the TypeScript compiler API, which TypeScript 7 (native) no longer ships; its peer range
// is ^5. It gets its own TypeScript 5 as a dependency, while the app is still checked with TypeScript 7.
module.exports = {
  hooks: {
    readPackage(pkg) {
      if (pkg.name === "openapi-typescript") {
        delete pkg.peerDependencies?.typescript;
        pkg.dependencies = { ...pkg.dependencies, typescript: "5.9.3" };
      }
      return pkg;
    },
  },
};
