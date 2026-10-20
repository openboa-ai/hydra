// Rust's actual serialized accepted read results enter the real TS consumer.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseProjection, parseReadOnlyProjection, parseStandardReply } from "../src/projection.ts";

const bytes = readFileSync(0);
assert.ok(bytes.length <= 4_194_304);
const vectors = JSON.parse(bytes.toString("utf8"));
let passed = 0, rejected = 0;
for (const vector of vectors) {
  if (!vector.accepted) {
    assert.equal(vector.rejected, true);
    assert.equal(Object.hasOwn(vector, "wire"), false);
    rejected++;
    continue;
  }
  const value = vector.profile === "projection" ? parseProjection(vector.wire) :
    vector.profile === "legacy" ? parseReadOnlyProjection(vector.wire).snapshot : parseStandardReply(vector.wire);
  for (const expected of vector.expected) {
    let actual = value;
    for (const key of expected.path) actual = actual[key];
    assert.deepEqual(actual, expected.value, vector.name);
  }
  passed++;
}
process.stdout.write(JSON.stringify({ passed, rejected }));
