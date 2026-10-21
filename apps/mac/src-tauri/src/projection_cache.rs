//! Memory-only validated read cache. Eviction never retires work or resources.
use crate::projection::{observed_repository_bindings,ReadPayload};
use crate::projection_policy::ReadPolicy;
use crate::protocol::RuntimeIdentity;
use serde::{Serialize, Serializer};
use serde_json::Value;
use std::{collections::{BTreeMap, HashMap, VecDeque}, sync::Arc, time::{Duration, Instant}};

const MAX_BYTES: usize = 4 * 1_048_576;
const MAX_DETAILS: usize = 16;
const MAX_SEQUENCE: u64 = 9_007_199_254_740_991;
const MAX_PENDING: usize = 16;

#[derive(Clone, Debug)]
pub struct ReadTicket {
    pub scope: String,
    pub epoch: String,
    pub request_id: String,
    pub sequence: u64,
    detail: bool,
    pub credential_scope:Option<String>,
    context_sequence:u64,
    remote:bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct ReadContext {pub scope:Option<String>,pub sequence:u64}
#[derive(Clone, Debug, Serialize)]
pub struct CachedRead {
    #[serde(serialize_with = "serialize_payload")]
    pub payload: Arc<ReadPayload>,
    pub age_ms: u64,
    pub cached: bool,
    pub stale: bool,
    pub sequence: u64,
    pub read_context:ReadContext,
}
fn serialize_payload<S:Serializer>(value:&Arc<ReadPayload>,serializer:S)->Result<S::Ok,S::Error> {
    value.as_ref().serialize(serializer)
}
struct Entry {payload:Arc<ReadPayload>,received:Instant,bytes:usize,detail:bool,stale:bool,sequence:u64}
#[derive(Default)]
struct Order {issued:u64,settled:u64}
pub struct ReadCache {
    epoch:String,
    runtime:Option<Value>,
    next:u64,
    orders:HashMap<String,Order>,
    entries:HashMap<String,Entry>,
    lru:VecDeque<String>,
    bytes:usize,
    last_clock:Option<Instant>,
    ledger:VecDeque<(ReadTicket,bool,Option<(bool,Instant)>)>,
    policy:ReadPolicy,
    remote_started:Option<Instant>,
    local_started:Option<Instant>,
    continuations:VecDeque<(String,String,u64)>,
    context:ReadContext,
    last_context_probe:Option<Instant>,
    repository_bindings:BTreeMap<String,u64>,
}
fn uuid(value:&str)->bool {
    value.len()==36 && value.bytes().enumerate().all(|(i,c)| if [8,13,18,23].contains(&i) {
        c==b'-'
    } else {c.is_ascii_digit() || (b'a'..=b'f').contains(&c)})
}
fn runtime_key(payload:&ReadPayload)->Result<Value,&'static str> {
    let value=serde_json::to_value(payload).map_err(|_|"invalid_response")?;
    let identity:RuntimeIdentity=serde_json::from_value(value["runtime"].clone()).map_err(|_|"invalid_response")?;
    if !identity.valid() {return Err("runtime_identity_unavailable");}
    Ok(serde_json::json!({"version":identity.version,"code_digest":identity.code_digest,
        "config_digest":identity.config_digest,"control_binding_digest":identity.control_binding_digest,
        "identity_reason":identity.identity_reason}))
}
impl ReadCache {
    pub fn new(epoch:String)->Result<Self,&'static str> {
        if !uuid(&epoch) {return Err("binding_invalid");}
        Ok(Self {epoch,runtime:None,next:0,orders:HashMap::new(),entries:HashMap::new(),
            lru:VecDeque::new(),bytes:0,last_clock:None,ledger:VecDeque::new(),policy:ReadPolicy::default(),remote_started:None,local_started:None,continuations:VecDeque::new(),context:ReadContext{scope:None,sequence:0},last_context_probe:None,repository_bindings:BTreeMap::new()})
    }
    pub fn binding_changed(&mut self,epoch:String)->Result<(),&'static str> {
        if !uuid(&epoch) || epoch==self.epoch {return Err("binding_invalid");}
        self.epoch=epoch; self.runtime=None; self.orders.clear(); self.entries.clear();
        self.lru.clear(); self.bytes=0; self.last_clock=None; self.ledger.clear();
        self.continuations.clear();self.context=ReadContext{scope:None,sequence:0};self.last_context_probe=None;
        self.repository_bindings.clear();
        self.policy=ReadPolicy::default(); self.remote_started=None; self.local_started=None; Ok(())
    }
    fn clock(&mut self,now:Instant)->Instant {
        if let Some(previous)=self.last_clock {
            if now<previous {self.clock_resumed(); return previous;}
        }
        self.last_clock=Some(now); now
    }
    pub fn clock_resumed(&mut self) {
        for entry in self.entries.values_mut() {entry.stale=true;}
    }
    pub fn issue(&mut self,scope:String,request_id:String,detail:bool)->Result<ReadTicket,&'static str> {
        if scope.is_empty() || scope.chars().count()>4096 || scope.chars().any(|c|c<'\u{20}' || c=='\u{7f}') || !uuid(&request_id) {
            return Err("read_request_invalid");
        }
        if !self.orders.contains_key(&scope) && self.orders.len()>=MAX_PENDING {
            return Err("read_capacity_held");
        }
        let sequence=self.next.checked_add(1).filter(|n|*n<=MAX_SEQUENCE).ok_or("sequence_exhausted")?;
        self.next=sequence; self.orders.entry(scope.clone()).or_default().issued=sequence;
        let remote=scope.starts_with("remote:");
        let ticket=ReadTicket{scope,epoch:self.epoch.clone(),request_id,sequence,detail,
            credential_scope:self.context.scope.clone(),context_sequence:self.context.sequence,remote};
        self.continuations.retain(|(scope,_,_)|scope!=&ticket.scope);
        self.ledger.push_back((ticket.clone(),false,None));
        while self.ledger.len()>64 {self.ledger.pop_front();}
        Ok(ticket)
    }
    fn current(&self,ticket:&ReadTicket)->bool {
        ticket.epoch==self.epoch && self.orders.get(&ticket.scope).is_some_and(|o|o.issued==ticket.sequence && o.settled<ticket.sequence)
    }
    pub fn failed(&mut self,ticket:&ReadTicket)->bool {
        if !self.current(ticket) {return false;}
        self.orders.get_mut(&ticket.scope).unwrap().settled=ticket.sequence;
        if let Some(entry)=self.entries.get_mut(&ticket.scope) {entry.stale=true;}
        self.orders.remove(&ticket.scope);
        true
    }
    pub fn accept(&mut self,ticket:&ReadTicket,bytes:&[u8],now:Instant)->Result<CachedRead,&'static str> {
        let current=self.current(ticket);
        let original=self.ledger.iter().any(|(t,seen,_)|!seen && t.sequence==ticket.sequence &&
            t.request_id==ticket.request_id && t.scope==ticket.scope && t.epoch==ticket.epoch);
        if ticket.epoch!=self.epoch || !original {return Err("stale_read");}
        let payload=match ReadPayload::parse(bytes) {
            Ok(value)=>value,
            Err(reason)=>{self.failed(ticket);return Err(reason);}
        };
        if !matches!(payload,ReadPayload::V3(_)) {
            self.failed(ticket);return Err("projection_schema_mismatch");
        }
        let value=serde_json::to_value(&payload).map_err(|_|"invalid_response")?;
        if value["schema_version"]==3 && (value["binding_epoch"]!=ticket.epoch || value["request_id"]!=ticket.request_id) {
            self.failed(ticket); return Err("read_binding_mismatch");
        }
        if ticket.remote {
            if ticket.credential_scope.is_none() {self.failed(ticket);return Err("read_context_unavailable");}
            for hint in value["retry_hints"].as_array().unwrap() {
                let observation=value["observations"].as_array().unwrap().iter().find(|o|o["key"]==hint["observation_key"]).unwrap();
                if observation["resource"]["source"]=="github" && hint["scope"].as_str()!=ticket.credential_scope.as_deref() {
                    self.failed(ticket);return Err("read_context_mismatch");
                }
            }
            if ticket.context_sequence!=self.context.sequence {
                let (_,seen,_)=self.ledger.iter_mut().find(|(t,_,_)|t.sequence==ticket.sequence).unwrap();*seen=true;
                self.policy.observe_scoped(&payload,now,false,ticket.credential_scope.as_deref());return Err("stale_read");
            }
        }
        let key=match runtime_key(&payload) {
            Ok(value)=>value,
            Err(reason)=>{self.failed(ticket);return Err(reason);}
        };
        if self.runtime.as_ref().is_some_and(|old|old!=&key) {
            if !current {
                // The data is fenced, but this original request consumed the
                // same connection's provider quota. Apply its hint only once.
                let (_,seen,_)=self.ledger.iter_mut().find(|(t,_,_)|t.sequence==ticket.sequence).unwrap();
                *seen=true;self.policy.observe_scoped(&payload,now,false,ticket.credential_scope.as_deref());return Err("stale_read");
            }
            // The response is a fresh, bound read of the new runtime. Invalidate
            // older cache/pending generations; retain the connection's quota wait.
            self.entries.clear();self.lru.clear();self.bytes=0;self.orders.clear();self.continuations.clear();
            self.repository_bindings.clear();
            self.orders.insert(ticket.scope.clone(),Order{issued:ticket.sequence,settled:0});
            let started=self.ledger.iter().find(|(t,_,_)|t.sequence==ticket.sequence).and_then(|(_,_,start)|*start);
            self.remote_started=None;self.local_started=None;
            if let Some((remote,at))=started {
                if remote {self.remote_started=Some(at);}else{self.local_started=Some(at);}
            }
        }
        let (_,seen,_)=self.ledger.iter_mut().find(|(t,_,_)|t.sequence==ticket.sequence).unwrap();
        *seen=true;
        // This raw cache preserves valid source frames. The source-aware reducer
        // fences regressed observations without discarding independent facts.
        self.policy.observe_scoped(&payload,now,current,ticket.credential_scope.as_deref());
        if !current {return Err("stale_read");}
        let size=serde_json::to_vec(&payload).map_err(|_|"invalid_response")?.len();
        if size>1_048_576 {self.failed(ticket);return Err("response_limit");}
        let now=self.clock(now);
        self.runtime=Some(key);
        if ticket.remote {
            for (name,number) in observed_repository_bindings(&value) {
                if self.repository_bindings.len()<1024 || self.repository_bindings.contains_key(&name) {
                    // Identity is retained across failed reads, never refreshed
                    // into a new source fact or silently retargeted by a name.
                    self.repository_bindings.entry(name).or_insert(number);
                }
            }
        }
        self.orders.get_mut(&ticket.scope).unwrap().settled=ticket.sequence;
        self.remove(&ticket.scope);
        let payload=Arc::new(payload);
        self.entries.insert(ticket.scope.clone(),Entry{payload:payload.clone(),received:now,
            bytes:size,detail:ticket.detail,stale:false,sequence:ticket.sequence});
        self.bytes+=size; self.touch(&ticket.scope); self.bound();
        self.remember_continuations(ticket,&value);
        Ok(CachedRead{payload,age_ms:0,cached:false,stale:false,sequence:ticket.sequence,read_context:self.context.clone()})
    }
    pub fn get(&mut self,scope:&str,local:bool,now:Instant)->Option<CachedRead> {
        let now=self.clock(now);
        let entry=self.entries.get(scope)?;
        let age=now.saturating_duration_since(entry.received);
        let result=CachedRead{payload:entry.payload.clone(),age_ms:age.as_millis().min(MAX_SEQUENCE as u128) as u64,
            cached:true,stale:entry.stale || age>=Duration::from_secs(if local {15}else{60}),sequence:entry.sequence,read_context:self.context.clone()};
        self.touch(scope); Some(result)
    }
    pub fn epoch(&self)->&str {&self.epoch}
    pub fn repository_binding_hints(&self)->Result<String,&'static str> {
        let value=serde_json::to_string(&self.repository_bindings).map_err(|_|"read_binding_unavailable")?;
        if value.len()>196_608{return Err("read_binding_limit");}Ok(value)
    }
    pub fn context_probe_due(&mut self,now:Instant)->bool {
        if self.last_context_probe.is_some_and(|at|now.saturating_duration_since(at)<Duration::from_secs(5)) {return false;}
        self.last_context_probe=Some(now);true
    }
    pub fn context_changed(&mut self,scope:Option<String>)->Result<(),&'static str> {
        if scope.as_ref().is_some_and(|s|s.is_empty() || s.chars().count()>256 || s.chars().any(|c|c<'\u{20}' || c=='\u{7f}')) {return Err("read_context_invalid");}
        if self.context.scope==scope {return Ok(());}
        self.context.sequence=self.context.sequence.checked_add(1).filter(|n|*n<=MAX_SEQUENCE).ok_or("sequence_exhausted")?;
        self.context.scope=scope;
        // Numeric identity pins do not confer access or reuse source facts.
        // The fixed reader revalidates each registered address with the new
        // credential; binding/runtime changes still discard these pins.
        self.remote_started=None;
        let scopes:Vec<_>=self.entries.keys().filter(|s|s.starts_with("remote:")).cloned().collect();
        for scope in scopes {self.remove(&scope);}
        self.orders.retain(|scope,_|!scope.starts_with("remote:"));
        self.continuations.retain(|(scope,_,_)|!scope.starts_with("remote:"));
        Ok(())
    }
    pub fn read_held(&self,now:Instant,remote:bool,scope:&str,continuation:bool,explicit_recovery:bool)->Result<bool,&'static str> {
        if remote && self.context.scope.is_none() {return Err("read_context_unavailable");}
        let issued=self.continuations.iter().any(|(next,parent,sequence)|
            next==scope && self.entries.get(parent).is_some_and(|entry|entry.sequence==*sequence && !entry.stale));
        let repeated=self.entries.contains_key(scope) || self.ledger.iter().any(|(ticket,_,_)|
            ticket.scope==scope && ticket.epoch==self.epoch && (!ticket.remote ||
                ticket.context_sequence==self.context.sequence && ticket.credential_scope==self.context.scope));
        if continuation && !issued && !repeated {return Err("invalid_cursor");}
        let continuation=continuation && !repeated && issued;
        if remote && continuation {
            // A cursor advances the bounded read; it is not an ordinary poll.
            // Connection quotas and exhausted automatic retries still apply.
            return self.policy.wait_seconds("github",self.context.scope.as_deref().ok_or("read_context_unavailable")?,now,explicit_recovery)
                .map(|seconds|seconds>0);
        }
        if remote {self.remote_wait(now,explicit_recovery).map(|seconds|seconds>0)}
        else {Ok(!continuation && self.local_wait(now))}
    }
    pub fn remote_wait(&self,now:Instant,explicit_recovery:bool)->Result<u64,&'static str> {
        let quota=self.policy.wait_seconds("github",self.context.scope.as_deref().ok_or("read_context_unavailable")?,now,explicit_recovery)?;
        let poll=self.remote_started.map(|start|Duration::from_secs(60).saturating_sub(now.saturating_duration_since(start)))
            .unwrap_or(Duration::ZERO);
        Ok(quota.max(poll.as_secs()+u64::from(poll.subsec_nanos()!=0)))
    }
    pub fn remote_started(&mut self,now:Instant) {
        self.remote_started=Some(now);
        if let Some((_,_,start))=self.ledger.back_mut() {*start=Some((true,now));}
    }
    pub fn local_wait(&self,now:Instant)->bool {
        self.local_started.is_some_and(|start|now.saturating_duration_since(start)<Duration::from_secs(5))
    }
    pub fn local_started(&mut self,now:Instant) {
        self.local_started=Some(now);
        if let Some((_,_,start))=self.ledger.back_mut() {*start=Some((false,now));}
    }

    fn remember_continuations(&mut self,ticket:&ReadTicket,value:&Value) {
        let Some(lane)=ticket.scope.split(':').next().filter(|lane|["remote","local"].contains(lane)) else {return;};
        let mut targets=Vec::new();
        let bindings=observed_repository_bindings(value);
        if let Some(cursor)=value["page"]["next_cursor"].as_str() {
            let repository=ticket.scope.split(':').nth(1).unwrap_or("overview");
            targets.push((repository.to_owned(),cursor.to_owned()));
        }
        for project in value["projects"].as_array().unwrap() {
            if let Some(cursor)=project["coverage"]["next_cursor"].as_str() {
                let requested=project["source_refs"].as_array().unwrap().iter().filter_map(|source| {
                    if source["source"]!="github" || source["kind"]!="repository" {return None;}
                    let name=source["id"].as_str()?.strip_prefix("requested:")?.to_ascii_lowercase();
                    (bindings.get(&name).map(u64::to_string).as_deref()==project["repository_ref"]["id"].as_str()).then_some(name)
                }).next();
                if let Some(name)=requested.or_else(||value["observations"].as_array().unwrap().iter()
                    .find(|o|o["resource"]==project["repository_ref"] && o["resource"]["kind"]=="repository")
                    .and_then(|o|o["value"]["full_name"].as_str()).map(str::to_ascii_lowercase)) {
                    targets.push((name,cursor.to_owned()));
                }
            }
        }
        for (repository,cursor) in targets {
            let scope=format!("{lane}:{repository}:{cursor}");
            self.continuations.retain(|(next,_,_)|next!=&scope);
            self.continuations.push_back((scope,ticket.scope.clone(),ticket.sequence));
            while self.continuations.len()>64 {self.continuations.pop_front();}
        }
    }
    fn touch(&mut self,scope:&str) {
        self.lru.retain(|key|key!=scope); self.lru.push_back(scope.to_owned());
    }
    fn remove(&mut self,scope:&str) {
        self.continuations.retain(|(_,parent,_)|parent!=scope);
        if let Some(entry)=self.entries.remove(scope) {self.bytes-=entry.bytes;}
        self.lru.retain(|key|key!=scope);
        if self.orders.get(scope).is_some_and(|order|order.issued==order.settled) {
            self.orders.remove(scope);
        }
    }
    fn bound(&mut self) {
        while self.entries.values().filter(|e|e.detail).count()>MAX_DETAILS {
            let victim=self.lru.iter().find(|key|self.entries.get(*key).is_some_and(|e|e.detail)).cloned().unwrap();
            self.remove(&victim);
        }
        while self.bytes>MAX_BYTES {
            let victim=self.lru.iter().find(|key|self.entries.get(*key).is_some_and(|e|e.detail)).or_else(||self.lru.front()).cloned().unwrap();
            self.remove(&victim);
        }
    }
    #[cfg(test)]
    fn counts(&self)->(usize,usize,usize) {(self.entries.len(),self.bytes,self.entries.values().filter(|e|e.detail).count())}
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{path::PathBuf,process::Command};
    const EPOCH:&str="00000000-0000-4000-8000-000000000001";
    fn test_cache()->ReadCache {
        let mut cache=ReadCache::new(EPOCH.into()).unwrap();
        cache.context_changed(Some(format!("github:registered-read:{EPOCH}"))).unwrap();cache
    }
    fn request(n:u32)->String {format!("00000000-0000-4000-8000-{n:012x}")}
    fn fixture(request_id:&str)->Vec<u8> {
        let path=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_wire.py");
        let output=Command::new("python3").arg("-I").arg(path).output().unwrap();
        assert!(output.status.success());
        let vectors:Value=serde_json::from_slice(&output.stdout).unwrap();
        let mut frame:Value=serde_json::from_str(vectors[0]["wire"].as_str().unwrap()).unwrap();
        frame["request_id"]=Value::String(request_id.into());
        serde_json::to_vec(&frame).unwrap()
    }
    #[test]
    fn retained_names_bound_memory_without_retargeting_and_rename_cursors_keep_registered_address() {
        let now=Instant::now();let mut cache=test_cache();
        let mut renamed:Value=serde_json::from_slice(&fixture(&request(70))).unwrap();
        let observed=renamed["observations"].as_array_mut().unwrap().iter_mut()
            .find(|o|o["resource"]["kind"]=="repository" && o["resource"]["id"]=="101").unwrap();
        observed["key"]="github:repository-request:example/alpha".into();
        observed["coverage"]["scope"]="repository-address:example/alpha".into();
        observed["value"]["full_name"]="example/renamed".into();
        observed["value"]["url"]="https://github.com/example/renamed".into();
        renamed["projects"][0]["source_refs"].as_array_mut().unwrap().push(
            serde_json::json!({"source":"github","kind":"repository","id":"requested:example/alpha"}));
        renamed["projects"][0]["coverage"]["next_cursor"]="rename-page".into();
        let ticket=cache.issue("remote:overview:".into(),request(70),false).unwrap();cache.remote_started(now);
        cache.accept(&ticket,&serde_json::to_vec(&renamed).unwrap(),now).unwrap();
        assert_eq!(cache.read_held(now+Duration::from_secs(1),true,"remote:example/alpha:rename-page",true,false),Ok(false));
        assert_eq!(cache.read_held(now+Duration::from_secs(1),true,"remote:example/renamed:rename-page",true,false),Err("invalid_cursor"));

        // Fill through validated bounded response pages, not private map writes.
        let seed:Value=serde_json::from_slice(&fixture(&request(71))).unwrap();
        let admission=seed["observations"].as_array().unwrap().iter().find(|o|o["resource"]["kind"]=="admission").unwrap().clone();
        let repository=seed["observations"].as_array().unwrap().iter().find(|o|o["resource"]["kind"]=="repository").unwrap().clone();
        let project=seed["projects"][0].clone();
        let page=|first:u64,count:u64,request_id:String| {
            let mut frame=seed.clone();frame["request_id"]=request_id.into();
            frame["work"]=serde_json::json!([]);frame["relations"]=serde_json::json!([]);
            frame["observations"]=serde_json::json!([admission.clone()]);frame["projects"]=serde_json::json!([]);
            for id in first..first+count {
                let mut o=repository.clone();let name=format!("example/p{id}");
                o["key"]=format!("github:{id}:repository").into();o["resource"]["id"]=id.to_string().into();
                o["coverage"]["scope"]=format!("resource:{id}").into();
                o["value"]["numeric_id"]=id.into();o["value"]["full_name"]=name.clone().into();
                o["value"]["url"]=format!("https://github.com/{name}").into();
                let mut p=project.clone();p["repository_ref"]=o["resource"].clone();
                p["goal_refs"]=serde_json::json!([]);p["work_refs"]=serde_json::json!([]);
                p["source_refs"]=serde_json::json!([o["resource"].clone(),admission["resource"].clone()]);
                p["coverage"]=serde_json::json!({"state":"complete","scope":format!("repository:{id};managed-work"),
                    "returned_count":0,"total_count":0,"next_cursor":null,"reason":null});
                frame["observations"].as_array_mut().unwrap().push(o);frame["projects"].as_array_mut().unwrap().push(p);
            }
            frame["page"]=serde_json::json!({"state":"complete","scope":"host;overview","returned_count":count,
                "total_count":count,"next_cursor":null,"reason":null});frame
        };
        let mut capacity=test_cache();
        for (first,n) in [(201,71),(713,72)] {
            let value=page(first,512,request(n));let bytes=serde_json::to_vec(&value).unwrap();
            assert!(bytes.len()<=1_048_576);
            let ticket=capacity.issue("remote:overview:".into(),request(n),false).unwrap();
            capacity.accept(&ticket,&bytes,now).unwrap();
        }
        let before=capacity.repository_binding_hints().unwrap();assert!(before.len()<=196_608);
        let pins:Value=serde_json::from_str(&before).unwrap();assert_eq!(pins.as_object().unwrap().len(),1024);
        assert_eq!(pins["example/p201"],201);
        let ticket=capacity.issue("remote:overview:".into(),request(73),false).unwrap();
        capacity.accept(&ticket,&serde_json::to_vec(&page(2000,1,request(73))).unwrap(),now).unwrap();
        assert_eq!(capacity.repository_binding_hints().unwrap(),before,"A new observed name exceeded the pin bound");
        let mut reused=page(9000,1,request(74));
        reused["observations"][1]["value"]["full_name"]="example/p201".into();
        reused["observations"][1]["value"]["url"]="https://github.com/example/p201".into();
        let ticket=capacity.issue("remote:overview:".into(),request(74),false).unwrap();
        capacity.accept(&ticket,&serde_json::to_vec(&reused).unwrap(),now).unwrap();
        assert_eq!(capacity.repository_binding_hints().unwrap(),before,"A reused name retargeted retained identity");
    }
    #[test]
    fn credential_rotation_keeps_per_scope_waits_fences_old_remote_and_preserves_local_cache() {
        let mut cache=test_cache();let now=Instant::now();
        let scope_a="connection:alpha";let scope_b="connection:beta";
        cache.context_changed(Some(scope_a.into())).unwrap();
        let local=cache.issue("local:overview:".into(),request(60),false).unwrap();
        cache.accept(&local,&fixture(&request(60)),now).unwrap();
        let old=cache.issue("remote:overview:".into(),request(61),false).unwrap();cache.remote_started(now);
        let mut value:Value=serde_json::from_slice(&fixture(&request(61))).unwrap();
        let mut o=value["observations"].as_array().unwrap().iter().find(|o|o["resource"]["source"]=="github").unwrap().clone();
        o["key"]="query:limited".into();o["reason"]="provider_wait".into();
        value["observations"].as_array_mut().unwrap().push(o);
        value["retry_hints"]=serde_json::json!([{"observation_key":"query:limited","scope":scope_a,"after_seconds":3600,"basis":"provider"}]);
        cache.context_changed(Some(scope_b.into())).unwrap();
        assert_eq!(cache.accept(&old,&serde_json::to_vec(&value).unwrap(),now).unwrap_err(),"stale_read");
        assert!(cache.get("remote:overview:",false,now).is_none());
        assert_eq!(cache.remote_wait(now+Duration::from_secs(1),false),Ok(0),"Credential B inherited A's ordinary poll floor");
        assert_eq!(cache.remote_wait(now+Duration::from_secs(60),false),Ok(0),"Credential B inherited A's provider wait");
        let retained=cache.get("local:overview:",true,now).unwrap();
        assert_eq!(retained.read_context.scope.as_deref(),Some(scope_b));
        assert!(!retained.stale,"Credential rotation invalidated independent local facts");
        cache.context_changed(Some(scope_a.into())).unwrap();
        assert_eq!(cache.remote_wait(now+Duration::from_secs(60),true),Ok(3540),"Rotation back erased an unexpired wait");
        cache.context_changed(None).unwrap();
        assert_eq!(cache.read_held(now,true,"remote:overview:",false,true),Err("read_context_unavailable"));
        assert_eq!(cache.read_held(now,false,"local:overview:",false,false),Ok(false));
        assert!(cache.context_probe_due(now));assert!(!cache.context_probe_due(now+Duration::from_secs(4)));
        assert!(cache.context_probe_due(now+Duration::from_secs(5)));
    }
    #[test]
    fn credential_rotation_rebuilds_remote_cache_immediately_and_keeps_independent_poll_floors() {
        let mut cache=test_cache();let now=Instant::now();
        let scope_a="connection:alpha";let scope_b="connection:beta";
        cache.context_changed(Some(scope_a.into())).unwrap();
        let old=cache.issue("remote:overview:".into(),request(70),false).unwrap();
        cache.remote_started(now);cache.accept(&old,&fixture(&old.request_id),now).unwrap();
        let local=cache.issue("local:overview:".into(),request(71),false).unwrap();
        cache.local_started(now);cache.accept(&local,&fixture(&local.request_id),now).unwrap();
        let changed=now+Duration::from_secs(1);
        cache.context_changed(Some(scope_a.into())).unwrap();
        assert_eq!(cache.read_held(changed,true,"remote:overview:",false,false),Ok(true),"An unchanged credential reset its poll floor");
        cache.context_changed(Some(scope_b.into())).unwrap();
        assert!(cache.get("remote:overview:",false,changed).is_none());
        assert_eq!(cache.read_held(changed,true,"remote:overview:",false,false),Ok(false),"The new credential cannot rebuild an invalidated cache");
        assert!(cache.local_wait(changed),"Credential rotation reset the independent local floor");
        assert!(!cache.get("local:overview:",true,changed).unwrap().stale);
        let fresh=cache.issue("remote:overview:".into(),request(72),false).unwrap();
        cache.remote_started(changed);
        let read=cache.accept(&fresh,&fixture(&fresh.request_id),changed).unwrap();
        assert_eq!(read.read_context.scope.as_deref(),Some(scope_b));
        assert!(cache.get("remote:overview:",false,changed).is_some());
        assert_eq!(cache.remote_wait(changed+Duration::from_secs(1),false),Ok(59),"The new read did not establish its own poll floor");
    }
    #[test]
    fn unissued_cursor_positions_never_reach_a_new_read_after_the_poll_floor() {
        let code="import sys,json;sys.path.insert(0,str(__import__('pathlib').Path.cwd()));from hydra_sdlc.projection_read import _cursor,_position;cfg={'repos':['example/alpha','example/beta','example/gamma']};epoch='00000000-0000-4000-8000-000000000001';issued=_cursor(cfg,epoch,None,{'project_index':1});altered=_cursor(cfg,epoch,None,{'project_index':2});assert _position(cfg,epoch,None,altered)=={'project_index':2};print(json.dumps({'issued':issued,'altered':altered}))";
        let root=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let output=Command::new("python3").args(["-I","-c",code]).current_dir(root).output().unwrap();
        assert!(output.status.success(),"actual cursor codec failed: {}",String::from_utf8_lossy(&output.stderr));
        let tokens:Value=serde_json::from_slice(&output.stdout).unwrap();
        let issued=tokens["issued"].as_str().unwrap();let altered=tokens["altered"].as_str().unwrap();assert_ne!(issued,altered);
        let mut cache=test_cache();let now=Instant::now();
        let mut frame:Value=serde_json::from_slice(&fixture(&request(780))).unwrap();
        frame["page"]["next_cursor"]=issued.into();
        let ticket=cache.issue("remote:overview:".into(),request(780),false).unwrap();cache.remote_started(now);
        cache.accept(&ticket,&serde_json::to_vec(&frame).unwrap(),now).unwrap();
        let allowed=format!("remote:overview:{issued}");let forged=format!("remote:overview:{altered}");
        assert_eq!(cache.read_held(now,true,&allowed,true,false),Ok(false));
        for elapsed in [0,60,120] {
            let time=now+Duration::from_secs(elapsed);
            assert!(cache.read_held(time,true,&forged,true,false).is_err(),"An altered position became a new read after {elapsed}s");
            assert!(cache.read_held(time,true,&format!("remote:example/other:{issued}"),true,false).is_err());
        }
        let consumed=cache.issue(allowed.clone(),request(781),false).unwrap();cache.remote_started(now);
        cache.failed(&consumed);
        assert_eq!(cache.read_held(now,true,&allowed,true,false),Ok(true));
        assert_eq!(cache.read_held(now+Duration::from_secs(60),true,&allowed,true,false),Ok(false),"A previously issued failed query lost explicit retry");
        cache.context_changed(Some("github:another-credential".into())).unwrap();
        assert!(cache.read_held(now+Duration::from_secs(120),true,&allowed,true,false).is_err());
    }
    #[test]
    fn continuation_privileges_require_exact_issued_lineage_and_are_consumed() {
        let mut cache=test_cache();let now=Instant::now();
        let mut frame:Value=serde_json::from_slice(&fixture(&request(50))).unwrap();
        frame["page"]["next_cursor"]="issued_cursor".into();
        let ticket=cache.issue("remote:overview:".into(),request(50),false).unwrap();cache.remote_started(now);
        cache.accept(&ticket,&serde_json::to_vec(&frame).unwrap(),now).unwrap();
        assert_eq!(cache.read_held(now,true,"remote:overview:issued_cursor",true,false),Ok(false));
        assert_eq!(cache.read_held(now,true,"remote:overview:altered_cursor",true,false),Err("invalid_cursor"));
        assert_eq!(cache.read_held(now,true,"remote:example/other:issued_cursor",true,false),Err("invalid_cursor"));
        let next=cache.issue("remote:overview:issued_cursor".into(),request(51),false).unwrap();cache.remote_started(now);
        cache.failed(&next);
        assert_eq!(cache.read_held(now,true,"remote:overview:issued_cursor",true,false),Ok(true),"Consumed continuation replayed its privilege");
        assert_eq!(cache.read_held(now+Duration::from_secs(60),true,"remote:overview:altered_cursor",true,false),Err("invalid_cursor"));
    }
    #[test]
    fn every_observation_kind_has_the_shared_exact_source_owner() {
        let path=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/source-owners.json");
        let owners:Value=serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        for (kind,owner) in owners.as_object().unwrap() {
            for source in ["github","codex","resource_provider","hydra"] {
                let mut frame:Value=serde_json::from_slice(&fixture(&request(52))).unwrap();
                let mut o=frame["observations"][0].clone();
                o["resource"]=serde_json::json!({"source":source,"kind":kind,"id":"fixture"});
                o["revision"]=Value::Null;o["value"]=Value::Null;o["observed_at"]=Value::Null;o["availability"]="unavailable".into();
                o["reason"]="fixture_unavailable".into();
                o["coverage"]=serde_json::json!({"state":"unavailable","scope":"fixture","returned_count":0,"total_count":null,"next_cursor":null,"reason":"fixture_unavailable"});
                frame["projects"]=serde_json::json!([]);frame["work"]=serde_json::json!([]);frame["relations"]=serde_json::json!([]);
                frame["retry_hints"]=serde_json::json!([]);frame["observations"]=serde_json::json!([o]);
                assert_eq!(ReadPayload::parse(&serde_json::to_vec(&frame).unwrap()).is_ok(),owner==source,"Foreign source impersonated {kind}");
            }
        }
    }
    #[test]
    fn same_scope_regression_cannot_discard_a_current_independent_source() {
        let mut cache=test_cache();let now=Instant::now();
        let mut value:Value=serde_json::from_slice(&fixture(&request(2))).unwrap();
        value["projects"]=serde_json::json!([]);value["work"]=serde_json::json!([]);value["relations"]=serde_json::json!([]);
        value["observations"][0]["revision"]["value"]="10".into();
        value["observations"][0]["value"]["revision"]=10.into();
        let first=cache.issue("remote".into(),request(2),false).unwrap();
        cache.accept(&first,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        value["observations"][0]["revision"]["value"]="0".into();value["request_id"]=request(3).into();
        value["observations"][0]["value"]["revision"]=0.into();
        let issue=value["observations"].as_array_mut().unwrap().iter_mut().find(|o|o["resource"]["kind"]=="issue").unwrap();
        issue["value"]["title"]="New current GitHub source".into();
        let second=cache.issue("remote".into(),request(3),false).unwrap();
        let accepted=cache.accept(&second,&serde_json::to_vec(&value).unwrap(),now)
            .expect("A per-source regression discarded a healthy GitHub observation");
        let read=serde_json::to_value(accepted.payload.as_ref()).unwrap();
        assert!(read["observations"].as_array().unwrap().iter().any(|o|o["value"]["title"]=="New current GitHub source"));
        assert!(!cache.get("remote",false,now).unwrap().stale);
    }
    #[test]
    fn explicit_v3_route_rejects_a_real_v2_payload_without_clearing_other_sources() {
        let path=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_wire.py");
        let output=Command::new("python3").arg("-I").arg(path).output().unwrap();assert!(output.status.success());
        let vectors:Value=serde_json::from_slice(&output.stdout).unwrap();
        let wire=vectors.as_array().unwrap().iter().find(|v|v["profile"]=="legacy" && v["accepted"]==true).unwrap()["wire"].as_str().unwrap();
        assert!(matches!(ReadPayload::parse(wire.as_bytes()),Ok(ReadPayload::V2(_))));
        let mut cache=test_cache();let now=Instant::now();
        let first=cache.issue("remote".into(),request(2),false).unwrap();
        cache.accept(&first,&fixture(&first.request_id),now).unwrap();
        let mut legacy:Value=serde_json::from_str(wire).unwrap();legacy["runtime"]["code_digest"]="f".repeat(64).into();
        let second=cache.issue("local".into(),request(3),false).unwrap();
        assert_eq!(cache.accept(&second,&serde_json::to_vec(&legacy).unwrap(),now).unwrap_err(),"projection_schema_mismatch");
        assert!(!cache.get("remote",false,now).unwrap().stale);
        assert!(cache.get("local",true,now).is_none());
    }
    #[test]
    fn old_success_or_failure_cannot_erase_new_settled_scope() {
        let mut cache=test_cache(); let now=Instant::now();
        let old=cache.issue("github:alpha".into(),request(2),false).unwrap();
        let latest=cache.issue("github:alpha".into(),request(3),false).unwrap();
        cache.accept(&latest,&fixture(&latest.request_id),now).unwrap();
        assert!(!cache.failed(&old));
        assert_eq!(cache.accept(&old,&fixture(&old.request_id),now).unwrap_err(),"stale_read");
        assert!(!cache.get("github:alpha",false,now).unwrap().stale);
    }
    #[test]
    fn failure_stales_only_its_scope_and_cached_reads_do_not_renew_age() {
        let mut cache=test_cache(); let now=Instant::now();
        for (scope,n) in [("github:alpha",2),("github:beta",3)] {
            let ticket=cache.issue(scope.into(),request(n),false).unwrap();
            cache.accept(&ticket,&fixture(&ticket.request_id),now).unwrap();
        }
        let bad=cache.issue("github:alpha".into(),request(4),false).unwrap(); assert!(cache.failed(&bad));
        assert!(cache.get("github:alpha",false,now).unwrap().stale);
        assert!(!cache.get("github:beta",false,now).unwrap().stale);
        assert_eq!(cache.get("github:beta",false,now+Duration::from_secs(10)).unwrap().age_ms,10_000);
        assert_eq!(cache.get("github:beta",false,now+Duration::from_secs(20)).unwrap().age_ms,20_000);
        assert!(cache.get("github:beta",false,now+Duration::from_secs(61)).unwrap().stale);
    }
    #[test]
    fn binding_clock_and_response_echo_are_explicit_fences() {
        let mut cache=test_cache(); let now=Instant::now();
        let ticket=cache.issue("local".into(),request(2),false).unwrap();
        assert_eq!(cache.accept(&ticket,&fixture(&request(3)),now).unwrap_err(),"read_binding_mismatch");
        let ticket=cache.issue("local".into(),request(4),false).unwrap();
        cache.accept(&ticket,&fixture(&ticket.request_id),now).unwrap();
        cache.clock_resumed(); assert!(cache.get("local",true,now).unwrap().stale);
        cache.binding_changed(request(5)).unwrap();
        assert!(cache.get("local",true,now).is_none());
        assert_eq!(cache.accept(&ticket,&fixture(&ticket.request_id),now).unwrap_err(),"stale_read");
    }
    #[test]
    fn detail_lru_is_bounded_and_eviction_is_not_resource_completion() {
        let mut cache=test_cache(); let now=Instant::now();
        for n in 2..20 {
            let scope=format!("detail:{n}");
            let ticket=cache.issue(scope,request(n),true).unwrap();
            cache.accept(&ticket,&fixture(&ticket.request_id),now).unwrap();
        }
        assert_eq!(cache.counts().2,16); assert!(cache.counts().1<=4_194_304);
        assert!(cache.get("detail:2",false,now).is_none());
        let current=cache.get("detail:19",false,now).unwrap();
        let value=serde_json::to_value(current.payload.as_ref()).unwrap();
        assert!(value["work"][0]["execution"]["value"].is_null());
        assert!(value["work"][0]["cleanup"]["value"].is_null());
    }
    #[test]
    fn pending_read_metadata_is_bounded_and_finished_failures_release_capacity() {
        let mut cache=test_cache();
        let mut tickets=Vec::new();
        for n in 1..=16 {tickets.push(cache.issue(format!("pending:{n}"),request(n+1),false).unwrap());}
        assert_eq!(cache.issue("overflow".into(),request(30),false).unwrap_err(),"read_capacity_held");
        assert!(cache.failed(&tickets[0]));
        assert!(cache.issue("next".into(),request(31),false).is_ok());
        assert!(!cache.failed(&tickets[0]));
    }
    #[test]
    fn serialized_cache_capacity_evicts_whole_details_before_four_mebibytes() {
        let mut cache=test_cache();let now=Instant::now();
        let mut value:Value=serde_json::from_slice(&fixture(&request(2))).unwrap();
        let original=value["observations"].as_array().unwrap().iter().find(|o|o["resource"]["kind"]=="issue").unwrap().clone();
        for n in 1..=120 {
            let mut o=original.clone();o["key"]=format!("github:101:large:{n}").into();
            o["resource"]["id"]=format!("101:{}",n+1000).into();o["value"]["number"]=(n+1000).into();
            o["value"]["description_excerpt"]="x".repeat(4096).into();o["value"]["description_truncated"]=false.into();
            value["observations"].as_array_mut().unwrap().push(o);
        }
        let mut total=0;
        for n in 2..11 {
            let ticket=cache.issue(format!("detail:{n}"),request(n),true).unwrap();
            value["request_id"]=ticket.request_id.clone().into();
            let bytes=serde_json::to_vec(&value).unwrap();assert!(bytes.len()>500_000 && bytes.len()<=1_048_576);
            total+=bytes.len();cache.accept(&ticket,&bytes,now).unwrap();
            assert!(cache.counts().1<=4_194_304);
        }
        assert!(total>4_194_304);assert!(cache.get("detail:2",false,now).is_none());
        assert!(cache.get("detail:10",false,now).is_some());assert!(cache.counts().0<9);
    }
    #[test]
    fn late_original_hint_still_holds_quota_but_cannot_replace_new_data_or_renew_on_replay() {
        let mut cache=test_cache();let now=Instant::now();
        let old=cache.issue("github:alpha".into(),request(2),false).unwrap();
        let latest=cache.issue("github:alpha".into(),request(3),false).unwrap();
        cache.accept(&latest,&fixture(&latest.request_id),now).unwrap();
        let mut value:Value=serde_json::from_slice(&fixture(&old.request_id)).unwrap();
        let mut o=value["observations"].as_array().unwrap().iter().find(|o|o["resource"]["source"]=="github").unwrap().clone();
        o["key"]="query:limited".into();o["reason"]="provider_wait".into();
        value["observations"].as_array_mut().unwrap().push(o);
        value["retry_hints"]=serde_json::json!([{"observation_key":"query:limited","scope":format!("github:registered-read:{EPOCH}"),"after_seconds":3600,"basis":"provider"}]);
        let bytes=serde_json::to_vec(&value).unwrap();
        assert_eq!(cache.accept(&old,&bytes,now).unwrap_err(),"stale_read");
        assert_eq!(cache.remote_wait(now,true),Ok(3600));
        assert_eq!(cache.get("github:alpha",false,now).unwrap().sequence,latest.sequence);
        assert_eq!(cache.accept(&old,&bytes,now+Duration::from_secs(100)).unwrap_err(),"stale_read");
        assert_eq!(cache.remote_wait(now+Duration::from_secs(100),true),Ok(3500));
        cache.clock_resumed();assert_eq!(cache.remote_wait(now+Duration::from_secs(100),true),Ok(3500));
    }
    #[test]
    fn raw_cache_preserves_full_decimal_tokens_for_the_source_aware_consumer() {
        let mut cache=test_cache();let now=Instant::now();
        let bytes=fixture(&request(2));let mut value:Value=serde_json::from_slice(&bytes).unwrap();
        value["projects"]=serde_json::json!([]);value["work"]=serde_json::json!([]);value["relations"]=serde_json::json!([]);
        let high="1".to_owned()+&"0".repeat(200);let low="9".repeat(200);
        value["observations"][0]["key"]="hydra:counter:ownership".into();
        value["observations"][0]["resource"]=serde_json::json!({"source":"hydra","kind":"ownership","id":"fixture-counter"});
        value["observations"][0]["value"]=serde_json::json!({"state":"free","scope_digest":null,"step_nonce":null});
        value["observations"][0]["revision"]["value"]=high.clone().into();
        let ticket=cache.issue("local".into(),request(2),false).unwrap();
        cache.accept(&ticket,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        value["observations"][0]["revision"]["value"]=low.clone().into();value["request_id"]=request(3).into();
        let ticket=cache.issue("local".into(),request(3),false).unwrap();
        cache.accept(&ticket,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        let retained=cache.get("local",true,now).unwrap();assert!(!retained.stale);
        let retained=serde_json::to_value(retained.payload.as_ref()).unwrap();
        assert_eq!(retained["observations"][0]["revision"]["value"],low);
    }
    #[test]
    fn older_shared_metadata_in_an_independent_read_does_not_discard_new_github_data() {
        let mut cache=test_cache();let now=Instant::now();
        let remote=cache.issue("remote".into(),request(2),false).unwrap();
        let local=cache.issue("local".into(),request(3),false).unwrap();
        let mut value:Value=serde_json::from_slice(&fixture(&local.request_id)).unwrap();
        value["projects"]=serde_json::json!([]);value["work"]=serde_json::json!([]);value["relations"]=serde_json::json!([]);
        value["observations"][0]["revision"]["value"]="8".into();
        value["observations"][0]["value"]["revision"]=8.into();
        cache.accept(&local,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        let remote=cache.accept(&remote,&fixture(&remote.request_id),now).expect("An older admission sample discarded an independent GitHub read");
        let remote=serde_json::to_value(remote.payload.as_ref()).unwrap();
        assert_eq!(remote["projects"].as_array().unwrap().len(),2);
        assert!(remote["observations"].as_array().unwrap().iter().any(|o|o["resource"]["source"]=="github" && o["availability"]=="current"));
        let local=cache.get("local",true,now).unwrap();assert!(!local.stale);
        let local=serde_json::to_value(local.payload.as_ref()).unwrap();
        assert_eq!(local["observations"][0]["revision"]["value"],"8");
    }
    #[test]
    fn current_runtime_change_recovers_a_generation_without_late_rollback_or_quota_reset() {
        let mut cache=test_cache();let now=Instant::now();
        let first=cache.issue("remote".into(),request(2),false).unwrap();
        let mut value:Value=serde_json::from_slice(&fixture(&first.request_id)).unwrap();
        let mut o=value["observations"].as_array().unwrap().iter().find(|o|o["resource"]["source"]=="github").unwrap().clone();
        o["key"]="query:runtime".into();o["reason"]="provider_wait".into();
        value["observations"].as_array_mut().unwrap().push(o);
        value["retry_hints"]=serde_json::json!([{"observation_key":"query:runtime","scope":format!("github:registered-read:{EPOCH}"),"after_seconds":600,"basis":"provider"}]);
        cache.accept(&first,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        let old=cache.issue("old-independent".into(),request(3),false).unwrap();
        let fresh=cache.issue("local".into(),request(4),false).unwrap();
        let mut value:Value=serde_json::from_slice(&fixture(&fresh.request_id)).unwrap();
        value["runtime"]["code_digest"]="f".repeat(64).into();
        let accepted=cache.accept(&fresh,&serde_json::to_vec(&value).unwrap(),now).expect("A legitimate runtime update permanently poisoned the cache");
        assert_eq!(serde_json::to_value(accepted.payload.as_ref()).unwrap()["runtime"]["code_digest"],"f".repeat(64));
        assert!(cache.get("remote",false,now).is_none());
        assert_eq!(cache.accept(&old,&fixture(&old.request_id),now).unwrap_err(),"stale_read");
        assert!(!cache.get("local",true,now).unwrap().stale);
        assert_eq!(cache.remote_wait(now,true),Ok(600));
    }
    #[test]
    fn local_generation_replacement_releases_old_remote_poll_floor() {
        let mut cache=test_cache();let now=Instant::now();
        let first=cache.issue("remote".into(),request(2),false).unwrap();
        cache.remote_started(now);cache.accept(&first,&fixture(&first.request_id),now).unwrap();
        let started=now+Duration::from_secs(1);
        let local=cache.issue("local".into(),request(3),false).unwrap();cache.local_started(started);
        let mut value:Value=serde_json::from_slice(&fixture(&local.request_id)).unwrap();
        value["runtime"]["code_digest"]="f".repeat(64).into();
        cache.accept(&local,&serde_json::to_vec(&value).unwrap(),started).unwrap();
        assert!(cache.get("remote",false,started).is_none());
        assert_eq!(cache.remote_wait(started,false),Ok(0),"An invalidated generation held an empty remote cache");
        assert!(cache.local_wait(started+Duration::from_secs(4)));
        assert!(!cache.local_wait(started+Duration::from_secs(5)));
    }
    #[test]
    fn remote_generation_replacement_retains_its_own_start_but_not_old_local_floor() {
        let mut cache=test_cache();let now=Instant::now();
        let first=cache.issue("local".into(),request(2),false).unwrap();
        cache.local_started(now);cache.accept(&first,&fixture(&first.request_id),now).unwrap();
        let started=now+Duration::from_secs(1);
        let remote=cache.issue("remote".into(),request(3),false).unwrap();cache.remote_started(started);
        let mut value:Value=serde_json::from_slice(&fixture(&remote.request_id)).unwrap();
        value["runtime"]["code_digest"]="f".repeat(64).into();
        cache.accept(&remote,&serde_json::to_vec(&value).unwrap(),started+Duration::from_secs(1)).unwrap();
        assert!(!cache.local_wait(started+Duration::from_secs(1)),"A new generation retained the unrelated old local poll");
        assert_eq!(cache.remote_wait(started+Duration::from_secs(1),false),Ok(59));
        assert_eq!(cache.remote_wait(started+Duration::from_secs(60),false),Ok(0));
    }
    #[test]
    fn late_old_runtime_hint_holds_the_same_connection_without_restoring_old_data() {
        let mut cache=test_cache();let now=Instant::now();
        let first=cache.issue("remote".into(),request(2),false).unwrap();
        cache.accept(&first,&fixture(&first.request_id),now).unwrap();
        let old=cache.issue("old-remote".into(),request(3),false).unwrap();
        let fresh=cache.issue("local".into(),request(4),false).unwrap();
        let mut next:Value=serde_json::from_slice(&fixture(&fresh.request_id)).unwrap();
        next["runtime"]["code_digest"]="f".repeat(64).into();
        cache.accept(&fresh,&serde_json::to_vec(&next).unwrap(),now).unwrap();
        let mut limited:Value=serde_json::from_slice(&fixture(&old.request_id)).unwrap();
        let mut o=limited["observations"].as_array().unwrap().iter().find(|o|o["resource"]["source"]=="github").unwrap().clone();
        o["key"]="query:late-runtime".into();o["reason"]="provider_wait".into();
        limited["observations"].as_array_mut().unwrap().push(o);
        limited["retry_hints"]=serde_json::json!([{"observation_key":"query:late-runtime","scope":format!("github:registered-read:{EPOCH}"),"after_seconds":600,"basis":"provider"}]);
        let bytes=serde_json::to_vec(&limited).unwrap();
        assert_eq!(cache.accept(&old,&bytes,now).unwrap_err(),"stale_read");
        assert_eq!(cache.remote_wait(now,true),Ok(600));
        assert_eq!(cache.accept(&old,&bytes,now+Duration::from_secs(100)).unwrap_err(),"stale_read");
        assert_eq!(cache.remote_wait(now+Duration::from_secs(100),true),Ok(500));
        let retained=serde_json::to_value(cache.get("local",true,now).unwrap().payload.as_ref()).unwrap();
        assert_eq!(retained["runtime"]["code_digest"],"f".repeat(64));
    }
    #[test]
    fn p12_review_cache_retains_valid_incomplete_runtime_observations() {
        let now=Instant::now();
        for missing in ["code_digest","config_digest","control_binding_digest","version"] {
            let mut cache=test_cache();let ticket=cache.issue("local:overview:".into(),request(930),false).unwrap();
            let mut frame:Value=serde_json::from_slice(&fixture(&request(930))).unwrap();
            frame["runtime"][missing]=Value::Null;
            frame["runtime"]["identity_reason"]=Value::String("runtime_source_unavailable".into());
            if missing=="control_binding_digest" {
                for group in ["projects","work"] {
                    for row in frame[group].as_array_mut().unwrap() {
                        row["admission"]["value"]=Value::Null;
                        row["admission"]["reason"]="admission_binding_unavailable".into();
                    }
                }
            }
            let identity:RuntimeIdentity=serde_json::from_value(frame["runtime"].clone()).unwrap();
            assert!(identity.valid());assert!(!identity.known());
            let bytes=serde_json::to_vec(&frame).unwrap();
            let result=cache.accept(&ticket,&bytes,now);
            assert!(result.is_ok(),"valid incomplete runtime discarded: {missing}");
            let accepted=result.unwrap();let retained=serde_json::to_value(&accepted).unwrap();
            assert_eq!(retained["payload"],frame);assert!(!frame["projects"].as_array().unwrap().is_empty());
            let cached=cache.get("local:overview:",true,now+Duration::from_secs(2)).unwrap();
            assert_eq!(serde_json::to_value(cached).unwrap()["payload"],frame);
        }
    }
    #[test]
    fn p12_review_incomplete_runtime_preserves_generation_and_validation_fences() {
        let now=Instant::now();let mut cache=test_cache();
        let first=cache.issue("local:first:".into(),request(931),false).unwrap();
        let late=cache.issue("local:late:".into(),request(932),false).unwrap();
        let mut incomplete:Value=serde_json::from_slice(&fixture(&request(931))).unwrap();
        incomplete["runtime"]["code_digest"]=Value::Null;
        incomplete["runtime"]["identity_reason"]=Value::String("runtime_source_unavailable".into());
        assert!(cache.accept(&first,&serde_json::to_vec(&incomplete).unwrap(),now).is_ok());
        let next=cache.issue("local:next:".into(),request(933),false).unwrap();
        assert!(cache.accept(&next,&fixture(&request(933)),now).is_ok());
        assert!(cache.get("local:first:",true,now).is_none());
        incomplete["request_id"]=Value::String(request(932));
        assert_eq!(cache.accept(&late,&serde_json::to_vec(&incomplete).unwrap(),now).unwrap_err(),"stale_read");
        assert!(cache.get("local:next:",true,now).is_some());
        let bad=cache.issue("local:bad:".into(),request(934),false).unwrap();
        let mut malformed:Value=serde_json::from_slice(&fixture(&request(934))).unwrap();
        malformed["runtime"]["code_digest"]=Value::String("invalid".into());
        assert!(cache.accept(&bad,&serde_json::to_vec(&malformed).unwrap(),now).is_err());
        assert!(cache.get("local:next:",true,now).is_some());
    }


    #[test]
    fn repository_identity_pins_survive_credentials_without_reusing_remote_facts() {
        let mut cache=test_cache();let now=Instant::now();
        cache.context_changed(Some("connection:alpha".into())).unwrap();
        let local=cache.issue("local:overview:".into(),request(201),false).unwrap();
        cache.accept(&local,&fixture(&local.request_id),now).unwrap();
        let remote=cache.issue("remote:overview:".into(),request(202),false).unwrap();cache.remote_started(now);
        cache.accept(&remote,&fixture(&remote.request_id),now).unwrap();
        let pins=cache.repository_binding_hints().unwrap();assert!(pins.contains("example/alpha"));
        let old=cache.issue("remote:overview:".into(),request(203),false).unwrap();
        cache.context_changed(Some("connection:beta".into())).unwrap();
        assert_eq!(cache.repository_binding_hints().unwrap(),pins,"Credential rotation discarded stable repository identity");
        assert!(cache.get("remote:overview:",false,now).is_none(),"A new credential inherited remote facts");
        assert!(!cache.get("local:overview:",true,now).unwrap().stale);
        assert_eq!(cache.accept(&old,&fixture(&old.request_id),now).unwrap_err(),"stale_read");
        assert_eq!(cache.repository_binding_hints().unwrap(),pins);
        cache.context_changed(None).unwrap();
        assert_eq!(cache.repository_binding_hints().unwrap(),pins,"Sign-out forgot identity while access was unavailable");
        assert_eq!(cache.read_held(now,true,"remote:overview:",false,true),Err("read_context_unavailable"));
        cache.context_changed(Some("connection:beta".into())).unwrap();
        let fresh=cache.issue("remote:overview:".into(),request(204),false).unwrap();
        cache.accept(&fresh,&fixture(&fresh.request_id),now).unwrap();
        assert_eq!(cache.get("remote:overview:",false,now).unwrap().read_context.scope.as_deref(),Some("connection:beta"));
    }
}
