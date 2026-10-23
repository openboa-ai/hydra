import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { parseProjection, ProjectionError } from "../src/projection.ts";

const script = fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_connection_guards.py", import.meta.url));
const result = spawnSync("python3", ["-I", script], { encoding: "utf8", timeout: 60_000, maxBuffer: 4_194_304 });
assert.equal(result.status, 0, "The actual connection-guard producer failed");
const rows = JSON.parse(result.stdout) as { name: string; accepted: boolean; wire: string }[];
assert.equal(rows.length, 6);
for (const row of rows) {
  test("actual connection-guard source: " + row.name, () => {
    if (row.accepted) parseProjection(row.wire);
    else assert.throws(() => parseProjection(row.wire), ProjectionError);
  });
}
