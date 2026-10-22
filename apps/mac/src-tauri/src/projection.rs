//! Closed CP8 read boundary. Decoding never grants execution or command authority.
use crate::protocol::{RuntimeIdentity, Snapshot, MAX_OUTPUT};
use serde::{de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor}, Serialize};
use serde_json::{Map, Number, Value};
use std::{cell::Cell, collections::{BTreeMap, HashMap, HashSet}, fmt};

type R = Result<(), &'static str>;
type Index<'a> = HashMap<&'a str, &'a Value>;
const INVALID: &str = "invalid_response";
const MAX_INTEGER: u64 = 9_007_199_254_740_991;

fn need(value: bool) -> R { if value { Ok(()) } else { Err(INVALID) } }
fn string(value: &Value) -> Result<&str, &'static str> { value.as_str().ok_or(INVALID) }
fn object(value: &Value, keys: &str) -> R {
    let map = value.as_object().ok_or(INVALID)?;
    let expected: Vec<_> = keys.split_ascii_whitespace().collect();
    need(map.len() == expected.len() && expected.iter().all(|k| map.contains_key(*k)))
}
fn text(value: &Value, limit: usize, empty: bool, controls: bool) -> R {
    let s = string(value)?;
    need((empty || !s.is_empty()) && s.chars().count() <= limit &&
         (controls || !s.chars().any(|c| c < '\u{20}' || c == '\u{7f}')))
}
fn short(value: &Value) -> R { text(value, 256, false, false) }
fn number(value: &Value) -> R { need(value.as_u64().is_some_and(|n| n <= MAX_INTEGER)) }
fn positive(value: &Value) -> R { number(value)?; need(value.as_u64().unwrap() > 0) }
fn boolean(value: &Value) -> R { need(value.is_boolean()) }
fn one(value: &Value, choices: &str) -> R {
    need(choices.split_ascii_whitespace().any(|c| value.as_str() == Some(c)))
}
fn optional(value: &Value, check: impl Fn(&Value) -> R) -> R {
    if value.is_null() { Ok(()) } else { check(value) }
}
fn list(value: &Value, check: impl Fn(&Value) -> R, limit: usize) -> R {
    let a = value.as_array().ok_or(INVALID)?; need(a.len() <= limit)?;
    for item in a { check(item)?; } Ok(())
}
fn code(value: &Value) -> R {
    let s = string(value)?; let first = s.as_bytes().first().copied().ok_or(INVALID)?;
    need(s.len() <= 120 && (first.is_ascii_lowercase() || first.is_ascii_digit()) &&
      s.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_-".contains(&c)))
}
fn uuid(value: &Value) -> R {
    let s = string(value)?;
    need(s.len() == 36 && s.bytes().enumerate().all(|(i,c)|
      if [8,13,18,23].contains(&i) { c == b'-' }
      else { c.is_ascii_digit() || (b'a'..=b'f').contains(&c) }))
}
fn hex(value: &Value, n: usize) -> R {
    let s = string(value)?;
    need(s.len() == n && s.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)))
}
fn sha(value: &Value) -> R { hex(value, 40) }
fn digest(value: &Value) -> R { hex(value, 64) }
fn timestamp(value: &Value) -> R {
    let s = string(value)?; need(s.is_ascii() && s.len() <= 64)?;
    let core = s.strip_suffix('Z').or_else(|| s.strip_suffix("+00:00")).ok_or(INVALID)?;
    let main = if let Some((main, fraction)) = core.split_once('.') {
        need(!fraction.is_empty() && fraction.len() <= 9 && fraction.bytes().all(|c| c.is_ascii_digit()))?; main
    } else { core };
    need(main.len() == 19)?;
    need(main.bytes().enumerate().all(|(i,c)| match i {
        4|7 => c == b'-', 10 => c == b'T', 13|16 => c == b':', _ => c.is_ascii_digit()
    }))?;
    need(&main[..4] != "0000" && main[17..19].parse::<u8>().map_err(|_| INVALID)? < 60)?;
    let date = chrono::DateTime::parse_from_rfc3339(s).map_err(|_| INVALID)?;
    need(date.offset().local_minus_utc() == 0)
}
fn reference(value: &Value) -> R {
    object(value, "source kind id")?; one(&value["source"], "github codex resource_provider hydra")?;
    let kind = string(&value["kind"])?;
    need(!kind.is_empty() && kind.len() <= 64 && kind.as_bytes()[0].is_ascii_lowercase() &&
      kind.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_'))?;
    short(&value["id"])
}
fn kind_ref(value: &Value, kind: &str) -> R {
    reference(value)?; need(value["kind"] == kind)?;
    if kind.starts_with("native_") { need(value["source"] == "codex")?; } Ok(())
}
fn revision(value: &Value) -> R {
    object(value, "kind value")?; one(&value["kind"], "opaque monotonic")?; short(&value["value"])?;
    if value["kind"] == "monotonic" {
        let s = string(&value["value"])?;
        need(s == "0" || (!s.starts_with('0') && s.bytes().all(|c| c.is_ascii_digit())))?;
    } Ok(())
}
fn coverage(value: &Value) -> R {
    object(value, "state scope returned_count total_count next_cursor reason")?;
    one(&value["state"], "complete partial unavailable")?; text(&value["scope"], 512, false, false)?;
    number(&value["returned_count"])?; optional(&value["total_count"], number)?;
    optional(&value["next_cursor"], |v| text(v, 2048, false, false))?; optional(&value["reason"], code)?;
    if !value["total_count"].is_null() {
        need(value["total_count"].as_u64() >= value["returned_count"].as_u64())?;
    }
    if value["state"] == "complete" {
        need(value["next_cursor"].is_null() && (value["total_count"].is_null() || value["total_count"] == value["returned_count"]))?;
    } else { need(!value["reason"].is_null())?; }
    if value["state"] == "unavailable" {
        need(value["returned_count"] == 0 && value["total_count"].is_null() && value["next_cursor"].is_null())?;
    } Ok(())
}
fn issue_ref(value: &Value) -> R {
    object(value, "repository_id issue_number")?; positive(&value["repository_id"])?; positive(&value["issue_number"])
}
fn goal_ref(value: &Value) -> R {
    object(value, "repository_id issue_number source_digest")?; positive(&value["repository_id"])?;
    positive(&value["issue_number"])?; digest(&value["source_digest"])
}
fn parent_ref(value: &Value) -> R {
    need(value.is_object())?; if value.get("source_digest").is_some() { goal_ref(value) } else { issue_ref(value) }
}
fn requirement_ref(value: &Value) -> R {
    object(value, "repository_id path revision selector")?; positive(&value["repository_id"])?;
    text(&value["path"], 512, false, false)?; let p = string(&value["path"])?;
    need(!p.starts_with(['/', '~']) && !p.contains('\\') &&
      p.split('/').all(|part| !["", ".", "..", ".git"].contains(&part)))?;
    sha(&value["revision"])?; text(&value["selector"], 160, false, false)
}
fn branch(value: &Value) -> R {
    let n = string(value)?.strip_prefix("hydra/issue-").ok_or(INVALID)?;
    need(!n.is_empty() && !n.starts_with('0') && n.bytes().all(|c| c.is_ascii_digit()))
}
fn runtime(value: &Value) -> R {
    let identity: RuntimeIdentity = serde_json::from_value(value.clone()).map_err(|_| INVALID)?;
    need(identity.valid())
}
fn execution(value: &Value) -> R {
    object(value, "state active_count")?; one(&value["state"], "unobserved running ended")?;
    optional(&value["active_count"], number)
}
fn reported(value: &Value) -> R {
    let s = string(value)?;
    need(!s.is_empty() && s.len() <= 120 && s.as_bytes()[0].is_ascii_alphabetic() &&
      s.bytes().all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c)))
}
fn source_fields(kind: &str) -> Result<&'static str, &'static str> {
    Ok(match kind {
        "repository" => "numeric_id full_name url contract_ref",
        "issue" => "number title state url work_kind parent_refs requirement_refs description_excerpt description_truncated",
        "progress" => "issue_ref attempt_id phase native_step head contract_revision branch expected_head expected_base published_head wait_reason next_action pending_action pr_ref completion_refs cleanup_state",
        "pull_request" => "number url state head base merge_commit required_check_refs review_refs",
        "check" => "producer name head status conclusion url", "review" => "producer head state unresolved_count url",
        "native_task_metadata" => "task_ref reported_status", "native_history_page" => "task_ref turns page",
        "native_task" => "task_ref assignment_ref execution question_ref schedule_refs open_ref",
        "native_schedule" => "schedule_ref task_ref status next_wake_at open_ref",
        "resource" => "resource_ref owner_ref activity preservation retirement open_ref",
        "admission" => "revision global_mode project_overrides gate_reason", "ownership" => "state scope_digest step_nonce",
        _ => return Err(INVALID),
    })
}
fn refs(value: &Value) -> R { list(value, reference, 4096) }
fn repository_name(value: &str, lower: bool) -> R {
    let (owner, name) = value.split_once('/').ok_or(INVALID)?;
    need(!owner.is_empty() && owner.len() <= 39 && owner.as_bytes()[0].is_ascii_alphanumeric() &&
      owner.bytes().all(|c| (c.is_ascii_alphanumeric() || c == b'-') && (!lower || !c.is_ascii_uppercase())) &&
      !name.is_empty() && name.len() <= 100 &&
      name.bytes().all(|c| (c.is_ascii_alphanumeric() || b"_.-".contains(&c)) && (!lower || !c.is_ascii_uppercase())))
}
fn source_value(kind: &str, v: &Value) -> R {
    object(v, source_fields(kind)?)?;
    match kind {
        "repository" => {
            positive(&v["numeric_id"])?; repository_name(string(&v["full_name"])?, false)?;
            text(&v["url"], 2048, false, false)?;
            optional(&v["contract_ref"], |c| { object(c,"path revision")?; text(&c["path"],512,false,false)?; optional(&c["revision"],sha) })?;
        },
        "issue" => {
            positive(&v["number"])?; text(&v["title"],512,true,true)?; one(&v["state"],"open closed")?;
            text(&v["url"],2048,false,false)?; optional(&v["work_kind"],|x| one(x,"goal work"))?;
            optional(&v["parent_refs"],|x| list(x,parent_ref,100))?;
            optional(&v["requirement_refs"],|x| list(x,requirement_ref,100))?;
            optional(&v["description_excerpt"],|x| text(x,4096,true,true))?;
            optional(&v["description_truncated"],boolean)?;
            need(v["description_excerpt"].is_null() == v["description_truncated"].is_null())?;
        },
        "progress" => {
            kind_ref(&v["issue_ref"],"issue")?;
            for k in ["attempt_id","native_step"] { optional(&v[k],uuid)?; }
            for k in ["head","contract_revision","expected_head","expected_base","published_head"] { optional(&v[k],sha)?; }
            optional(&v["branch"],branch)?;
            for k in ["phase","wait_reason","next_action","pending_action","cleanup_state"] { optional(&v[k],code)?; }
            optional(&v["pr_ref"],reference)?; optional(&v["completion_refs"],refs)?;
        },
        "pull_request" => {
            positive(&v["number"])?; text(&v["url"],2048,false,false)?; one(&v["state"],"open closed")?;
            for k in ["head","base","merge_commit"] { optional(&v[k],sha)?; }
            optional(&v["required_check_refs"],refs)?; optional(&v["review_refs"],refs)?;
        },
        "check"|"review" => {
            optional(&v["producer"],reference)?; optional(&v["head"],sha)?; optional(&v["url"],|x| text(x,2048,false,false))?;
            if kind=="check" { text(&v["name"],512,false,false)?; code(&v["status"])?; optional(&v["conclusion"],code)?; }
            else { code(&v["state"])?; optional(&v["unresolved_count"],number)?; }
        },
        "native_task_metadata"|"native_history_page" => {
            kind_ref(&v["task_ref"],"native_task")?;
            if kind=="native_task_metadata" { reported(&v["reported_status"])?; }
            else {
                let page=&v["page"]; object(page,"order limit has_more")?;
                need(page["order"]=="newest_first")?; positive(&page["limit"])?; boolean(&page["has_more"])?;
                let mut turns=HashSet::new(); let mut messages=HashSet::new();
                let array=v["turns"].as_array().ok_or(INVALID)?; need(array.len()<=4096 && array.len() as u64 <= page["limit"].as_u64().unwrap())?;
                for t in array {
                    object(t,"turn_ref reported_status started_at completed_at messages")?;
                    kind_ref(&t["turn_ref"],"native_turn")?; unique(&mut turns,&t["turn_ref"])?; reported(&t["reported_status"])?;
                    optional(&t["started_at"],timestamp)?; optional(&t["completed_at"],timestamp)?;
                    let array=t["messages"].as_array().ok_or(INVALID)?; need(array.len()<=4096)?;
                    for m in array {
                        object(m,"message_ref message_type")?; kind_ref(&m["message_ref"],"native_message")?;
                        one(&m["message_type"],"userMessage agentMessage")?; unique(&mut messages,&m["message_ref"])?;
                    }
                }
            }
        },
        "native_task" => {
            kind_ref(&v["task_ref"],"native_task")?; optional(&v["assignment_ref"],reference)?;
            optional(&v["execution"],execution)?; optional(&v["question_ref"],reference)?;
            optional(&v["schedule_refs"],refs)?; optional(&v["open_ref"],|x| text(x,2048,false,false))?;
        },
        "native_schedule" => {
            kind_ref(&v["schedule_ref"],"native_schedule")?; optional(&v["task_ref"],reference)?; code(&v["status"])?;
            optional(&v["next_wake_at"],timestamp)?; optional(&v["open_ref"],|x| text(x,2048,false,false))?;
        },
        "resource" => {
            reference(&v["resource_ref"])?; optional(&v["owner_ref"],reference)?;
            for k in ["activity","preservation","retirement"] { optional(&v[k],code)?; }
            optional(&v["open_ref"],|x| text(x,2048,false,false))?;
        },
        "admission" => {
            number(&v["revision"])?; one(&v["global_mode"],"running paused stopped")?;
            let overrides=v["project_overrides"].as_object().ok_or(INVALID)?; need(overrides.len()<=1024)?;
            for (repository,mode) in overrides { repository_name(repository,true)?; one(mode,"running paused stopped")?; }
            optional(&v["gate_reason"],code)?;
        },
        "ownership" => {
            one(&v["state"],"free absent owned busy native unknown")?; optional(&v["scope_digest"],digest)?;
            optional(&v["step_nonce"],uuid)?;
        }, _=>return Err(INVALID),
    } Ok(())
}
fn unique(seen: &mut HashSet<String>, value: &Value) -> R {
    need(seen.insert(serde_json::to_string(value).map_err(|_| INVALID)?))
}
fn observation(v: &Value) -> R {
    object(v,"key resource revision observed_at last_attempt_at availability coverage reason value")?;
    text(&v["key"],512,false,false)?; reference(&v["resource"])?;
    let kind=string(&v["resource"]["kind"])?; source_fields(kind)?;
    let owner=match kind {
        "repository"|"issue"|"progress"|"pull_request"|"check"|"review"=>"github",
        "native_task_metadata"|"native_history_page"|"native_task"|"native_schedule"=>"codex",
        "resource"=>"resource_provider", "admission"|"ownership"=>"hydra", _=>return Err(INVALID),
    };
    need(v["resource"]["source"]==owner)?;
    optional(&v["revision"],revision)?; optional(&v["observed_at"],timestamp)?; timestamp(&v["last_attempt_at"])?;
    one(&v["availability"],"current stale unavailable unsupported")?; coverage(&v["coverage"])?; optional(&v["reason"],code)?;
    if v["availability"]=="current" {need(v["coverage"]["state"]!="unavailable")?;}
    if v["availability"]=="current" || v["availability"]=="stale" {
        need(!v["observed_at"].is_null() && !v["value"].is_null())?; source_value(kind,&v["value"])?;
        if kind=="admission" {
            let value=v["value"]["revision"].as_u64().ok_or(INVALID)?.to_string();
            need(v["revision"]==serde_json::json!({"kind":"monotonic","value":value}))?;
        } else if kind=="repository" {
            need(v["resource"]["id"]==v["value"]["numeric_id"].as_u64().ok_or(INVALID)?.to_string())?;
        } else if kind=="issue" {
            let (repository,issue)=string(&v["resource"]["id"])?.split_once(':').ok_or(INVALID)?;
            let repository_number=repository.parse::<u64>().map_err(|_|INVALID)?;
            positive(&Value::from(repository_number))?;
            need(repository==repository_number.to_string() &&
                issue==v["value"]["number"].as_u64().ok_or(INVALID)?.to_string())?;
        }
    } else {
        need(v["value"].is_null() && v["observed_at"].is_null() && !v["reason"].is_null() && v["coverage"]["state"]=="unavailable")?;
    }
    if ["native_task_metadata","native_history_page"].contains(&kind) {
        need(v["revision"].is_null())?;
        if !v["value"].is_null() {
            let c=&v["coverage"];
            if kind=="native_task_metadata" { need(c["state"]=="complete" && c["returned_count"]==1 && c["total_count"]==1)?; }
            else {
                let page=&v["value"]["page"];
                need(c["state"]=="partial" && c["total_count"].is_null() &&
                  c["returned_count"].as_u64()==Some(v["value"]["turns"].as_array().unwrap().len() as u64) &&
                  c["reason"]==if page["has_more"]==true { "more_pages" } else { "history_scope_unverified" } &&
                  (!c["next_cursor"].is_null()) == (page["has_more"]==true))?;
            }
        }
    } Ok(())
}
fn evidence(v: &Value) -> R { object(v,"observation_key revision")?; text(&v["observation_key"],512,false,false)?; optional(&v["revision"],revision) }
fn evidence_in<'a>(v: &Value, index: &Index<'a>) -> Result<&'a Value,&'static str> {
    evidence(v)?; let source=*index.get(string(&v["observation_key"])?).ok_or(INVALID)?;
    need(source["revision"]==v["revision"])?; Ok(source)
}
fn fact(v: &Value, check: impl Fn(&Value)->R, index: &Index<'_>) -> R {
    object(v,"value evidence reason")?; list(&v["evidence"],evidence,4096)?; optional(&v["reason"],code)?;
    let mut seen=HashSet::new();
    for e in v["evidence"].as_array().unwrap() {
        let source=evidence_in(e,index)?; need(seen.insert(string(&source["key"])?))?;
        if !v["value"].is_null() { need(source["availability"]=="current" && source["coverage"]["state"]=="complete")?; }
    }
    if v["value"].is_null() { need(!v["reason"].is_null()) }
    else { need(!seen.is_empty() && v["reason"].is_null())?; check(&v["value"]) }
}
fn canonical_repository_name(value:&str)->Option<String> {
    if !value.is_ascii(){return None;}
    let name=value.to_ascii_lowercase();repository_name(&name,true).is_ok().then_some(name)
}
fn repository_names(repository:&Value,index:&Index<'_>)->Result<HashSet<String>,&'static str> {
    kind_ref(repository,"repository")?;need(repository["source"]=="github")?;
    let identifier=string(&repository["id"])?;
    if let Some(name)=identifier.strip_prefix("requested:") {
        return Ok(HashSet::from([canonical_repository_name(name).ok_or(INVALID)?]));
    }
    let number=identifier.parse::<u64>().map_err(|_|INVALID)?;positive(&Value::from(number))?;
    need(identifier==number.to_string())?;let mut names=HashSet::new();let mut fallback=HashSet::new();
    for observed in index.values().filter(|o|o["resource"]==*repository) {
        let mut requested=HashSet::new();
        for (field,prefix) in [(string(&observed["key"])?,"github:repository-request:"),
            (string(&observed["coverage"]["scope"])?,"repository-address:")] {
            if let Some(value)=field.strip_prefix(prefix) {
                let Some(name)=canonical_repository_name(value) else{return Ok(HashSet::new());};requested.insert(name);
            }
        }
        if requested.len()>1{return Ok(HashSet::new());}
        if !requested.is_empty(){names.extend(requested);}
        else if !observed["value"].is_null() {
            if let Some(name)=canonical_repository_name(string(&observed["value"]["full_name"])?) {fallback.insert(name);}
        }
    } Ok(if names.is_empty(){fallback}else{names})
}
fn issue_repository(issue:&Value)->Result<Value,&'static str> {
    kind_ref(issue,"issue")?;need(issue["source"]=="github")?;
    let (repository,number)=string(&issue["id"])?.split_once(':').ok_or(INVALID)?;
    for value in [repository,number] {
        let numeric=value.parse::<u64>().map_err(|_|INVALID)?;positive(&Value::from(numeric))?;need(value==numeric.to_string())?;
    }
    Ok(serde_json::json!({"source":"github","kind":"repository","id":repository}))
}
pub(crate) fn observed_repository_bindings(value:&Value)->BTreeMap<String,u64> {
    let Some(observations)=value["observations"].as_array() else{return BTreeMap::new();};
    let index:Index<'_>=observations.iter().filter(|o|o["availability"]=="current" && o["coverage"]["state"]=="complete")
        .filter_map(|o|o["key"].as_str().map(|key|(key,o))).collect();
    let Some(projects)=value["projects"].as_array() else{return BTreeMap::new();};
    let mut candidates:BTreeMap<String,Option<u64>>=BTreeMap::new();
    for project in projects {
        let reference=&project["repository_ref"];
        let Some(number)=reference["id"].as_str().and_then(|id|id.parse::<u64>().ok()) else{continue;};
        if let Ok(names)=repository_names(reference,&index) {
            for name in names {
                candidates.entry(name).and_modify(|previous|{if *previous!=Some(number){*previous=None;}}).or_insert(Some(number));
            }
        }
    }
    candidates.into_iter().filter_map(|(name,number)|number.map(|number|(name,number))).take(1024).collect()
}
fn admission_fact(v: &Value, index: &Index<'_>, names:&HashSet<String>, binding:&Value) -> R {
    fact(v,|x|one(x,"allowed paused stopped"),index)?;
    if !v["value"].is_null() {
        let mut admission=false;
        for item in v["evidence"].as_array().ok_or(INVALID)? {
            let source=evidence_in(item,index)?;
            if source["resource"]["source"]=="hydra" && source["resource"]["kind"]=="admission" {
                admission=true;need(!binding.is_null() && source["resource"]["id"]==*binding)?;
                let snapshot=&source["value"];let mode=string(&snapshot["global_mode"])?;
                if mode=="running" {
                    need(!names.is_empty())?;
                    for name in names {
                        let mode=match snapshot["project_overrides"].get(name){Some(mode)=>string(mode)?,None=>"running"};
                        need(v["value"]==if mode=="running"{"allowed"}else{mode})?;
                    }
                } else {need(v["value"]==mode)?;}
            }
        }
        need(admission)?;
    } Ok(())
}
fn readiness(v: &Value) -> R {
    object(v,"disposition source_ref source_revision interpretation_ref binding_ref extracted missing authority trust_reason")?;
    one(&v["disposition"],"actionable needs_info propose quarantined")?; reference(&v["source_ref"])?;
    optional(&v["source_revision"],revision)?; optional(&v["interpretation_ref"],reference)?; optional(&v["binding_ref"],reference)?;
    let e=&v["extracted"]; object(e,"purpose_excerpt requirement_refs scope_excerpt")?;
    optional(&e["purpose_excerpt"],|x| text(x,1024,true,true))?; optional(&e["scope_excerpt"],|x| text(x,1024,true,true))?;
    list(&e["requirement_refs"],requirement_ref,100)?;
    list(&v["missing"],|m| {object(m,"code detail owner_ref")?; code(&m["code"])?;
      text(&m["detail"],1024,true,true)?; optional(&m["owner_ref"],reference)},100)?;
    one(&v["authority"],"confirmed missing unknown")?; optional(&v["trust_reason"],code)
}
fn unmapped_fact(v:&Value,check:impl Fn(&Value)->R,index:&Index<'_>)->R {
    fact(v,check,index)?;need(v["value"].is_null())
}
fn readiness_fact(v:&Value,index:&Index<'_>,issue:&Value)->R {
    fact(v,readiness,index)?;let value=&v["value"];if value.is_null(){return Ok(());}
    need(value["source_ref"]==*issue && value["disposition"]=="propose" && value["authority"]=="unknown" &&
         value["interpretation_ref"].is_null() && value["binding_ref"].is_null())?;
    need(value["extracted"]==serde_json::json!({"purpose_excerpt":null,"requirement_refs":[],"scope_excerpt":null}))?;
    let mut matched=false;
    for e in v["evidence"].as_array().ok_or(INVALID)? {
        let source=evidence_in(e,index)?;
        matched|=issue["source"]=="github" && issue["kind"]=="issue" && source["resource"]==*issue &&
                  source["revision"]==value["source_revision"];
    } need(matched)
}
fn project_work_refs(v:&Value,repository:&Value)->R {
    let rows=v.as_array().ok_or(INVALID)?;need(rows.len()<=128)?;let mut seen=HashSet::new();
    for item in rows {need(issue_repository(item)?==*repository)?;unique(&mut seen,item)?;}Ok(())
}
fn parent_relation(v:&Value,index:&Index<'_>)->R {
    object(v,"from to kind evidence")?;issue_repository(&v["from"])?;issue_repository(&v["to"])?;
    need(v["kind"]=="parent")?;
    fact(&serde_json::json!({"value":"relation","evidence":v["evidence"],"reason":null}),|_|Ok(()),index)?;
    let mut matched=false;
    for e in v["evidence"].as_array().ok_or(INVALID)? {
        let source=evidence_in(e,index)?;
        if source["resource"]!=v["from"] || source["resource"]["kind"]!="issue" {continue;}
        let Some(parents)=source["value"]["parent_refs"].as_array() else {continue;};
        for parent in parents {
            let id=format!("{}:{}",parent["repository_id"].as_u64().ok_or(INVALID)?,parent["issue_number"].as_u64().ok_or(INVALID)?);
            matched|=v["to"]==serde_json::json!({"source":"github","kind":"issue","id":id});
        }
    }need(matched)
}
fn decision(v: &Value,index:&Index<'_>)->R {
    object(v,"question answer acceptance application")?;
    // No implemented source mapping qualifies these axes. Metadata cannot enable it.
    for k in ["question","answer","acceptance","application"] {
        fact(&v[k],|_|Err(INVALID),index)?;
    } Ok(())
}
fn waiting(v:&Value)->R {
    if v=="none" { return Ok(()); } object(v,"kind owner_ref wake_ref reason")?;
    one(&v["kind"],"human external resource")?; optional(&v["owner_ref"],reference)?; optional(&v["wake_ref"],reference)?; code(&v["reason"])
}
fn next_action(v:&Value,index:&Index<'_>)->R {
    object(v,"code target_ref rationale_excerpt evidence")?; code(&v["code"])?; optional(&v["target_ref"],reference)?;
    text(&v["rationale_excerpt"],1024,true,true)?;
    fact(&serde_json::json!({"value":"candidate","evidence":v["evidence"],"reason":null}), |_|Ok(()),index)
}
fn assignment(v:&Value)->R {
    object(v,"attempt_id step_id head contract_revision spec_revision")?; uuid(&v["attempt_id"])?; uuid(&v["step_id"])?;
    sha(&v["head"])?; sha(&v["contract_revision"])?; optional(&v["spec_revision"],sha)
}
fn candidate(v:&Value)->R {object(v,"attempt_id head contract_revision")?; uuid(&v["attempt_id"])?; sha(&v["head"])?; sha(&v["contract_revision"])}
fn target(v:&Value,action:&str)->R {
    match action {
        "admission_set" => if v["kind"]=="host" {object(v,"kind")} else {
            object(v,"kind repository_id")?; need(v["kind"]=="repository")?; positive(&v["repository_id"])
        },
        "workflow_step" => {object(v,"repository_id issue_number")?; positive(&v["repository_id"])?; positive(&v["issue_number"])},
        "work_create" => {object(v,"repository_id")?; positive(&v["repository_id"])},
        "cleanup" => {object(v,"kind repository_id issue_number source_attempt resource")?; need(v["kind"]=="owned_resource")?;
          positive(&v["repository_id"])?; positive(&v["issue_number"])?; uuid(&v["source_attempt"])?; reference(&v["resource"])},
        _ => reference(v),
    }
}
fn receipt(v:&Value,index:&Index<'_>)->R {
    let kind=string(&v["kind"])?;
    object(v,match kind {
        "admission"=>"kind readback",
        "checkpoint"=>"kind assignment outcome checkpoint_head progress_ref step_retired ticket_released",
        "decision"=>"kind source_attempt round intent_ref context_ref resolved_ref resume_attempt",
        "continuation"=>"kind progress_ref attempt_id head contract_revision boundary",
        "verification"=>"kind candidate verdict review progress_ref evidence_refs",
        "verification_review"=>"kind candidate assignment review progress_ref evidence_refs step_retired ticket_released",
        "publication"=>"kind candidate branch observed_remote_head pr_ref review_request_refs progress_ref stage",
        "delivery"=>"kind candidate pr_ref integration_base merge_commit post_merge issue_closed progress_ref",
        "cleanup"=>"kind resource operation result evidence_refs", _=>return Err(INVALID),
    })?;
    if kind=="admission" {
        let o=evidence_in(&v["readback"],index)?;
        need(o["availability"]=="current" && o["coverage"]["state"]=="complete" && o["resource"]["kind"]=="admission")?;
    }
    if kind=="checkpoint" {assignment(&v["assignment"])?; one(&v["outcome"],"stopped candidate_ready failed needs_decision")?; sha(&v["checkpoint_head"])?;}
    if ["checkpoint","verification_review"].contains(&kind) {need(v["step_retired"]==true && v["ticket_released"]==true)?;}
    if kind=="decision" {
        uuid(&v["source_attempt"])?; positive(&v["round"])?; uuid(&v["resume_attempt"])?;
        for k in ["intent_ref","context_ref","resolved_ref"] {reference(&v[k])?;}
    }
    if kind=="continuation" {
        uuid(&v["attempt_id"])?; sha(&v["head"])?; sha(&v["contract_revision"])?;
        one(&v["boundary"],"progress_recorded assignment_returned existing_result_reconciled")?;
    }
    if ["verification","verification_review","publication","delivery"].contains(&kind) {candidate(&v["candidate"])?;}
    if kind=="verification" {
        one(&v["verdict"],"passed failed")?; optional(&v["review"],|x| one(x,"pending accepted failed not_required"))?;
    }
    if kind=="verification_review" {
        assignment(&v["assignment"])?;
        for k in ["attempt_id","head","contract_revision"] {need(v["assignment"][k]==v["candidate"][k])?;}
        one(&v["review"],"accepted failed pending")?;
    }
    if kind=="publication" {
        branch(&v["branch"])?; sha(&v["observed_remote_head"])?; need(v["observed_remote_head"]==v["candidate"]["head"])?;
        optional(&v["pr_ref"],reference)?; refs(&v["review_request_refs"])?; one(&v["stage"],"branch_published pr_ready publication_ready")?;
        need(v["stage"]=="branch_published" || !v["pr_ref"].is_null())?;
    }
    if kind=="delivery" {
        reference(&v["pr_ref"])?; sha(&v["integration_base"])?; sha(&v["merge_commit"])?;
        one(&v["post_merge"],"pending success failed unknown")?; optional(&v["issue_closed"],boolean)?;
    }
    if kind=="cleanup" {
        need(v["evidence_refs"].as_array().is_some_and(|refs|!refs.is_empty()))?;
        reference(&v["resource"])?; one(&v["operation"],"preserve archive retire remove_schedule")?;
        let result=match string(&v["operation"])? {"preserve"=>"preserved","archive"=>"archived","retire"=>"retired","remove_schedule"=>"schedule_removed",_=>return Err(INVALID)};
        need(v["result"]==result)?;
    }
    if v.get("evidence_refs").is_some() {refs(&v["evidence_refs"])?;} if v.get("progress_ref").is_some() {reference(&v["progress_ref"])?;} Ok(())
}
fn command_result(v:&Value,index:&Index<'_>)->R {
    object(v,"request_id action target outcome reason effect_refs observed_refs receipt required_next")?;
    uuid(&v["request_id"])?; one(&v["action"],"admission_set work_create workflow_step native_control cleanup open_record")?;
    target(&v["target"],string(&v["action"])?)?; one(&v["outcome"],"applied waiting rejected unknown")?;
    optional(&v["reason"],code)?; refs(&v["effect_refs"])?;
    list(&v["observed_refs"],|e| evidence_in(e,index).map(|_|()),4096)?;
    one(&v["required_next"],"none refresh reconcile open_source")?; optional(&v["receipt"],|r| receipt(r,index))?;
    let kind=v["receipt"].get("kind").and_then(Value::as_str);
    if v["action"]=="workflow_step" && matches!(kind,Some("publication"|"delivery")) {
        let pr=&v["receipt"]["pr_ref"];
        if !pr.is_null() {
            need(pr["source"]=="github" && pr["kind"]=="pull_request")?;
            let (repository,number)=string(&pr["id"])?.split_once(':').ok_or(INVALID)?;
            let repository_id=repository.parse::<u64>().map_err(|_|INVALID)?;
            let pr_number=number.parse::<u64>().map_err(|_|INVALID)?;
            need(repository_id>0 && repository_id<=MAX_INTEGER && pr_number>0 && pr_number<=MAX_INTEGER &&
                repository_id.to_string()==repository && pr_number.to_string()==number &&
                v["target"]["repository_id"].as_u64()==Some(repository_id))?;
        }
    }
    if kind.is_some() && v["action"]=="cleanup" {need(v["receipt"]["resource"]==v["target"]["resource"])?;}
    if v["outcome"]=="applied" && ["workflow_step","cleanup"].contains(&string(&v["action"])?) {
        need(!v["receipt"].is_null())?;
    }
    if v["outcome"]=="applied" && kind==Some("publication") {
        need(v["receipt"]["stage"]=="publication_ready")?;
    }
    if v["outcome"]=="applied" && kind==Some("delivery") {
        need(v["receipt"]["post_merge"]=="success" && v["receipt"]["issue_closed"]==true)?;
    }
    if v["action"]=="admission_set" || matches!(kind,Some("checkpoint"|"decision")) {
        need((!v["receipt"].is_null())==(v["outcome"]=="applied"))?;
    }
    if let Some(k)=kind {
        need((v["action"]=="admission_set" && k=="admission") ||
          (v["action"]=="workflow_step" && ["checkpoint","decision","continuation","verification","verification_review","publication","delivery"].contains(&k)) ||
          (v["action"]=="cleanup" && k=="cleanup"))?;
    }
    if v["action"]=="workflow_step" && v["receipt"].get("progress_ref").is_some() {
        let progress=&v["receipt"]["progress_ref"];
        let expected=format!("{}:{}",v["target"]["repository_id"],v["target"]["issue_number"]);
        need(progress["source"]=="github")?;
        if progress["kind"]=="progress" {need(progress["id"]==expected)?;}
        else {
            need(progress["kind"]=="issue_comment")?;
        }
        if progress["kind"]=="issue_comment" || kind==Some("checkpoint") {
            let proofs:Vec<_>=v["observed_refs"].as_array().ok_or(INVALID)?.iter()
                .filter_map(|e|index.get(e["observation_key"].as_str()?))
                .filter(|o|o["resource"]["source"]=="github" && o["resource"]["kind"]=="progress" &&
                    o["resource"]["id"]==progress["id"]).collect();
            need(proofs.len()==1)?;let proof=proofs[0];
            need(proof["availability"]=="current" && proof["coverage"]["state"]=="complete" &&
                proof["value"]["issue_ref"]==serde_json::json!({"source":"github","kind":"issue","id":expected}))?;
            if kind==Some("checkpoint") {
                let checkpoint=&v["receipt"];
                need(proof["value"]["head"]==checkpoint["checkpoint_head"] &&
                    proof["value"]["attempt_id"]==checkpoint["assignment"]["attempt_id"] &&
                    proof["value"]["contract_revision"]==checkpoint["assignment"]["contract_revision"] &&
                    proof["value"]["native_step"].is_null())?;
            }
        }
    }
    Ok(())
}
fn observations(value:&Value)->Result<Index<'_>,&'static str> {
    let rows=value.as_array().ok_or(INVALID)?; need(rows.len()<=4096)?; let mut index=HashMap::new();
    for v in rows {observation(v)?; need(index.insert(string(&v["key"])?,v).is_none())?;} Ok(index)
}
fn bound_command_result(v:&Value,index:&Index<'_>,binding:&Value)->R {
    command_result(v,index)?;let receipt=&v["receipt"];
    if v["outcome"]=="applied" && !matches!(v["action"].as_str(),Some("admission_set"|"workflow_step")) {
        return Err("unsupported_command_source");
    }
    // Each future operation must qualify its paired producer and consumers first.
    if !receipt.is_null() && !matches!(receipt["kind"].as_str(),Some("admission"|"checkpoint")) {
        return Err("unsupported_receipt_source");
    }
    if receipt["kind"]=="admission" {
        let source=evidence_in(&receipt["readback"],index)?;
        need(binding.is_string() && source["resource"]["source"]=="hydra" &&
             source["resource"]["kind"]=="admission" && source["resource"]["id"]==*binding)?;
    }Ok(())
}
fn validate_frame(v:&Value)->R {
    object(v,"schema_version runtime binding_epoch request_id assembled_at observations projects work relations page capabilities retry_hints request")?;
    need(v["schema_version"]==3)?; runtime(&v["runtime"])?; uuid(&v["binding_epoch"])?; uuid(&v["request_id"])?; timestamp(&v["assembled_at"])?;
    let index=observations(&v["observations"])?; let mut seen=HashSet::new();
    for h in v["retry_hints"].as_array().ok_or(INVALID)? {
        object(h,"observation_key scope after_seconds basis")?; text(&h["observation_key"],512,false,false)?; short(&h["scope"])?;
        number(&h["after_seconds"])?; one(&h["basis"],"provider fallback")?;
        need(seen.insert((string(&h["observation_key"])?,string(&h["scope"])?)))?;
        let o=index.get(string(&h["observation_key"])?).ok_or(INVALID)?;
        need(o["availability"]!="unsupported" && (o["availability"]=="unavailable" || o["availability"]=="stale" ||
          o["coverage"]["state"]!="complete" || o["reason"]=="rate_limited" || o["reason"]=="provider_wait"))?;
    }
    need(v["retry_hints"].as_array().unwrap().len()<=4096)?;
    let mut projects=HashSet::new();let mut membership=HashSet::new();
    let rows=v["projects"].as_array().ok_or(INVALID)?; need(rows.len()<=1024)?;
    for p in rows {
        object(p,"repository_ref goal_refs work_refs admission execution attention_refs coverage source_refs")?;
        kind_ref(&p["repository_ref"],"repository")?; unique(&mut projects,&p["repository_ref"])?;
        list(&p["goal_refs"],goal_ref,100)?; project_work_refs(&p["work_refs"],&p["repository_ref"])?;
        admission_fact(&p["admission"],&index,&repository_names(&p["repository_ref"],&index)?,&v["runtime"]["control_binding_digest"])?; unmapped_fact(&p["execution"],execution,&index)?;
        refs(&p["attention_refs"])?; coverage(&p["coverage"])?; refs(&p["source_refs"])?;
        need(p["coverage"]["returned_count"].as_u64()==Some(p["work_refs"].as_array().unwrap().len() as u64))?;
        for reference in p["work_refs"].as_array().unwrap() {membership.insert(serde_json::to_string(reference).map_err(|_|INVALID)?);}
    }
    let mut works=HashSet::new();
    let rows=v["work"].as_array().ok_or(INVALID)?; need(rows.len()<=512)?;
    for w in rows {
        object(w,"issue_ref goal_refs spec_refs requirement_refs readiness stage admission execution wait decision delivery result cleanup next_action task_refs resource_refs evidence_refs")?;
        kind_ref(&w["issue_ref"],"issue")?; unique(&mut works,&w["issue_ref"])?;
        need(membership.contains(&serde_json::to_string(&w["issue_ref"]).map_err(|_|INVALID)?))?;
        list(&w["goal_refs"],goal_ref,100)?; list(&w["spec_refs"],requirement_ref,100)?; list(&w["requirement_refs"],requirement_ref,100)?;
        readiness_fact(&w["readiness"],&index,&w["issue_ref"])?; unmapped_fact(&w["stage"],|x| one(x,"prepare design implement verify deliver observe complete"),&index)?;
        admission_fact(&w["admission"],&index,&repository_names(&issue_repository(&w["issue_ref"])?,&index)?,&v["runtime"]["control_binding_digest"])?; unmapped_fact(&w["execution"],execution,&index)?;
        unmapped_fact(&w["wait"],waiting,&index)?; decision(&w["decision"],&index)?;
        unmapped_fact(&w["delivery"],|x| one(x,"candidate published merged post_merge_verified deployment_observed"),&index)?;
        unmapped_fact(&w["result"],|x| one(x,"incomplete complete cancelled"),&index)?; unmapped_fact(&w["cleanup"],|x| one(x,"not_required pending complete"),&index)?;
        unmapped_fact(&w["next_action"],|x| next_action(x,&index),&index)?; refs(&w["task_refs"])?; refs(&w["resource_refs"])?;
        list(&w["evidence_refs"],|e| evidence_in(e,&index).map(|_|()),4096)?;
    }
    list(&v["relations"],|r| parent_relation(r,&index),4096)?;
    coverage(&v["page"])?;
    need(v["page"]["returned_count"].as_u64()==Some(v["projects"].as_array().unwrap().len() as u64))?;
    list(&v["capabilities"],|c| {
        object(c,"source operation state actor qualification_ref reason")?; one(&c["source"],"github codex resource_provider hydra")?;
        short(&c["operation"])?; one(&c["state"],"available unsupported unavailable")?; one(&c["actor"],"core native_actor provider")?;
        optional(&c["qualification_ref"],|x| text(x,2048,false,false))?; optional(&c["reason"],code)?;
        need(if c["state"]=="available" {!c["qualification_ref"].is_null() && c["reason"].is_null()} else {!c["reason"].is_null()})
    },4096)?;
    optional(&v["request"],|r| bound_command_result(r,&index,&v["runtime"]["control_binding_digest"]))
}

