import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  MAX_PROJECTION_BYTES, ProjectionError, parseProjection, parseReadOnlyProjection,
  parseStandardReply, readProjectionJson,
} from "../src/projection.ts";

const emitter = fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_wire.py", import.meta.url));
const emitted = spawnSync("python3", ["-I", emitter], { encoding: "utf8", timeout: 60_000, maxBuffer: 4_194_304 });
assert.equal(emitted.status, 0, "The actual Python producer fixture did not complete");
const vectors = JSON.parse(emitted.stdout) as {
  name: string; profile: string; accepted: boolean; producer_rejected: boolean;
  wire: string; expected: { path: (string | number)[]; value: unknown }[];
}[];
test("one input set contains accepted source controls and rejected protocol controls", () => {
  assert.ok(vectors.length >= 16);
  assert.ok(vectors.filter(v => v.accepted).length >= 6);
  assert.ok(vectors.filter(v => !v.accepted).length >= 10);
  assert.equal(new Set(vectors.map(v => v.name)).size, vectors.length);
});
for (const vector of vectors) {
  test("actual Python bytes: " + vector.name, () => {
    assert.equal(vector.producer_rejected, !vector.accepted);
    const consume = () => vector.profile === "projection" ? parseProjection(vector.wire) :
      vector.profile === "legacy" ? parseReadOnlyProjection(vector.wire).snapshot : parseStandardReply(vector.wire);
    if (!vector.accepted) {
      assert.throws(consume, ProjectionError);
      return;
    }
    const value = consume();
    for (const expected of vector.expected) {
      let actual: unknown = value;
      for (const key of expected.path) actual = (actual as Record<string | number, unknown>)[key];
      assert.deepEqual(actual, expected.value, vector.name + ": " + expected.path.join("/"));
    }
  });
}
test("v2 is explicitly read-only with absent v3 axes unknown", () => {
  const v = vectors.find(v => v.profile === "legacy")!;
  const result = parseReadOnlyProjection(v.wire);
  assert.equal(result.schema_version, 2);
  assert.equal(result.read_only, true);
  assert.equal(result.missing_axes, "unknown");
  assert.throws(() => parseProjection(v.wire), ProjectionError);
});
test("invalid UTF-8, lone surrogates, duplicate keys and non-integer JSON fail closed", () => {
  for (const raw of [new Uint8Array([0xc0, 0x80]), '{"a":1,"a":2}', '{"a":"\\ud800"}',
    '{"a":NaN}', '{"a":1.0}', '{"a":1e2}', '{"a":9007199254740992}', '{"a":-1}', '{"a":true,}']) {
    assert.throws(() => readProjectionJson(raw), ProjectionError);
  }
  assert.deepEqual(readProjectionJson('{"a":true,"b":null,"c":[0,9007199254740991]}'),
    { a: true, b: null, c: [0, 9007199254740991] });
});
test("UTF-8 byte and nesting bounds hold before consumer assignment", () => {
  assert.throws(() => readProjectionJson(" ".repeat(MAX_PROJECTION_BYTES + 1)), ProjectionError);
  assert.throws(() => readProjectionJson("[".repeat(66) + "0" + "]".repeat(66)), ProjectionError);
});
test("native-only payloads have a typed rejection and never become a standard read result", () => {
  const vector = vectors.find(v => v.name === "native-only-reply-never-enters-standard-pipeline")!;
  assert.throws(() => parseStandardReply(vector.wire), (error: unknown) =>
    error instanceof ProjectionError && error.reason === "unsupported_reply_profile" &&
      !error.message.includes("SYNTHETIC_NATIVE_PAYLOAD_CANARY"));
  assert.throws(() => parseReadOnlyProjection(vector.wire), ProjectionError);
});
