//! Memory-only validated read cache. Eviction never retires work or resources.
use crate::projection::ReadPayload;
use crate::projection_policy::ReadPolicy;
use crate::protocol::RuntimeIdentity;
use serde::{Serialize, Serializer};
use serde_json::Value;
use std::{collections::{HashMap, VecDeque}, sync::Arc, time::{Duration, Instant}};

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
}
#[derive(Clone, Debug, Serialize)]
pub struct CachedRead {
    #[serde(serialize_with = "serialize_payload")]
    pub payload: Arc<ReadPayload>,
    pub age_ms: u64,
    pub cached: bool,
    pub stale: bool,
    pub sequence: u64,
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
    ledger:VecDeque<(ReadTicket,bool)>,
    policy:ReadPolicy,
    remote_started:Option<Instant>,
    local_started:Option<Instant>,
}
fn uuid(value:&str)->bool {
    value.len()==36 && value.bytes().enumerate().all(|(i,c)| if [8,13,18,23].contains(&i) {
        c==b'-'
    } else {c.is_ascii_digit() || (b'a'..=b'f').contains(&c)})
}
fn runtime_key(payload:&ReadPayload)->Result<Value,&'static str> {
    let value=serde_json::to_value(payload).map_err(|_|"invalid_response")?;
    let identity:RuntimeIdentity=serde_json::from_value(value["runtime"].clone()).map_err(|_|"invalid_response")?;
    if !identity.known() {return Err("runtime_identity_unavailable");}
    Ok(serde_json::json!({"version":identity.version,"code_digest":identity.code_digest,
        "config_digest":identity.config_digest,"control_binding_digest":identity.control_binding_digest}))
}
impl ReadCache {
    pub fn new(epoch:String)->Result<Self,&'static str> {
        if !uuid(&epoch) {return Err("binding_invalid");}
        Ok(Self {epoch,runtime:None,next:0,orders:HashMap::new(),entries:HashMap::new(),
            lru:VecDeque::new(),bytes:0,last_clock:None,ledger:VecDeque::new(),policy:ReadPolicy::default(),remote_started:None,local_started:None})
    }
    pub fn binding_changed(&mut self,epoch:String)->Result<(),&'static str> {
        if !uuid(&epoch) || epoch==self.epoch {return Err("binding_invalid");}
        self.epoch=epoch; self.runtime=None; self.orders.clear(); self.entries.clear();
        self.lru.clear(); self.bytes=0; self.last_clock=None; self.ledger.clear();
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
        let ticket=ReadTicket{scope,epoch:self.epoch.clone(),request_id,sequence,detail};
        self.ledger.push_back((ticket.clone(),false));
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
        let original=self.ledger.iter().any(|(t,seen)|!seen && t.sequence==ticket.sequence &&
            t.request_id==ticket.request_id && t.scope==ticket.scope && t.epoch==ticket.epoch);
        if ticket.epoch!=self.epoch || !original {return Err("stale_read");}
        let payload=match ReadPayload::parse(bytes) {
            Ok(value)=>value,
            Err(reason)=>{self.failed(ticket);return Err(reason);}
        };
        let value=serde_json::to_value(&payload).map_err(|_|"invalid_response")?;
        if value["schema_version"]==3 && (value["binding_epoch"]!=ticket.epoch || value["request_id"]!=ticket.request_id) {
            self.failed(ticket); return Err("read_binding_mismatch");
        }
        let key=match runtime_key(&payload) {
            Ok(value)=>value,
            Err(reason)=>{self.failed(ticket);return Err(reason);}
        };
        if self.runtime.as_ref().is_some_and(|old|old!=&key) {
            self.clock_resumed(); self.failed(ticket); return Err("runtime_binding_changed");
        }
        let (_,seen)=self.ledger.iter_mut().find(|(t,_)|t.sequence==ticket.sequence).unwrap();
        *seen=true;
        let regressed=self.entries.values().any(|entry|payload.regresses_from(entry.payload.as_ref()));
        self.policy.observe(&payload,now,current && !regressed);
        if !current {return Err("stale_read");}
        if regressed {self.failed(ticket);return Err("source_revision_regressed");}
        let size=serde_json::to_vec(&payload).map_err(|_|"invalid_response")?.len();
        if size>1_048_576 {self.failed(ticket);return Err("response_limit");}
        let now=self.clock(now);
        self.runtime=Some(key);
        self.orders.get_mut(&ticket.scope).unwrap().settled=ticket.sequence;
        self.remove(&ticket.scope);
        let payload=Arc::new(payload);
        self.entries.insert(ticket.scope.clone(),Entry{payload:payload.clone(),received:now,
            bytes:size,detail:ticket.detail,stale:false,sequence:ticket.sequence});
        self.bytes+=size; self.touch(&ticket.scope); self.bound();
        Ok(CachedRead{payload,age_ms:0,cached:false,stale:false,sequence:ticket.sequence})
    }
    pub fn get(&mut self,scope:&str,local:bool,now:Instant)->Option<CachedRead> {
        let now=self.clock(now);
        let entry=self.entries.get(scope)?;
        let age=now.saturating_duration_since(entry.received);
        let result=CachedRead{payload:entry.payload.clone(),age_ms:age.as_millis().min(MAX_SEQUENCE as u128) as u64,
            cached:true,stale:entry.stale || age>=Duration::from_secs(if local {15}else{60}),sequence:entry.sequence};
        self.touch(scope); Some(result)
    }
    pub fn epoch(&self)->&str {&self.epoch}
    pub fn remote_wait(&self,now:Instant,explicit_recovery:bool)->Result<u64,&'static str> {
        let quota=self.policy.wait_seconds("github",&format!("github:registered-read:{}",self.epoch),now,explicit_recovery)?;
        let poll=self.remote_started.map(|start|Duration::from_secs(60).saturating_sub(now.saturating_duration_since(start)))
            .unwrap_or(Duration::ZERO);
        Ok(quota.max(poll.as_secs()+u64::from(poll.subsec_nanos()!=0)))
    }
    pub fn remote_started(&mut self,now:Instant) {self.remote_started=Some(now);}
    pub fn local_wait(&self,now:Instant)->bool {
        self.local_started.is_some_and(|start|now.saturating_duration_since(start)<Duration::from_secs(5))
    }
    pub fn local_started(&mut self,now:Instant) {self.local_started=Some(now);}

    fn touch(&mut self,scope:&str) {
        self.lru.retain(|key|key!=scope); self.lru.push_back(scope.to_owned());
    }
    fn remove(&mut self,scope:&str) {
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
    fn old_success_or_failure_cannot_erase_new_settled_scope() {
        let mut cache=ReadCache::new(EPOCH.into()).unwrap(); let now=Instant::now();
        let old=cache.issue("github:alpha".into(),request(2),false).unwrap();
        let latest=cache.issue("github:alpha".into(),request(3),false).unwrap();
        cache.accept(&latest,&fixture(&latest.request_id),now).unwrap();
        assert!(!cache.failed(&old));
        assert_eq!(cache.accept(&old,&fixture(&old.request_id),now).unwrap_err(),"stale_read");
        assert!(!cache.get("github:alpha",false,now).unwrap().stale);
    }
    #[test]
    fn failure_stales_only_its_scope_and_cached_reads_do_not_renew_age() {
        let mut cache=ReadCache::new(EPOCH.into()).unwrap(); let now=Instant::now();
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
        let mut cache=ReadCache::new(EPOCH.into()).unwrap(); let now=Instant::now();
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
        let mut cache=ReadCache::new(EPOCH.into()).unwrap(); let now=Instant::now();
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
        let mut cache=ReadCache::new(EPOCH.into()).unwrap();
        let mut tickets=Vec::new();
        for n in 1..=16 {tickets.push(cache.issue(format!("pending:{n}"),request(n+1),false).unwrap());}
        assert_eq!(cache.issue("overflow".into(),request(30),false).unwrap_err(),"read_capacity_held");
        assert!(cache.failed(&tickets[0]));
        assert!(cache.issue("next".into(),request(31),false).is_ok());
        assert!(!cache.failed(&tickets[0]));
    }
    #[test]
    fn serialized_cache_capacity_evicts_whole_details_before_four_mebibytes() {
        let mut cache=ReadCache::new(EPOCH.into()).unwrap();let now=Instant::now();
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
        let mut cache=ReadCache::new(EPOCH.into()).unwrap();let now=Instant::now();
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
    fn monotonic_revisions_are_compared_as_unbounded_decimal_strings_before_cache_replacement() {
        let mut cache=ReadCache::new(EPOCH.into()).unwrap();let now=Instant::now();
        let bytes=fixture(&request(2));let mut value:Value=serde_json::from_slice(&bytes).unwrap();
        value["projects"]=serde_json::json!([]);value["work"]=serde_json::json!([]);value["relations"]=serde_json::json!([]);
        let high="1".to_owned()+&"0".repeat(200);let low="9".repeat(200);
        value["observations"][0]["revision"]["value"]=high.clone().into();
        let ticket=cache.issue("local".into(),request(2),false).unwrap();
        cache.accept(&ticket,&serde_json::to_vec(&value).unwrap(),now).unwrap();
        value["observations"][0]["revision"]["value"]=low.into();value["request_id"]=request(3).into();
        let ticket=cache.issue("local".into(),request(3),false).unwrap();
        assert_eq!(cache.accept(&ticket,&serde_json::to_vec(&value).unwrap(),now).unwrap_err(),"source_revision_regressed");
        let retained=cache.get("local",true,now).unwrap();assert!(retained.stale);
        let retained=serde_json::to_value(retained.payload.as_ref()).unwrap();
        assert_eq!(retained["observations"][0]["revision"]["value"],high);
    }
}