#[derive(Clone,Copy)]
struct JsonNode<'a> {depth:usize,native:&'a Cell<bool>}
impl<'de> DeserializeSeed<'de> for JsonNode<'_> {
    type Value=Value;
    fn deserialize<D:serde::Deserializer<'de>>(self,d:D)->Result<Value,D::Error> {
        if self.depth>64 {return Err(de::Error::custom("depth"));}
        d.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for JsonNode<'_> {
    type Value=Value;
    fn expecting(&self,f:&mut fmt::Formatter)->fmt::Result {f.write_str("bounded unique JSON")}
    fn visit_unit<E:de::Error>(self)->Result<Value,E> {Ok(Value::Null)}
    fn visit_bool<E:de::Error>(self,v:bool)->Result<Value,E> {Ok(Value::Bool(v))}
    fn visit_str<E:de::Error>(self,v:&str)->Result<Value,E> {Ok(Value::String(v.to_owned()))}
    fn visit_string<E:de::Error>(self,v:String)->Result<Value,E> {Ok(Value::String(v))}
    fn visit_u64<E:de::Error>(self,v:u64)->Result<Value,E> {
        if v>MAX_INTEGER {Err(E::custom("integer"))} else {Ok(Value::Number(Number::from(v)))}
    }
    fn visit_i64<E:de::Error>(self,v:i64)->Result<Value,E> {
        if v<0 {Err(E::custom("integer"))} else {self.visit_u64(v as u64)}
    }
    fn visit_f64<E:de::Error>(self,_:f64)->Result<Value,E> {Err(E::custom("integer"))}
    fn visit_seq<A:SeqAccess<'de>>(self,mut a:A)->Result<Value,A::Error> {
        let mut values=Vec::new();
        while let Some(value)=a.next_element_seed(JsonNode{depth:self.depth+1,..self})? {values.push(value);}
        Ok(Value::Array(values))
    }
    fn visit_map<A:MapAccess<'de>>(self,mut a:A)->Result<Value,A::Error> {
        let mut values=Map::new();
        while let Some(key)=a.next_key::<String>()? {
            if self.depth==0 && ["reply_profile","handoff"].contains(&key.as_str()) {
                self.native.set(true); return Err(de::Error::custom("native profile"));
            }
            if values.contains_key(&key) {return Err(de::Error::custom("duplicate"));}
            let value=a.next_value_seed(JsonNode{depth:self.depth+1,..self})?; values.insert(key,value);
        } Ok(Value::Object(values))
    }
}
fn read_json(bytes:&[u8])->Result<Value,&'static str> {
    need(bytes.len()<=MAX_OUTPUT)?;
    let native=Cell::new(false); let mut decoder=serde_json::Deserializer::from_slice(bytes);
    let result=JsonNode{depth:0,native:&native}.deserialize(&mut decoder);
    if native.get() {return Err("unsupported_reply_profile");}
    let value=result.map_err(|_| INVALID)?; decoder.end().map_err(|_| INVALID)?; Ok(value)
}
#[derive(Clone,Debug,Serialize)]
#[serde(transparent)]
pub struct Projection(Value);
impl Projection {
    pub fn parse(bytes:&[u8])->Result<Self,&'static str> {
        let value=read_json(bytes)?; validate_frame(&value)?; Ok(Self(value))
    }
}
#[derive(Clone,Debug,Serialize)]
#[serde(transparent)]
pub struct StandardReply(Value);
impl StandardReply {
    pub fn parse(bytes:&[u8])->Result<Self,&'static str> {
        let v=read_json(bytes)?; object(&v,"command_schema runtime binding_epoch request observations")?;
        need(v["command_schema"]==1)?; runtime(&v["runtime"])?; optional(&v["binding_epoch"],uuid)?;
        bound_command_result(&v["request"],&observations(&v["observations"])?,&v["runtime"]["control_binding_digest"])?; Ok(Self(v))
    }
}
#[derive(Clone,Debug,Serialize)]
#[serde(untagged)]
pub enum ReadPayload {V3(Projection),V2(Snapshot)}
impl ReadPayload {
    pub(crate) fn projection_value(&self)->Option<&Value> {
        match self {Self::V3(value)=>Some(&value.0),Self::V2(_)=>None}
    }
    pub fn parse(bytes:&[u8])->Result<Self,&'static str> {
        let value=read_json(bytes)?;
        match value["schema_version"].as_u64() {
            Some(3)=>Projection::parse(bytes).map(Self::V3),
            Some(2)=>Snapshot::parse(bytes).map(Self::V2).map_err(|_| INVALID),
            _=>Err(INVALID),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{io::Write,path::PathBuf,process::{Command,Stdio}};
    fn root()->PathBuf {PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")}
    fn expected<'a>(value:&'a Value,path:&Value)->&'a Value {
        let mut cursor=value;
        for key in path.as_array().unwrap() {
            cursor=if let Some(k)=key.as_str() {cursor.get(k).unwrap()} else {cursor.get(key.as_u64().unwrap() as usize).unwrap()};
        } cursor
    }
    #[test]
    fn actual_python_encoder_crosses_rust_and_actual_typescript_consumer() {
        let emitted=Command::new("python3").args(["-I"]).arg(root().join("tests/fixtures/control-v3/emit_wire.py")).output().unwrap();
        assert!(emitted.status.success(),"Actual Python producer fixture failed");
        assert!(emitted.stdout.len()<=4_194_304);
        let vectors:Value=serde_json::from_slice(&emitted.stdout).unwrap(); let vectors=vectors.as_array().unwrap();
        assert!(vectors.len()>=16 && vectors.iter().any(|v|v["accepted"]==true) && vectors.iter().any(|v|v["accepted"]==false));
        let mut forwarded=Vec::new();
        for v in vectors {
            let wire=v["wire"].as_str().unwrap().as_bytes();
            let decoded=if v["profile"]=="standard" {
                StandardReply::parse(wire).and_then(|v|serde_json::to_value(v).map_err(|_|INVALID))
            } else {
                ReadPayload::parse(wire).and_then(|v|serde_json::to_value(v).map_err(|_|INVALID))
            };
            if v["accepted"]==true {
                let value=decoded.unwrap_or_else(|_|panic!("Rust rejected accepted case {}",v["name"]));
                for e in v["expected"].as_array().unwrap() {assert_eq!(expected(&value,&e["path"]),&e["value"],"{}",v["name"]);}
                forwarded.push(serde_json::json!({"name":v["name"],"profile":v["profile"],"accepted":true,"wire":serde_json::to_string(&value).unwrap(),"expected":v["expected"]}));
            } else {
                assert!(decoded.is_err(),"Rust accepted invalid case {}",v["name"]);
                // Invalid/native data is never passed onward to renderer/cache.
                forwarded.push(serde_json::json!({"name":v["name"],"accepted":false,"rejected":true}));
            }
        }
        let mut child=Command::new("node").args(["--experimental-strip-types"]).arg(root().join("apps/mac/tests/control-v3-consume.mjs"))
          .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().unwrap();
        child.stdin.take().unwrap().write_all(&serde_json::to_vec(&forwarded).unwrap()).unwrap();
        let output=child.wait_with_output().unwrap(); assert!(output.status.success(),"Actual TypeScript consumer rejected the Rust read boundary");
        let summary:Value=serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(summary["passed"].as_u64(),Some(vectors.iter().filter(|v|v["accepted"]==true).count() as u64));
        assert_eq!(summary["rejected"].as_u64(),Some(vectors.iter().filter(|v|v["accepted"]==false).count() as u64));
    }
    #[test]
    fn applied_receipt_bearing_results_cannot_omit_readback_proof() {
        let emitted=Command::new("python3").arg("-I").arg(root().join("tests/fixtures/control-v3/emit_wire.py")).output().unwrap();
        assert!(emitted.status.success());let vectors:Value=serde_json::from_slice(&emitted.stdout).unwrap();
        let original:Value=serde_json::from_str(vectors.as_array().unwrap().iter()
            .find(|v|v["profile"]=="standard" && v["accepted"]==true).unwrap()["wire"].as_str().unwrap()).unwrap();
        for (action,target) in [("workflow_step",serde_json::json!({"repository_id":101,"issue_number":7})),
            ("cleanup",serde_json::json!({"kind":"owned_resource","repository_id":101,"issue_number":7,
             "source_attempt":"00000000-0000-4000-8000-000000000001",
             "resource":{"source":"resource_provider","kind":"workspace","id":"fixture"}}))] {
            let mut value=original.clone();let result=&mut value["request"];
            result["action"]=action.into();result["target"]=target;result["receipt"]=Value::Null;
            result["effect_refs"]=serde_json::json!([]);result["observed_refs"]=serde_json::json!([]);
            result["outcome"]="waiting".into();
            assert!(StandardReply::parse(&serde_json::to_vec(&value).unwrap()).is_ok());
            value["request"]["outcome"]="applied".into();
            assert!(StandardReply::parse(&serde_json::to_vec(&value).unwrap()).is_err(),"Receiptless applied {action}");
        }
    }
    #[test]
    fn unique_bounded_integer_json_is_required_before_assignment() {
        for raw in [b"{\"a\":1,\"a\":2}".as_slice(),b"{\"a\":1.0}",b"{\"a\":1e2}",b"{\"a\":-1}",b"{\"a\":9007199254740992}",b"{\"a\":\"\\ud800\"}"] {assert!(read_json(raw).is_err());}
        assert!(read_json(&[0xc0,0x80]).is_err()); assert!(read_json(&vec![b' ';MAX_OUTPUT+1]).is_err());
        assert!(read_json(( "[".repeat(66)+"0"+&"]".repeat(66)).as_bytes()).is_err());
    }
    #[test]
    fn native_payload_is_rejected_before_its_value_is_traversed() {
        assert_eq!(StandardReply::parse(b"{\"reply_profile\": [invalid native bytes").unwrap_err(),"unsupported_reply_profile");
    }

