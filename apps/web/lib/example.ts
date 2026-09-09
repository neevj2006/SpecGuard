import type { Run, Verdict } from "./types";

const criteria = [
  ["Apply a 10% discount to eligible orders.", "satisfied"],
  ["Keep the discounted total at or above zero.", "satisfied"],
  ["Reject expired promotion codes.", "partially_satisfied"],
  ["Limit each promotion to one use per customer.", "not_satisfied"],
  ["Send a receipt after the order is confirmed.", "not_verifiable"],
] as const;
const quotes = [
  "export function applyDiscount(order: Order, promotion: Promotion) {\n  if (!isEligible(order, promotion)) return order.total;\n\n  const discount = order.total * 0.1;\n  return Math.max(0, order.total - discount);\n}",
  "export function calculateTotal(total: number, discount: number) {\n  return Math.max(0, total - discount);\n}",
  "export function isActive(promotion: Promotion) {\n  return promotion.enabled;\n  // Expiration validation is not implemented yet.\n}",
  "export async function redeem(code: string, customer: Customer) {\n  const promotion = await findPromotion(code);\n  return applyPromotion(customer.cart, promotion);\n}",
];
export const exampleRun: Run = {
  id: "example-review",
  repository: "acme/checkout",
  base_sha: "8b2ac19".padEnd(40, "0"),
  head_sha: "c7e41d2".padEnd(40, "0"),
  requirement: criteria.map(([text]) => `- ${text}`).join("\n"),
  created_at: "2026-09-08T14:32:00Z",
  duration_ms: 2840,
  versions: {
    parser: "typescript-5.9.3/1",
    index: "1",
    retriever: "bm25/1",
    verifier: "illustrative",
    model: "illustrative",
    prompt: "1",
  },
  excluded: [],
  results: criteria.map(([text, verdict], i) => ({
    criterion: {
      id: `AC-${String(i + 1).padStart(2, "0")}`,
      text,
      source_text: text,
    },
    verdict: verdict as Verdict,
    rationale: [
      "The eligible-order branch calculates a 10% reduction and returns the adjusted total. This is a static reading of the implementation.",
      "Math.max clamps the adjusted total to zero, preventing a negative result.",
      "The enabled flag is checked, but the expiration timestamp is not evaluated.",
      "The redemption path applies the promotion without checking prior use for this customer.",
      "The selected source does not establish whether a receipt is sent after confirmation.",
    ][i],
    confidence: i === 4 ? null : [0.94, 0.98, 0.86, 0.91][i],
    uncertainty:
      i === 4
        ? "Receipt delivery may occur in a service outside this change."
        : "Static inference; behavior has not been tested in this run.",
    suggestion:
      i === 4
        ? "Confirm which service owns receipt delivery, then add an integration test."
        : "Add a focused test for this acceptance criterion. Tests shown as source have not been executed.",
    tests: { status: "not_run" },
    evidence:
      i === 4
        ? []
        : [
            {
              id: `e-${i}`,
              path: [
                "src/pricing/discount.ts",
                "src/pricing/total.ts",
                "src/promotions/validate.ts",
                "src/promotions/redeem.ts",
              ][i],
              start_line: 18,
              end_line: 18 + quotes[i].split("\n").length - 1,
              quote: quotes[i],
              revision: "c7e41d2".padEnd(40, "0"),
              symbol: ["applyDiscount", "calculateTotal", "isActive", "redeem"][
                i
              ],
              kind: "function",
              score: 3.48,
              changed: true,
            },
          ],
  })),
};
