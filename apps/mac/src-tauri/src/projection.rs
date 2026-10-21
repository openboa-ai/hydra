//! Closed CP8 read boundary. Decoding never grants execution or command authority.
use crate::protocol::{RuntimeIdentity, Snapshot, MAX_OUTPUT};
use serde::{de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor}, Serialize};
use serde_json::{Map, Number, Value};
use std::{cell::Cell, collections::{HashMap, HashSet}, fmt};

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
    if v["availability"]=="current" || v["availability"]=="stale" {
        need(!v["observed_at"].is_null() && !v["value"].is_null())?; source_value(kind,&v["value"])?;
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
fn question(v: &Value)->R {
    if v=="none" { return Ok(()); } object(v,"source_attempt_id task_ref question_ref revision")?;
    uuid(&v["source_attempt_id"])?; kind_ref(&v["task_ref"],"native_task")?; reference(&v["question_ref"])?; optional(&v["revision"],revision)
}
fn answer(v: &Value)->R {
    if v["state"]=="awaiting" { object(v,"state") }
    else {object(v,"state answer_ref revision")?; need(v["state"]=="received")?; reference(&v["answer_ref"])?; optional(&v["revision"],revision)}
}
fn application(v: &Value)->R {
    object(v,"state context_ref resolved_ref")?; one(&v["state"],"pending context_recorded applied")?;
    optional(&v["context_ref"],reference)?; optional(&v["resolved_ref"],reference)?;
    need((!v["context_ref"].is_null()) == (v["state"]!="pending") &&
      (!v["resolved_ref"].is_null()) == (v["state"]=="applied"))
}
fn decision(v: &Value,index:&Index<'_>)->R {
    object(v,"question answer acceptance application")?;
    fact(&v["question"],question,index)?; fact(&v["answer"],answer,index)?;
    fact(&v["acceptance"],|x| one(x,"pending accepted conflict invalid"),index)?; fact(&v["application"],application,index)?;
    for k in ["question","answer","acceptance","application"] {
        if !v[k]["value"].is_null() {
            for e in v[k]["evidence"].as_array().unwrap() {
                let source=evidence_in(e,index)?;
                need(!["native_task_metadata","native_history_page"].contains(&string(&source["resource"]["kind"])?))?;
            }
        }
    }
    if v["question"]["value"]=="none" {
        for k in ["answer","acceptance","application"] { need(v[k]["value"].is_null() && v[k]["reason"]=="not_applicable")?; }
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
    if kind=="verification" {one(&v["verdict"],"passed failed")?; optional(&v["review"],|x| one(x,"pending accepted failed not_required"))?;}
    if kind=="verification_review" {
        assignment(&v["assignment"])?;
        for k in ["attempt_id","head","contract_revision"] {need(v["assignment"][k]==v["candidate"][k])?;}
        one(&v["review"],"accepted failed pending")?;
    }
    if kind=="publication" {
        branch(&v["branch"])?; sha(&v["observed_remote_head"])?; need(v["observed_remote_head"]==v["candidate"]["head"])?;
        optional(&v["pr_ref"],reference)?; refs(&v["review_request_refs"])?; one(&v["stage"],"branch_published pr_ready publication_ready")?;
    }
    if kind=="delivery" {
        reference(&v["pr_ref"])?; sha(&v["integration_base"])?; sha(&v["merge_commit"])?;
        one(&v["post_merge"],"pending success failed unknown")?; optional(&v["issue_closed"],boolean)?;
    }
    if kind=="cleanup" {
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
    if kind.is_some() && v["action"]=="cleanup" {need(v["receipt"]["resource"]==v["target"]["resource"])?;}
    if v["outcome"]=="applied" && ["workflow_step","cleanup"].contains(&string(&v["action"])?) {
        need(!v["receipt"].is_null())?;
    }
    if v["action"]=="admission_set" || matches!(kind,Some("checkpoint"|"decision")) {
        need((!v["receipt"].is_null())==(v["outcome"]=="applied"))?;
    }
    if let Some(k)=kind {
        need((v["action"]=="admission_set" && k=="admission") ||
          (v["action"]=="workflow_step" && ["checkpoint","decision","continuation","verification","verification_review","publication","delivery"].contains(&k)) ||
          (v["action"]=="cleanup" && k=="cleanup"))?;
    } Ok(())
}
fn observations(value:&Value)->Result<Index<'_>,&'static str> {
    let rows=value.as_array().ok_or(INVALID)?; need(rows.len()<=4096)?; let mut index=HashMap::new();
    for v in rows {observation(v)?; need(index.insert(string(&v["key"])?,v).is_none())?;} Ok(index)
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
    let mut projects=HashSet::new();
    let rows=v["projects"].as_array().ok_or(INVALID)?; need(rows.len()<=1024)?;
    for p in rows {
        object(p,"repository_ref goal_refs work_refs admission execution attention_refs coverage source_refs")?;
        kind_ref(&p["repository_ref"],"repository")?; unique(&mut projects,&p["repository_ref"])?;
        list(&p["goal_refs"],goal_ref,100)?; list(&p["work_refs"],reference,128)?;
        fact(&p["admission"],|x| one(x,"allowed paused stopped"),&index)?; fact(&p["execution"],execution,&index)?;
        refs(&p["attention_refs"])?; coverage(&p["coverage"])?; refs(&p["source_refs"])?;
    }
    let mut works=HashSet::new();
    let rows=v["work"].as_array().ok_or(INVALID)?; need(rows.len()<=512)?;
    for w in rows {
        object(w,"issue_ref goal_refs spec_refs requirement_refs readiness stage admission execution wait decision delivery result cleanup next_action task_refs resource_refs evidence_refs")?;
        kind_ref(&w["issue_ref"],"issue")?; unique(&mut works,&w["issue_ref"])?;
        list(&w["goal_refs"],goal_ref,100)?; list(&w["spec_refs"],requirement_ref,100)?; list(&w["requirement_refs"],requirement_ref,100)?;
        fact(&w["readiness"],readiness,&index)?; fact(&w["stage"],|x| one(x,"prepare design implement verify deliver observe complete"),&index)?;
        fact(&w["admission"],|x| one(x,"allowed paused stopped"),&index)?; fact(&w["execution"],execution,&index)?;
        fact(&w["wait"],waiting,&index)?; decision(&w["decision"],&index)?;
        fact(&w["delivery"],|x| one(x,"candidate published merged post_merge_verified deployment_observed"),&index)?;
        fact(&w["result"],|x| one(x,"incomplete complete cancelled"),&index)?; fact(&w["cleanup"],|x| one(x,"not_required pending complete"),&index)?;
        fact(&w["next_action"],|x| next_action(x,&index),&index)?; refs(&w["task_refs"])?; refs(&w["resource_refs"])?;
        list(&w["evidence_refs"],|e| evidence_in(e,&index).map(|_|()),4096)?;
    }
    list(&v["relations"],|r| {
        object(r,"from to kind evidence")?; reference(&r["from"])?; reference(&r["to"])?; one(&r["kind"],"parent depends_on implements verifies delivers")?;
        fact(&serde_json::json!({"value":"relation","evidence":r["evidence"],"reason":null}),|_|Ok(()),&index)
    },4096)?;
    coverage(&v["page"])?;
    list(&v["capabilities"],|c| {
        object(c,"source operation state actor qualification_ref reason")?; one(&c["source"],"github codex resource_provider hydra")?;
        short(&c["operation"])?; one(&c["state"],"available unsupported unavailable")?; one(&c["actor"],"core native_actor provider")?;
        optional(&c["qualification_ref"],|x| text(x,2048,false,false))?; optional(&c["reason"],code)?;
        need(if c["state"]=="available" {!c["qualification_ref"].is_null() && c["reason"].is_null()} else {!c["reason"].is_null()})
    },4096)?;
    optional(&v["request"],|r| command_result(r,&index))
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
        command_result(&v["request"],&observations(&v["observations"])?)?; Ok(Self(v))
    }
}
#[derive(Clone,Debug,Serialize)]
#[serde(untagged)]
pub enum ReadPayload {V3(Projection),V2(Snapshot)}
impl ReadPayload {
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
}
