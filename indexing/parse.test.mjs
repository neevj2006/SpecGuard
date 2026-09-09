import { test } from "node:test";
import assert from "node:assert/strict";
import { parseFile } from "./parse.mjs";

test("AST chunks retain exact line spans and stable IDs", () => {
  const source =
    'import { x } from "./x";\nexport function greet() {\n  return x;\n}\n';
  const result = parseFile("src/a.ts", source, "a".repeat(40));
  assert.equal(
    result.chunks[0].quote,
    "export function greet() {\n  return x;\n}",
  );
  assert.equal(result.chunks[0].start_line, 2);
  assert.equal(result.chunks[0].end_line, 4);
  assert.equal(result.imports[0].to, "./x");
  assert.deepEqual(result, parseFile("src/a.ts", source, "a".repeat(40)));
});

test("TSX and test calls are retained", () => {
  const result = parseFile(
    "view.tsx",
    'export const View = () => <main>Hello</main>;\ntest("renders", () => {});',
    "b".repeat(40),
  );
  assert.equal(result.chunks[0].symbol, "View");
  assert.ok(result.chunks.some((c) => c.kind === "test"));
});