    #[test]
    fn cp8_receipt_state_matrix_agrees_with_shared_oracles() {
        let data:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/receipt-states.json")).unwrap()).unwrap();
        let inputs:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/inputs.json")).unwrap()).unwrap();
        let cases=data["cases"].as_array().unwrap();assert_eq!(cases.len(),54);
        let mut failures=Vec::new();
        for case in cases {
            let raw=case["wire"].as_str().unwrap();let expected=case["accepted"].as_bool().unwrap();
            if StandardReply::parse(raw.as_bytes()).is_ok()!=expected {failures.push(format!("{}:standard",case["name"]));}
            let reply:Value=serde_json::from_str(raw).unwrap();let mut frame=inputs["frame"].clone();frame["request"]=reply["request"].clone();
            if Projection::parse(&serde_json::to_vec(&frame).unwrap()).is_ok()!=expected {failures.push(format!("{}:projection",case["name"]));}
        }
        assert!(failures.is_empty(),"CP8 receipt state mismatches: {:?}",failures);
    }
    #[test]
    fn p12_review_cleanup_receipts_require_readback_in_both_profiles() {
        let data:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/cleanup-receipts.json")).unwrap()).unwrap();
        let inputs:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/inputs.json")).unwrap()).unwrap();
        let cases=data["cases"].as_array().unwrap();assert_eq!(cases.len(),32);
        let mut failures=Vec::new();
        for case in cases {
            let raw=case["wire"].as_str().unwrap();let expected=case["accepted"].as_bool().unwrap();
            if StandardReply::parse(raw.as_bytes()).is_ok()!=expected {failures.push(format!("{}:standard",case["name"]));}
            let reply:Value=serde_json::from_str(raw).unwrap();let mut frame=inputs["frame"].clone();frame["request"]=reply["request"].clone();
            if Projection::parse(&serde_json::to_vec(&frame).unwrap()).is_ok()!=expected {failures.push(format!("{}:projection",case["name"]));}
        }
        assert!(failures.is_empty(),"cleanup proof mismatches: {:?}",failures);
    }

