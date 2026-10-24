/** Strict read-only CP8 boundary. A decoded value is never command authority. */
import { parseSnapshot } from "./model.ts";

type ObjectValue = Record<string, unknown>;
type Check = (value: unknown) => void;
export type Source = "github" | "codex" | "resource_provider" | "hydra";
export interface ResourceRef { source: Source; kind: string; id: string }
export interface Revision { kind: "opaque" | "monotonic"; value: string }
export interface Coverage {
  state: "complete" | "partial" | "unavailable"; scope: string; returned_count: number;
  total_count: number | null; next_cursor: string | null; reason: string | null;
}
export interface EvidenceRef { observation_key: string; revision: Revision | null }
export interface Fact<T> { value: T | null; evidence: EvidenceRef[]; reason: string | null }
export interface Observation {
  key: string; resource: ResourceRef; revision: Revision | null;
  observed_at: string | null; last_attempt_at: string;
  availability: "current" | "stale" | "unavailable" | "unsupported";
  coverage: Coverage; reason: string | null; value: ObjectValue | null;
}
export interface RetryHint {
  observation_key: string; scope: string; after_seconds: number; basis: "provider" | "fallback";
}
export interface Execution { state: "unobserved" | "running" | "ended"; active_count: number | null }
export interface GoalRef { repository_id: number; issue_number: number; source_digest: string }
export interface RequirementRef { repository_id: number; path: string; revision: string; selector: string }
export interface ProjectView {
  repository_ref: ResourceRef; goal_refs: GoalRef[]; work_refs: ResourceRef[];
  admission: Fact<"allowed" | "paused" | "stopped">; execution: Fact<Execution>;
  attention_refs: ResourceRef[]; coverage: Coverage; source_refs: ResourceRef[];
}
export interface WorkView {
  issue_ref: ResourceRef; goal_refs: GoalRef[]; spec_refs: RequirementRef[]; requirement_refs: RequirementRef[];
  readiness: Fact<ObjectValue>; stage: Fact<string>; admission: Fact<string>; execution: Fact<Execution>;
  wait: Fact<"none" | ObjectValue>; delivery: Fact<string>; result: Fact<string>; cleanup: Fact<string>;
  decision: Record<"question" | "answer" | "acceptance" | "application", Fact<unknown>>;
  next_action: Fact<ObjectValue>; task_refs: ResourceRef[]; resource_refs: ResourceRef[]; evidence_refs: EvidenceRef[];
}
export interface CommandResult {
  request_id: string; action: string; target: ObjectValue; outcome: "applied" | "waiting" | "rejected" | "unknown";
  reason: string | null; effect_refs: ResourceRef[]; observed_refs: EvidenceRef[];
  receipt: ObjectValue | null; required_next: "none" | "refresh" | "reconcile" | "open_source";
}
export interface ProjectionV3 {
  schema_version: 3; runtime: ObjectValue; binding_epoch: string; request_id: string; assembled_at: string;
  observations: Observation[]; projects: ProjectView[]; work: WorkView[];
  relations: { from: ResourceRef; to: ResourceRef; kind: string; evidence: EvidenceRef[] }[];
  page: Coverage; capabilities: ObjectValue[]; retry_hints: RetryHint[]; request: CommandResult | null;
}
export const MAX_PROJECTION_BYTES = 1_048_576;
export class ProjectionError extends Error {
  readonly reason: string;
  constructor(reason = "invalid_response") {
    super(reason); this.reason = reason; this.name = "ProjectionError";
  }
}
function requireValue(value: unknown): asserts value {
  if (!value) throw new ProjectionError();
}
function object(value: unknown, keys: string): ObjectValue {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  const result = value as ObjectValue;
  const expected = keys.split(/\s+/);
  requireValue(Object.keys(result).length === expected.length &&
    expected.every(key => Object.hasOwn(result, key)));
  return result;
}
function plain(value: unknown): ObjectValue {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as ObjectValue;
}
function wellFormed(value: string): boolean {
  for (const point of value) {
    const n = point.codePointAt(0)!;
    if (n >= 0xd800 && n <= 0xdfff) return false;
  }
  return true;
}
function text(value: unknown, limit = 256, empty = false, controls = false): asserts value is string {
  requireValue(typeof value === "string" && (empty || value.length > 0) &&
    [...value].length <= limit && wellFormed(value));
  if (!controls) requireValue(!/[\u0000-\u001f\u007f]/u.test(value));
}
function integer(value: unknown, min = 0): asserts value is number {
  requireValue(typeof value === "number" && Number.isSafeInteger(value) && value >= min);
}
function one(value: unknown, choices: string): asserts value is string {
  requireValue(typeof value === "string" && choices.split(" ").includes(value));
}
function code(value: unknown): void {
  requireValue(typeof value === "string" && /^[a-z0-9][a-z0-9_-]{0,119}$/.test(value));
}
function nullable(value: unknown, check: Check): void { if (value !== null) check(value); }
function list(value: unknown, check: Check, limit = 4096): asserts value is unknown[] {
  requireValue(Array.isArray(value) && value.length <= limit);
  value.forEach(check);
}
function uuid(value: unknown): void {
  requireValue(typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value));
}
function hex(value: unknown, length: number): void {
  requireValue(typeof value === "string" && value.length === length && /^[0-9a-f]+$/.test(value));
}
const sha: Check = value => hex(value, 40);
const digest: Check = value => hex(value, 64);
function timestamp(value: unknown): void {
  requireValue(typeof value === "string" &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)$/.test(value));
  const year = Number(value.slice(0, 4)), month = Number(value.slice(5, 7)), day = Number(value.slice(8, 10));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  requireValue(year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]! &&
    Number(value.slice(11, 13)) < 24 && Number(value.slice(14, 16)) < 60 && Number(value.slice(17, 19)) < 60);
}
function ref(value: unknown): void {
  const v = object(value, "source kind id");
  one(v.source, "github codex resource_provider hydra");
  requireValue(typeof v.kind === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(v.kind));
  text(v.id);
}
function kindRef(value: unknown, kind: string): void {
  ref(value); const v = plain(value); requireValue(v.kind === kind);
  if (kind.startsWith("native_")) requireValue(v.source === "codex");
}
function revision(value: unknown): void {
  const v = object(value, "kind value"); one(v.kind, "opaque monotonic"); text(v.value);
  if (v.kind === "monotonic") requireValue(/^(?:0|[1-9][0-9]*)$/.test(v.value));
}
function coverage(value: unknown): void {
  const v = object(value, "state scope returned_count total_count next_cursor reason");
  one(v.state, "complete partial unavailable"); text(v.scope, 512); integer(v.returned_count);
  nullable(v.total_count, integer); nullable(v.next_cursor, x => text(x, 2048)); nullable(v.reason, code);
  if (v.total_count !== null) requireValue((v.total_count as number) >= v.returned_count);
  if (v.state === "complete") requireValue(v.next_cursor === null &&
    (v.total_count === null || v.total_count === v.returned_count));
  if (v.state === "unavailable") requireValue(v.returned_count === 0 && v.total_count === null && v.next_cursor === null);
  if (v.state !== "complete") requireValue(v.reason !== null);
}
function issueRef(value: unknown): void {
  const v = object(value, "repository_id issue_number"); integer(v.repository_id, 1); integer(v.issue_number, 1);
}
function goalRef(value: unknown): void {
  const v = object(value, "repository_id issue_number source_digest");
  integer(v.repository_id, 1); integer(v.issue_number, 1); digest(v.source_digest);
}
function parentRef(value: unknown): void {
  const v = plain(value); Object.hasOwn(v, "source_digest") ? goalRef(v) : issueRef(v);
}
function requirementRef(value: unknown): void {
  const v = object(value, "repository_id path revision selector");
  integer(v.repository_id, 1); text(v.path, 512);
  requireValue(!v.path.startsWith("/") && !v.path.startsWith("~") && !v.path.includes("\\") &&
    v.path.split("/").every(part => !["", ".", "..", ".git"].includes(part)));
  sha(v.revision); text(v.selector, 160);
}
function branch(value: unknown): void {
  requireValue(typeof value === "string" && /^hydra\/issue-[1-9][0-9]*$/.test(value));
}
function runtime(value: unknown): void {
  const v = object(value, "identity_schema package version code_digest code_digest_scope config_digest control_binding_digest identity_reason");
  requireValue(v.identity_schema === 1 && v.package === "openboa-hydra-sdlc" &&
    v.code_digest_scope === "package_sources_at_startup");
  nullable(v.version, x => { text(x, 128); requireValue(/^[\x20-\x7e]+$/.test(x)); });
  for (const key of ["code_digest", "config_digest", "control_binding_digest"]) nullable(v[key], digest);
  nullable(v.identity_reason, code);
}
function execution(value: unknown): void {
  const v = object(value, "state active_count"); one(v.state, "unobserved running ended"); nullable(v.active_count, integer);
}
function reported(value: unknown): void {
  requireValue(typeof value === "string" && /^[A-Za-z][A-Za-z0-9_-]{0,119}$/.test(value));
}
const sourceFields: Record<string, string> = {
  repository: "numeric_id full_name url contract_ref",
  issue: "number title state url work_kind parent_refs requirement_refs description_excerpt description_truncated",
  progress: "issue_ref attempt_id phase native_step head contract_revision branch expected_head expected_base published_head wait_reason next_action pending_action pr_ref completion_refs cleanup_state",
  pull_request: "number url state head base merge_commit required_check_refs review_refs",
  check: "producer name head status conclusion url", review: "producer head state unresolved_count url",
  native_task_metadata: "task_ref reported_status", native_history_page: "task_ref turns page",
  native_task: "task_ref assignment_ref execution question_ref schedule_refs open_ref",
  native_schedule: "schedule_ref task_ref status next_wake_at open_ref",
  resource: "resource_ref owner_ref activity preservation retirement open_ref",
  admission: "revision global_mode project_overrides gate_reason", ownership: "state scope_digest step_nonce",
};
function refs(value: unknown): void { list(value, ref); }
function bool(value: unknown): void { requireValue(typeof value === "boolean"); }
function sourceValue(kind: string, value: unknown): void {
  requireValue(Object.hasOwn(sourceFields, kind));
  const keys = kind === "admission" && Object.hasOwn(plain(value), "default_project_mode") ?
    sourceFields[kind]! + " default_project_mode" : sourceFields[kind]!;
  const v = object(value, keys);
  switch (kind) {
    case "repository": {
      integer(v.numeric_id, 1); text(v.full_name);
      requireValue(/^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}$/.test(v.full_name));
      text(v.url, 2048);
      if (v.contract_ref !== null) {
        const c = object(v.contract_ref, "path revision"); text(c.path, 512); nullable(c.revision, sha);
      }
      break;
    }
    case "issue":
      integer(v.number, 1); text(v.title, 512, true, true); one(v.state, "open closed"); text(v.url, 2048);
      nullable(v.work_kind, x => one(x, "goal work")); nullable(v.parent_refs, x => list(x, parentRef, 100));
      nullable(v.requirement_refs, x => list(x, requirementRef, 100));
      nullable(v.description_excerpt, x => text(x, 4096, true, true)); nullable(v.description_truncated, bool);
      requireValue((v.description_excerpt === null) === (v.description_truncated === null));
      break;
    case "progress":
      kindRef(v.issue_ref, "issue");
      for (const k of ["attempt_id", "native_step"]) nullable(v[k], uuid);
      for (const k of ["head", "contract_revision", "expected_head", "expected_base", "published_head"]) nullable(v[k], sha);
      nullable(v.branch, branch);
      for (const k of ["phase", "wait_reason", "next_action", "pending_action", "cleanup_state"]) nullable(v[k], code);
      nullable(v.pr_ref, ref); nullable(v.completion_refs, refs); break;
    case "pull_request":
      integer(v.number, 1); text(v.url, 2048); one(v.state, "open closed");
      for (const k of ["head", "base", "merge_commit"]) nullable(v[k], sha);
      nullable(v.required_check_refs, refs); nullable(v.review_refs, refs); break;
    case "check": case "review":
      nullable(v.producer, ref); nullable(v.head, sha); nullable(v.url, x => text(x, 2048));
      if (kind === "check") { text(v.name, 512); code(v.status); nullable(v.conclusion, code); }
      else { code(v.state); nullable(v.unresolved_count, integer); }
      break;
    case "native_task_metadata": case "native_history_page": {
      kindRef(v.task_ref, "native_task");
      if (kind === "native_task_metadata") reported(v.reported_status);
      else {
        const page = object(v.page, "order limit has_more");
        requireValue(page.order === "newest_first"); integer(page.limit, 1); bool(page.has_more);
        const turns = new Set<string>(), messages = new Set<string>();
        list(v.turns, turn => {
          const t = object(turn, "turn_ref reported_status started_at completed_at messages");
          kindRef(t.turn_ref, "native_turn"); unique(turns, t.turn_ref); reported(t.reported_status);
          nullable(t.started_at, timestamp); nullable(t.completed_at, timestamp);
          list(t.messages, message => {
            const m = object(message, "message_ref message_type"); kindRef(m.message_ref, "native_message");
            one(m.message_type, "userMessage agentMessage"); unique(messages, m.message_ref);
          });
        });
        requireValue(v.turns.length <= page.limit);
      }
      break;
    }
    case "native_task":
      kindRef(v.task_ref, "native_task"); nullable(v.assignment_ref, ref); nullable(v.execution, execution);
      nullable(v.question_ref, ref); nullable(v.schedule_refs, refs); nullable(v.open_ref, x => text(x, 2048)); break;
    case "native_schedule":
      kindRef(v.schedule_ref, "native_schedule"); nullable(v.task_ref, ref); code(v.status);
      nullable(v.next_wake_at, timestamp); nullable(v.open_ref, x => text(x, 2048)); break;
    case "resource":
      ref(v.resource_ref); nullable(v.owner_ref, ref);
      for (const k of ["activity", "preservation", "retirement"]) nullable(v[k], code);
      nullable(v.open_ref, x => text(x, 2048)); break;
    case "admission": {
      if (Object.hasOwn(v, "default_project_mode")) one(v.default_project_mode, "running stopped");
      integer(v.revision); one(v.global_mode, "running paused stopped");
      const overrides = plain(v.project_overrides); requireValue(Object.keys(overrides).length <= 1024);
      for (const [repository, mode] of Object.entries(overrides)) {
        requireValue(/^[a-z0-9][a-z0-9-]{0,38}\/[a-z0-9_.-]{1,100}$/.test(repository)); one(mode, "running paused stopped");
      }
      nullable(v.gate_reason, code); break;
    }
    case "ownership":
      one(v.state, "free absent owned busy native unknown"); nullable(v.scope_digest, digest); nullable(v.step_nonce, uuid); break;
  }
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") {
    const v = value as ObjectValue;
    return "{" + Object.keys(v).sort().map(key => JSON.stringify(key) + ":" + canonical(v[key])).join(",") + "}";
  }
  const encoded = JSON.stringify(value); requireValue(typeof encoded === "string"); return encoded;
}
function unique(seen: Set<string>, value: unknown): void {
  const key = canonical(value); requireValue(!seen.has(key)); seen.add(key);
}
function observation(value: unknown): void {
  const v = object(value, "key resource revision observed_at last_attempt_at availability coverage reason value");
  text(v.key, 512); ref(v.resource); const resource = plain(v.resource);
  requireValue(typeof resource.kind === "string" && Object.hasOwn(sourceFields, resource.kind));
  const owners:Record<string,string>={repository:"github",issue:"github",progress:"github",pull_request:"github",check:"github",review:"github",
    native_task_metadata:"codex",native_history_page:"codex",native_task:"codex",native_schedule:"codex",
    resource:"resource_provider",admission:"hydra",ownership:"hydra"};
  requireValue(resource.source===owners[resource.kind]);
  nullable(v.revision, revision); nullable(v.observed_at, timestamp); timestamp(v.last_attempt_at);
  one(v.availability, "current stale unavailable unsupported"); coverage(v.coverage); nullable(v.reason, code);
  const c = plain(v.coverage);
  if (v.availability === "current") requireValue(c.state !== "unavailable");
  if (v.availability === "current" || v.availability === "stale") {
    requireValue(v.observed_at !== null && v.value !== null); sourceValue(resource.kind, v.value);
    const data = plain(v.value);
    if (resource.kind === "admission")
      requireValue(canonical(v.revision) === canonical({kind: "monotonic", value: String(data.revision)}));
    else if (resource.kind === "repository") requireValue(resource.id === String(data.numeric_id));
    else if (resource.kind === "issue") {
      const locator = /^([1-9][0-9]*):([1-9][0-9]*)$/.exec(String(resource.id));
      requireValue(locator !== null); integer(Number(locator[1]), 1); integer(Number(locator[2]), 1);
      requireValue(locator[2] === String(data.number));
    }
  } else requireValue(v.value === null && v.observed_at === null && v.reason !== null && c.state === "unavailable");
  if (resource.kind === "native_task_metadata" || resource.kind === "native_history_page") {
    requireValue(v.revision === null);
    if (v.value !== null) {
      if (resource.kind === "native_task_metadata")
        requireValue(c.state === "complete" && c.returned_count === 1 && c.total_count === 1);
      else {
        const data = plain(v.value), page = plain(data.page);
        requireValue(c.state === "partial" && c.total_count === null &&
          c.returned_count === (data.turns as unknown[]).length &&
          c.reason === (page.has_more ? "more_pages" : "history_scope_unverified") &&
          (c.next_cursor !== null) === page.has_more);
      }
    }
  }
}
function evidence(value: unknown): void {
  const v = object(value, "observation_key revision"); text(v.observation_key, 512); nullable(v.revision, revision);
}
type Index = Map<string, Observation>;
function evidenceIn(value: unknown, index: Index): Observation {
  evidence(value); const e = value as EvidenceRef, source = index.get(e.observation_key);
  requireValue(source && canonical(source.revision) === canonical(e.revision)); return source;
}
function fact(value: unknown, check: Check, index: Index): void {
  const v = object(value, "value evidence reason"); list(v.evidence, evidence); nullable(v.reason, code);
  const seen = new Set<string>();
  for (const item of v.evidence) {
    const source = evidenceIn(item, index); requireValue(!seen.has(source.key)); seen.add(source.key);
    if (v.value !== null) requireValue(source.availability === "current" && source.coverage.state === "complete");
  }
  if (v.value === null) requireValue(v.reason !== null);
  else { requireValue(seen.size > 0 && v.reason === null); check(v.value); }
}
function repositoryName(value: unknown): string | null {
  if (typeof value !== "string" || !/^[\x00-\x7f]*$/.test(value)) return null;
  const name=value.toLowerCase();
  return /^[a-z0-9][a-z0-9-]{0,38}\/[a-z0-9_.-]{1,100}$/.test(name)?name:null;
}
function repositoryNames(value: unknown, index: Index): Set<string> {
  kindRef(value,"repository");const target=value as ResourceRef;requireValue(target.source==="github");
  if (target.id.startsWith("requested:")) {
    const name=repositoryName(target.id.slice(10));requireValue(name!==null);return new Set([name]);
  }
  requireValue(/^[1-9][0-9]*$/.test(target.id));integer(Number(target.id),1);
  const names=new Set<string>(),fallback=new Set<string>();
  for (const observed of index.values()) {
    if(canonical(observed.resource)!==canonical(target))continue;
    const requested=new Set<string>();
    for(const [field,prefix] of [[observed.key,"github:repository-request:"],[observed.coverage.scope,"repository-address:"]] as const){
      if(field.startsWith(prefix)){
        const name=repositoryName(field.slice(prefix.length));if(name===null)return new Set();requested.add(name);
      }
    }
    if(requested.size>1)return new Set();
    if(requested.size)for(const name of requested)names.add(name);
    else if(observed.value!==null){const name=repositoryName(observed.value.full_name);if(name!==null)fallback.add(name);}
  }
  return names.size?names:fallback;
}
function issueRepository(value: unknown): ResourceRef {
  kindRef(value,"issue");const issue=value as ResourceRef;requireValue(issue.source==="github");
  const locator=/^([1-9][0-9]*):([1-9][0-9]*)$/.exec(issue.id);requireValue(locator!==null);
  const repository=locator[1]!,number=locator[2]!;integer(Number(repository),1);integer(Number(number),1);
  return {source:"github",kind:"repository",id:repository};
}
export function projectAdmissionMode(snapshot: Record<string,unknown>, name: string): unknown {
  const overrides=plain(snapshot.project_overrides);
  return Object.hasOwn(overrides,name)?overrides[name]:snapshot.default_project_mode??"running";
}
function admissionFact(value: unknown, index: Index, names:Set<string>, binding:unknown): void {
  fact(value, x => one(x, "allowed paused stopped"), index);
  const v = value as Fact<string>;
  if(v.value===null)return;
  const sources=v.evidence.map(item=>evidenceIn(item,index)).filter(source=>source.resource.source==="hydra" && source.resource.kind==="admission");
  requireValue(sources.length>0 && binding!==null);
  for(const source of sources){
    requireValue(source.resource.id===binding);const snapshot=plain(source.value);let mode=snapshot.global_mode;
    if(mode==="running"){
      requireValue(names.size>0);const modes=new Set([...names].map(name=>projectAdmissionMode(snapshot,name)));
      requireValue(modes.size===1);mode=[...modes][0];
    }
    requireValue(v.value===(mode==="running"?"allowed":mode));
  }
}
function readiness(value: unknown): void {
  const v = object(value, "disposition source_ref source_revision interpretation_ref binding_ref extracted missing authority trust_reason");
  one(v.disposition, "actionable needs_info propose quarantined"); ref(v.source_ref); nullable(v.source_revision, revision);
  nullable(v.interpretation_ref, ref); nullable(v.binding_ref, ref);
  const e = object(v.extracted, "purpose_excerpt requirement_refs scope_excerpt");
  nullable(e.purpose_excerpt, x => text(x, 1024, true, true)); nullable(e.scope_excerpt, x => text(x, 1024, true, true));
  list(e.requirement_refs, requirementRef, 100);
  list(v.missing, item => {
    const m = object(item, "code detail owner_ref"); code(m.code); text(m.detail, 1024, true, true); nullable(m.owner_ref, ref);
  }, 100);
  one(v.authority, "confirmed missing unknown"); nullable(v.trust_reason, code);
}
function unmappedFact(value:unknown,check:Check,index:Index):void {
  fact(value,check,index);requireValue((value as Fact<unknown>).value===null);
}
function readinessFact(value:unknown,index:Index,issue:unknown):void {
  fact(value,readiness,index);const f=value as Fact<ObjectValue>;if(f.value===null)return;
  const v=f.value,target=issue as ResourceRef;
  requireValue(canonical(v.source_ref)===canonical(target) && v.disposition==="propose" &&
    v.authority==="unknown" && v.interpretation_ref===null && v.binding_ref===null);
  requireValue(canonical(v.extracted)===canonical({purpose_excerpt:null,requirement_refs:[],scope_excerpt:null}));
  requireValue(f.evidence.some(e=>{
    const source=evidenceIn(e,index);
    return target.source==="github" && target.kind==="issue" && canonical(source.resource)===canonical(target) &&
      canonical(source.revision)===canonical(v.source_revision);
  }));
}
function projectWorkRefs(value:unknown,repository:unknown):void {
  const seen=new Set<string>();list(value,item=>{
    requireValue(canonical(issueRepository(item))===canonical(repository));unique(seen,item);
  },128);
}
function parentRelation(value:unknown,index:Index):void {
  const v=object(value,"from to kind evidence");issueRepository(v.from);issueRepository(v.to);
  requireValue(v.kind==="parent");fact({value:"relation",evidence:v.evidence,reason:null},()=>{},index);
  requireValue((v.evidence as EvidenceRef[]).some(e=>{
    const source=evidenceIn(e,index),parents=source.value?.parent_refs;
    return canonical(source.resource)===canonical(v.from) && source.resource.kind==="issue" &&
      Array.isArray(parents) && parents.some(parent=>{
        const p=plain(parent);
        return canonical(v.to)===canonical({source:"github",kind:"issue",id:String(p.repository_id)+":"+String(p.issue_number)});
      });
  }));
}
function decision(value: unknown, index: Index): void {
  const v = object(value, "question answer acceptance application");
  // No implemented source mapping qualifies these axes. Metadata cannot enable it.
  for(const key of ["question","answer","acceptance","application"])fact(v[key],()=>requireValue(false),index);
}
function wait(value: unknown): void {
  if (value === "none") return;
  const v = object(value, "kind owner_ref wake_ref reason"); one(v.kind, "human external resource");
  nullable(v.owner_ref, ref); nullable(v.wake_ref, ref); code(v.reason);
}
function nextAction(value: unknown, index: Index): void {
  const v = object(value, "code target_ref rationale_excerpt evidence"); code(v.code); nullable(v.target_ref, ref);
  text(v.rationale_excerpt, 1024, true, true);
  fact({ value: "candidate", evidence: v.evidence, reason: null }, () => {}, index);
}
function assignment(value: unknown): void {
  const v = object(value, "attempt_id step_id head contract_revision spec_revision");
  uuid(v.attempt_id); uuid(v.step_id); sha(v.head); sha(v.contract_revision); nullable(v.spec_revision, sha);
}
function candidate(value: unknown): void {
  const v = object(value, "attempt_id head contract_revision"); uuid(v.attempt_id); sha(v.head); sha(v.contract_revision);
}
function target(value: unknown, action: string): void {
  if (action === "admission_set") {
    const v = plain(value);
    if (v.kind === "host") object(v, "kind");
    else { object(v, "kind repository_id"); requireValue(v.kind === "repository"); integer(v.repository_id, 1); }
  } else if (action === "workflow_step" || action === "work_create") {
    const v = object(value, action === "workflow_step" ? "repository_id issue_number" : "repository_id");
    Object.values(v).forEach(x => integer(x, 1));
  } else if (action === "cleanup") {
    const v = object(value, "kind repository_id issue_number source_attempt resource");
    requireValue(v.kind === "owned_resource"); integer(v.repository_id, 1); integer(v.issue_number, 1);
    uuid(v.source_attempt); ref(v.resource);
  } else ref(value);
}
function receipt(value: unknown, index: Index): void {
  const fields: Record<string, string> = {
    admission: "kind readback",
    checkpoint: "kind assignment outcome checkpoint_head progress_ref step_retired ticket_released",
    decision: "kind source_attempt round intent_ref context_ref resolved_ref resume_attempt",
    continuation: "kind progress_ref attempt_id head contract_revision boundary",
    verification: "kind candidate verdict review progress_ref evidence_refs",
    verification_review: "kind candidate assignment review progress_ref evidence_refs step_retired ticket_released",
    publication: "kind candidate branch observed_remote_head pr_ref review_request_refs progress_ref stage",
    delivery: "kind candidate pr_ref integration_base merge_commit post_merge issue_closed progress_ref",
    cleanup: "kind resource operation result evidence_refs",
  };
  const v = plain(value); requireValue(typeof v.kind === "string" && Object.hasOwn(fields, v.kind));
  object(v, fields[v.kind]!);
  if (v.kind === "admission") {
    const o = evidenceIn(v.readback, index);
    requireValue(o.availability === "current" && o.coverage.state === "complete" && o.resource.kind === "admission");
  }
  if (v.kind === "checkpoint") {
    assignment(v.assignment); one(v.outcome, "stopped candidate_ready failed needs_decision"); sha(v.checkpoint_head);
  }
  if (v.kind === "checkpoint" || v.kind === "verification_review")
    requireValue(v.step_retired === true && v.ticket_released === true);
  if (v.kind === "decision") {
    uuid(v.source_attempt); integer(v.round, 1); uuid(v.resume_attempt);
    for (const key of ["intent_ref", "context_ref", "resolved_ref"]) ref(v[key]);
  }
  if (v.kind === "continuation") {
    uuid(v.attempt_id); nullable(v.head, sha); sha(v.contract_revision);
    one(v.boundary, "progress_recorded assignment_returned existing_result_reconciled");
    requireValue(v.head !== null || v.boundary === "progress_recorded");
  }
  if (["verification", "verification_review", "publication", "delivery"].includes(v.kind)) candidate(v.candidate);
  if (v.kind === "verification") {
    one(v.verdict, "passed failed"); nullable(v.review, x => one(x, "pending accepted failed not_required"));
  }
  if (v.kind === "verification_review") {
    assignment(v.assignment); const a = plain(v.assignment), c = plain(v.candidate);
    requireValue(["attempt_id", "head", "contract_revision"].every(k => a[k] === c[k])); one(v.review, "accepted failed pending");
  }
  if (v.kind === "publication") {
    branch(v.branch); sha(v.observed_remote_head); requireValue(v.observed_remote_head === plain(v.candidate).head);
    nullable(v.pr_ref, ref); refs(v.review_request_refs); one(v.stage, "branch_published pr_ready publication_ready");
    requireValue(v.stage === "branch_published" || v.pr_ref !== null);
  }
  if (v.kind === "delivery") {
    ref(v.pr_ref); sha(v.integration_base); sha(v.merge_commit);
    one(v.post_merge, "pending success failed unknown"); nullable(v.issue_closed, bool);
  }
  if (v.kind === "cleanup") {
    ref(v.resource); one(v.operation, "preserve archive retire remove_schedule");
    requireValue(v.result === ({ preserve: "preserved", archive: "archived", retire: "retired", remove_schedule: "schedule_removed" } as ObjectValue)[v.operation]);
    requireValue(Array.isArray(v.evidence_refs) && v.evidence_refs.length > 0);
  }
  if (Object.hasOwn(v, "evidence_refs")) refs(v.evidence_refs);
  if (Object.hasOwn(v, "progress_ref")) ref(v.progress_ref);
}
function commandResult(value: unknown, index: Index): void {
  const v = object(value, "request_id action target outcome reason effect_refs observed_refs receipt required_next");
  uuid(v.request_id); one(v.action, "admission_set work_create workflow_step native_control cleanup open_record");
  target(v.target, v.action); one(v.outcome, "applied waiting rejected unknown"); nullable(v.reason, code);
  refs(v.effect_refs); list(v.observed_refs, e => { evidenceIn(e, index); });
  one(v.required_next, "none refresh reconcile open_source"); nullable(v.receipt, r => receipt(r, index));
  const kind = v.receipt === null ? null : plain(v.receipt).kind;
  if (v.action === "workflow_step" && ["publication", "delivery"].includes(String(kind))) {
    const pr = plain(v.receipt).pr_ref;
    if (pr !== null) {
      const locator = plain(pr);
      requireValue(locator.source === "github" && locator.kind === "pull_request");
      const parts = /^([1-9][0-9]*):([1-9][0-9]*)$/.exec(String(locator.id));
      requireValue(parts !== null);
      const repository = Number(parts[1]), number = Number(parts[2]);
      integer(repository, 1); integer(number, 1);
      requireValue(repository === plain(v.target).repository_id);
    }
  }
  if (kind!==null && v.action==="cleanup")
    requireValue(canonical(plain(v.receipt).resource)===canonical(plain(v.target).resource));
  if (v.outcome === "applied" && ["workflow_step", "cleanup"].includes(v.action))
    requireValue(v.receipt !== null);
  if (v.outcome === "applied" && kind === "publication")
    requireValue(plain(v.receipt).stage === "publication_ready");
  if (v.outcome === "applied" && kind === "delivery")
    requireValue(plain(v.receipt).post_merge === "success" && plain(v.receipt).issue_closed === true);
  if (v.action === "admission_set" || ["checkpoint", "decision"].includes(String(kind)))
    requireValue((v.receipt !== null) === (v.outcome === "applied"));
  if (kind !== null) requireValue(
    (v.action === "admission_set" && kind === "admission") ||
    (v.action === "workflow_step" && ["checkpoint", "decision", "continuation", "verification", "verification_review", "publication", "delivery"].includes(String(kind))) ||
    (v.action === "cleanup" && kind === "cleanup"));
  if (v.action === "workflow_step" && kind !== null && Object.hasOwn(plain(v.receipt), "progress_ref")) {
    const progress = plain(plain(v.receipt).progress_ref), target = plain(v.target);
    const expected = String(target.repository_id) + ":" + String(target.issue_number);
    requireValue(progress.source === "github");
    if (progress.kind === "progress") requireValue(progress.id === expected);
    else {
      requireValue(progress.kind === "issue_comment");
    }
    if (progress.kind === "issue_comment" || kind === "checkpoint" || kind === "continuation") {
      const proofs = (v.observed_refs as unknown[]).map(e => index.get(String(plain(e).observation_key))!)
        .filter(o => { const resource=plain(o.resource); return resource.source === "github" &&
          resource.kind === "progress" && resource.id === progress.id; });
      requireValue(proofs.length === 1);
      const proof=proofs[0]!;
      requireValue(proof.availability === "current" && plain(proof.coverage).state === "complete" &&
        proof.value !== null && canonical(plain(proof.value).issue_ref) ===
        canonical({source:"github",kind:"issue",id:expected}));
      if (kind === "checkpoint") {
        const checkpoint=plain(v.receipt), assignment=plain(checkpoint.assignment), source=plain(proof.value);
        requireValue(source.head === checkpoint.checkpoint_head && source.attempt_id === assignment.attempt_id &&
          source.contract_revision === assignment.contract_revision && source.native_step === null);
      }
      if (kind === "continuation") {
        const source=plain(proof.value), result=plain(v.receipt);
        requireValue(["attempt_id", "head", "contract_revision"].every(k=>source[k]===result[k]));
      }
    }
  }
}
function observations(value: unknown): Index {
  const index: Index = new Map();
  list(value, v => {
    observation(v); const o = v as Observation; requireValue(!index.has(o.key)); index.set(o.key, o);
  });
  return index;
}

