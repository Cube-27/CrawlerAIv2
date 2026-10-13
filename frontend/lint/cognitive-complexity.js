// Cognitive complexity per function (C11, INV-18), as SonarSource defines it (G. Ann Campbell, "Cognitive
// Complexity", 2017; SonarCloud rule S3776). oxlint-plugin-complexity measures it; its own rule always gates
// cyclomatic complexity as well, and C11 allows one complexity check only, so this rule reports the cognitive
// score alone. The threshold lives in vite.config.ts.
import { definePlugin, defineRule } from "vite-plus/lint/plugins";
import { createCognitiveVisitor } from "oxlint-plugin-complexity";

const cognitiveComplexity = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Limit the cognitive complexity of each function" },
    schema: [
      {
        type: "object",
        properties: { max: { type: "integer", minimum: 0 } },
        required: ["max"],
        additionalProperties: false,
      },
    ],
  },
  createOnce(context) {
    let max = 0;
    return {
      before() {
        max = context.options[0].max;
      },
      ...createCognitiveVisitor(context, ({ total }, node) => {
        if (total > max) {
          context.report({
            node,
            message: `Cognitive complexity is ${total}; at most ${max} is allowed. Extract named steps.`,
          });
        }
      }),
    };
  },
});

export default definePlugin({
  meta: { name: "crawlerai" },
  rules: { "cognitive-complexity": cognitiveComplexity },
});