    #[test]
    fn p12_source_value_evidence_causality_matches_shared_oracles() {
        let input:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/inputs.json")).unwrap()).unwrap();
        let matrix:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/source-causality.json")).unwrap()).unwrap();
        let commands:Value=serde_json::from_slice(&std::fs::read(root().join("tests/fixtures/control-v3/receipt-states.json")).unwrap()).unwrap();
        let rows=matrix["cases"].as_array().unwrap();assert_eq!(rows.len(),33);let mut failures=Vec::new();
        for row in rows {
            let mut frame=input["frame"].clone();
            for change in row["changes"].as_array().unwrap(){
                let path=change["path"].as_array().unwrap();let mut target=&mut frame;
                for key in path {target=if let Some(key)=key.as_str(){&mut target[key]}else{&mut target[key.as_u64().unwrap() as usize]};}
                *target=change["value"].clone();
            }
            let mut reply=commands["commands"].as_array().unwrap().iter().find(|c|c["name"]=="admission").unwrap()["reply"].clone();
            reply["observations"]=frame["observations"].clone();
            let request=reply["request"].as_object_mut().unwrap();
            for (key,value) in [("outcome",serde_json::json!("rejected")),("reason",serde_json::json!("fixture_source_check")),
                ("receipt",Value::Null),("effect_refs",serde_json::json!([])),("observed_refs",serde_json::json!([])),("required_next",serde_json::json!("refresh"))]{request.insert(key.into(),value);}
            if Projection::parse(&serde_json::to_vec(&frame).unwrap()).is_ok()!=row["accepted_projection"].as_bool().unwrap(){failures.push(format!("{}:projection",row["name"]));}
            if StandardReply::parse(&serde_json::to_vec(&reply).unwrap()).is_ok()!=row["accepted_standard"].as_bool().unwrap(){failures.push(format!("{}:standard",row["name"]));}
        }
        assert!(failures.is_empty(),"source/value/evidence mismatches: {:?}",failures);
    }