/** Duplicate keys and non-integer JSON numbers are rejected before field validation. */
export function readProjectionJson(input: string | Uint8Array): unknown {
  let raw: string;
  try { raw = typeof input === "string" ? input : new TextDecoder("utf-8", { fatal: true }).decode(input); }
  catch { throw new ProjectionError(); }
  requireValue(wellFormed(raw) && new TextEncoder().encode(raw).length <= MAX_PROJECTION_BYTES);
  let i = 0;
  const space = () => { while (i < raw.length && /[ \r\n\t]/.test(raw[i]!)) i++; };
  function quoted(): string {
    const start = i++; let escaped = false;
    while (i < raw.length) {
      const c = raw[i++];
      if (c === '"' && !escaped) {
        const result = JSON.parse(raw.slice(start, i)) as string;
        requireValue(wellFormed(result)); return result;
      }
      if (c === "\\" && !escaped) escaped = true; else escaped = false;
    }
    throw new ProjectionError();
  }
  function value(depth: number): unknown {
    requireValue(depth <= 64); space();
    const c = raw[i];
    if (c === '"') return quoted();
    if (c === "{") {
      i++; const result: ObjectValue = {}; space(); if (raw[i] === "}") { i++; return result; }
      while (true) {
        space(); requireValue(raw[i] === '"'); const key = quoted(); space();
        requireValue(!Object.hasOwn(result, key) && raw[i++] === ":");
        Object.defineProperty(result, key, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        space(); if (raw[i] === "}") { i++; return result; } requireValue(raw[i++] === ",");
      }
    }
    if (c === "[") {
      i++; const result: unknown[] = []; space(); if (raw[i] === "]") { i++; return result; }
      while (true) {
        result.push(value(depth + 1)); space(); if (raw[i] === "]") { i++; return result; }
        requireValue(raw[i++] === ",");
      }
    }
    for (const [token, result] of [["true", true], ["false", false], ["null", null]] as const) {
      if (raw.slice(i, i + token.length) === token) { i += token.length; return result; }
    }
    const token = /^(?:0|[1-9][0-9]*)/.exec(raw.slice(i));
    requireValue(token); i += token[0].length; const result = Number(token[0]); integer(result); return result;
  }
  try { const result = value(0); space(); requireValue(i === raw.length); return result; }
  catch { throw new ProjectionError(); }
}
function inputValue(input: unknown): ObjectValue {
  const v = plain(typeof input === "string" || input instanceof Uint8Array ? readProjectionJson(input) : input);
  if (Object.hasOwn(v, "reply_profile") || Object.hasOwn(v, "handoff"))
    throw new ProjectionError("unsupported_reply_profile");
  let bytes: number;
  try { bytes = new TextEncoder().encode(JSON.stringify(v)).length; } catch { throw new ProjectionError(); }
  requireValue(bytes <= MAX_PROJECTION_BYTES); return v;
}
function boundCommandResult(value:unknown,index:Index,binding:unknown):void {
  commandResult(value,index);const result=plain(value);
  if(result.outcome==="applied" && !["admission_set","workflow_step"].includes(String(result.action)))
    throw new ProjectionError("unsupported_command_source");
  if(result.receipt===null)return;
  const receipt=plain(result.receipt);
  // Each future operation must qualify its paired producer and consumers first.
  if(!["admission","checkpoint"].includes(String(receipt.kind)))throw new ProjectionError("unsupported_receipt_source");
  if(receipt.kind!=="admission")return;
  const source=evidenceIn(receipt.readback,index);
  requireValue(typeof binding==="string" && canonical(source.resource)===canonical({source:"hydra",kind:"admission",id:binding}));
}
function projectionDocument(input: unknown, sourceFrame: boolean): ProjectionV3 {
  const v = inputValue(input);
  object(v, "schema_version runtime binding_epoch request_id assembled_at observations projects work relations page capabilities retry_hints request");
  requireValue(v.schema_version === 3); runtime(v.runtime); uuid(v.binding_epoch); uuid(v.request_id); timestamp(v.assembled_at);
  const index = observations(v.observations);
  const hints = new Set<string>();
  list(v.retry_hints, x => {
    const h = object(x, "observation_key scope after_seconds basis"); text(h.observation_key, 512); text(h.scope);
    integer(h.after_seconds); one(h.basis, "provider fallback");
    const marker = canonical([h.observation_key, h.scope]); requireValue(!hints.has(marker)); hints.add(marker);
    const o = index.get(h.observation_key);
    requireValue(o && o.availability !== "unsupported" &&
      (o.availability === "unavailable" || o.availability === "stale" ||
       o.coverage.state !== "complete" || ["rate_limited", "provider_wait"].includes(String(o.reason))));
  });
  const projects = new Set<string>(), work = new Set<string>(), membership = new Set<string>();
  list(v.projects, item => {
    const p = object(item, "repository_ref goal_refs work_refs admission execution attention_refs coverage source_refs");
    kindRef(p.repository_ref, "repository"); unique(projects, p.repository_ref);
    list(p.goal_refs, goalRef, 100); projectWorkRefs(p.work_refs,p.repository_ref);
    for (const reference of p.work_refs as unknown[]) membership.add(canonical(reference));
    admissionFact(p.admission, index,repositoryNames(p.repository_ref,index),plain(v.runtime).control_binding_digest); unmappedFact(p.execution, execution, index);
    refs(p.attention_refs); coverage(p.coverage); refs(p.source_refs);
    if (sourceFrame) requireValue(plain(p.coverage).returned_count === (p.work_refs as unknown[]).length);
  }, 1024);
  list(v.work, item => {
    const w = object(item, "issue_ref goal_refs spec_refs requirement_refs readiness stage admission execution wait decision delivery result cleanup next_action task_refs resource_refs evidence_refs");
    kindRef(w.issue_ref, "issue"); unique(work, w.issue_ref); requireValue(membership.has(canonical(w.issue_ref))); list(w.goal_refs, goalRef, 100);
    list(w.spec_refs, requirementRef, 100); list(w.requirement_refs, requirementRef, 100);
    readinessFact(w.readiness,index,w.issue_ref); unmappedFact(w.stage, x => one(x, "prepare design implement verify deliver observe complete"), index);
    admissionFact(w.admission, index,repositoryNames(issueRepository(w.issue_ref),index),plain(v.runtime).control_binding_digest); unmappedFact(w.execution, execution, index); unmappedFact(w.wait, wait, index);
    decision(w.decision, index); unmappedFact(w.delivery, x => one(x, "candidate published merged post_merge_verified deployment_observed"), index);
    unmappedFact(w.result, x => one(x, "incomplete complete cancelled"), index); unmappedFact(w.cleanup, x => one(x, "not_required pending complete"), index);
    unmappedFact(w.next_action, x => nextAction(x, index), index);
    refs(w.task_refs); refs(w.resource_refs); list(w.evidence_refs, e => { evidenceIn(e, index); });
  }, 512);
  list(v.relations,item=>parentRelation(item,index));
  coverage(v.page);
  if (sourceFrame) requireValue(plain(v.page).returned_count === (v.projects as unknown[]).length);
  list(v.capabilities, item => {
    const c = object(item, "source operation state actor qualification_ref reason");
    one(c.source, "github codex resource_provider hydra"); text(c.operation); one(c.state, "available unsupported unavailable");
    one(c.actor, "core native_actor provider"); nullable(c.qualification_ref, x => text(x, 2048)); nullable(c.reason, code);
    requireValue(c.state === "available" ? c.qualification_ref !== null && c.reason === null : c.reason !== null);
  });
  nullable(v.request, r => boundCommandResult(r,index,plain(v.runtime).control_binding_digest));
  return v as unknown as ProjectionV3;
}
export function parseProjection(input: unknown): ProjectionV3 {
  return projectionDocument(input,true);
}
// Accumulated display membership can span several validated source pages.
// Use only for displays assembled from frames already checked by parseProjection.
export function validateProjectionView(view: ProjectionV3): void {
  projectionDocument(view,false);
}
export function parseStandardReply(input: unknown): ObjectValue {
  const v = inputValue(input); object(v, "command_schema runtime binding_epoch request observations");
  requireValue(v.command_schema === 1); runtime(v.runtime); nullable(v.binding_epoch, uuid);
  boundCommandResult(v.request,observations(v.observations),plain(v.runtime).control_binding_digest); return v;
}
export function parseReadOnlyProjection(input: unknown) {
  const v = inputValue(input);
  if (v.schema_version === 2) return { schema_version: 2 as const, read_only: true as const,
    missing_axes: "unknown" as const, snapshot: parseSnapshot(v) };
  return { schema_version: 3 as const, read_only: true as const,
    missing_axes: null, snapshot: parseProjection(v) };
}
