import ts from "typescript";
import { createHash } from "node:crypto";

export const parserVersion = `typescript-${ts.version}/1`;

export function parseFile(path, source, revision) {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  const lines = source.split(/\r?\n/);
  const chunks = [];
  const imports = [];
  function add(node, symbol, kind) {
    const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line;
    const end = file.getLineAndCharacterOfPosition(node.getEnd()).line;
    const quote = lines.slice(start, end + 1).join("\n");
    if (!quote.trim()) return;
    chunks.push({
      id: createHash("sha256")
        .update(
          `${revision}:${path}:${symbol}:${start}:${end}:${parserVersion}`,
        )
        .digest("hex")
        .slice(0, 24),
      revision,
      path,
      symbol,
      kind,
      start_line: start + 1,
      end_line: end + 1,
      quote,
    });
  }
  function visit(node) {
    if (
      ts.isImportDeclaration(node) &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      imports.push({
        from: path,
        to: node.moduleSpecifier.text,
        kind: "import",
        resolution: "unresolved",
      });
    }
    if (
      ts.isFunctionDeclaration(node) ||
      ts.isClassDeclaration(node) ||
      ts.isMethodDeclaration(node)
    ) {
      add(
        node,
        node.name?.getText(file) ?? "<anonymous>",
        ts.isClassDeclaration(node) ? "class" : "function",
      );
    } else if (ts.isVariableStatement(node)) {
      add(
        node,
        node.declarationList.declarations
          .map((d) => d.name.getText(file))
          .join(", "),
        "variable",
      );
    } else if (
      ts.isExpressionStatement(node) &&
      /^(test|it|describe)\s*\(/.test(node.getText(file))
    ) {
      add(node, node.expression.arguments?.[0]?.text ?? "<test>", "test");
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  if (!chunks.length && source.trim()) add(file, path, "file");
  return {
    chunks,
    imports,
    diagnostics: file.parseDiagnostics.map((d) =>
      ts.flattenDiagnosticMessageText(d.messageText, "\n"),
    ),
  };
}

if (process.argv[1]?.endsWith("parse.mjs")) {
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 12_000_000)
      throw new Error("Index input exceeds size limit");
  }
  const { files, revision } = JSON.parse(input);
  process.stdout.write(
    JSON.stringify({
      version: parserVersion,
      files: files.map((f) => ({
        path: f.path,
        ...parseFile(f.path, f.source, revision),
      })),
    }),
  );
}