    #[test]
    fn derived_fact_profiles_use_actual_python_positive_encoders_and_literal_oracles() {
        let output=Command::new("python3").arg("-I").arg(root().join("tests/fixtures/control-v3/emit_derived.py")).output().unwrap();
        assert!(output.status.success());let rows:Value=serde_json::from_slice(&output.stdout).unwrap();
        let rows=rows.as_array().unwrap();assert_eq!(rows.len(),272);let mut failures=Vec::new();
        for row in rows {
            let raw=row["wire"].as_str().unwrap().as_bytes();let expected=row["accepted"].as_bool().unwrap();
            let accepted=if row["profile"]=="projection"{Projection::parse(raw).is_ok()}else{StandardReply::parse(raw).is_ok()};
            if accepted!=expected{failures.push(format!("{}:{}",row["name"],row["profile"]));}
        }
        assert!(failures.is_empty(),"derived fact/source mismatches: {:?}",failures);
    }

}

#[cfg(test)]
mod qualified_fact_tests {
    use super::{Projection,StandardReply};
    use serde_json::Value;
    use std::{path::PathBuf,process::Command};
    #[test]
    fn qualified_view_claims_use_actual_python_positive_encoders_and_literal_oracles() {
        let path=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_qualified.py");
        let output=Command::new("python3").arg("-I").arg(path).output().unwrap();
        assert!(output.status.success(),"Actual positive encoder failed: {}",String::from_utf8_lossy(&output.stderr));
        let values:Value=serde_json::from_slice(&output.stdout).unwrap();let rows=values.as_array().unwrap();
        assert_eq!(rows.len(),862);
        let mut failures=Vec::new();
        for row in rows {
            let wire=row["wire"].as_str().unwrap().as_bytes();
            let accepted=if row["profile"]=="projection" {Projection::parse(wire).is_ok()}else{StandardReply::parse(wire).is_ok()};
            if accepted!=row["accepted"].as_bool().unwrap(){failures.push(format!("{} {}",row["name"],row["profile"]));}
        }
        assert!(failures.is_empty(),"Qualified claim mismatches: {}",failures.join(", "));
    }
}

#[cfg(test)]
#[test]
fn workflow_progress_receipt_target_and_source_proofs() {
    let path=std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_workflow_progress.py");
    let output=std::process::Command::new("python3").arg("-I").arg(path).output().unwrap();
    assert!(output.status.success(),"actual workflow fixture failed: {}",String::from_utf8_lossy(&output.stderr));
    let cases:Value=serde_json::from_slice(&output.stdout).unwrap();
    let rows=cases.as_array().unwrap();assert_eq!(rows.len(),134);let mut failures=Vec::new();
    for row in rows {
        let bytes=row["wire"].as_str().unwrap().as_bytes();
        let accepted=if row["profile"]=="projection" {Projection::parse(bytes).is_ok()} else {StandardReply::parse(bytes).is_ok()};
        if accepted!=row["accepted"].as_bool().unwrap(){failures.push(format!("{}:{}",row["name"],row["profile"]));}
    }
    assert!(failures.is_empty(),"workflow progress target/proof mismatches: {:?}",failures);
}

#[cfg(test)]
#[test]
fn workflow_source_receipt_identity_and_invocation_proofs() {
    let script=std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_workflow_source_receipts.py");
    let output=std::process::Command::new("python3").arg("-I").arg(script).output().unwrap();
    assert!(output.status.success(),"source vector producer failed: {}",String::from_utf8_lossy(&output.stderr));
    let values:Value=serde_json::from_slice(&output.stdout).unwrap();let rows=values.as_array().unwrap();
    assert_eq!(rows.len(),82);let mut failures=Vec::new();
    for row in rows {
        let bytes=row["wire"].as_str().unwrap().as_bytes();
        let accepted=if row["profile"]=="standard" {StandardReply::parse(bytes).is_ok()}else{Projection::parse(bytes).is_ok()};
        if accepted!=row["accepted"].as_bool().unwrap(){failures.push(format!("{}:{}",row["name"],row["profile"]));}
    }
    assert!(failures.is_empty(),"source identity/invocation mismatches: {:?}",failures);
}

#[cfg(test)]
#[test]
fn unqualified_command_actions_cannot_claim_applied() {
    let script=std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_unqualified_command_actions.py");
    let output=std::process::Command::new("python3").arg("-I").arg(script).output().unwrap();
    assert!(output.status.success(),"action fixture failed: {}",String::from_utf8_lossy(&output.stderr));
    let values:Value=serde_json::from_slice(&output.stdout).unwrap();let rows=values.as_array().unwrap();assert_eq!(rows.len(),12);
    let mut failures=Vec::new();
    for row in rows {
        let bytes=row["wire"].as_str().unwrap().as_bytes();
        let accepted=if row["profile"]=="standard" {StandardReply::parse(bytes).is_ok()}else{Projection::parse(bytes).is_ok()};
        if accepted!=row["accepted"].as_bool().unwrap(){failures.push(format!("{}:{}",row["name"],row["profile"]));}
    }
    assert!(failures.is_empty(),"unqualified action mismatches: {:?}",failures);
}

#[cfg(test)]
#[test]
fn qualified_command_sources_and_checkpoint_heads() {
    let script=std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_qualified_command_sources.py");
    let output=std::process::Command::new("python3").arg("-I").arg(script).output().unwrap();
    assert!(output.status.success(),"actual qualified fixture failed: {}",String::from_utf8_lossy(&output.stderr));
    let values:Value=serde_json::from_slice(&output.stdout).unwrap();let rows=values.as_array().unwrap();
    assert_eq!(rows.len(),76);let mut failures=Vec::new();
    for row in rows {
        let bytes=row["wire"].as_str().unwrap().as_bytes();
        let accepted=if row["profile"]=="standard" {StandardReply::parse(bytes).is_ok()}else{Projection::parse(bytes).is_ok()};
        if accepted!=row["accepted"].as_bool().unwrap(){failures.push(format!("{}:{}",row["name"],row["profile"]));}
    }
    assert!(failures.is_empty(),"qualified command source mismatches: {:?}",failures);
}

#[cfg(test)]
mod read_page_count_regressions {
    use super::*;
    #[test]
    fn actual_read_wire_counts_match_returned_membership() {
        let script=std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_read_page_counts.py");
        let output=std::process::Command::new("python3").arg("-I").arg(script).output().unwrap();
        assert!(output.status.success(),"Actual read producer failed: {}",String::from_utf8_lossy(&output.stderr));
        let cases:Value=serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(cases.as_array().unwrap().len(),18);
        for case in cases.as_array().unwrap() {
            assert_eq!(ReadPayload::parse(case["wire"].as_str().unwrap().as_bytes()).is_ok(),case["accepted"].as_bool().unwrap(),"{}",case["name"]);
        }
    }
}
