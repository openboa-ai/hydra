//! Read-only connection backoff. This is neither admission nor effect authority.
use crate::projection::ReadPayload;
use serde_json::Value;
use std::{collections::HashMap, time::{Duration, Instant}};

const FALLBACK: [u64; 5] = [60, 120, 240, 480, 900];
const MAX_SCOPES: usize = 256;
const MAX_FAILURES: usize = 512;

#[derive(Default)]
struct Gate {
    failures: HashMap<String, u32>,
    wait: Option<(Instant, Duration)>,
}
#[derive(Default)]
pub struct ReadPolicy {
    gates: HashMap<(String, String), Gate>,
    overflow: bool,
}

fn remaining(wait: Option<(Instant, Duration)>, now: Instant) -> Duration {
    wait.map(|(start, duration)| duration.saturating_sub(now.saturating_duration_since(start)))
        .unwrap_or(Duration::ZERO)
}
fn successful(o: &Value) -> bool {
    o["availability"] == "current" && o["coverage"]["state"] == "complete" &&
        o["reason"] != "provider_wait" && o["reason"] != "rate_limited"
}
impl ReadPolicy {
    // Called once for a newly received validated response. Cache replay never calls it.
    pub fn observe(&mut self, payload: &ReadPayload, now: Instant, recover: bool) {
        let value = serde_json::to_value(payload).expect("sealed read serializes");
        if value["schema_version"] != 3 { return; }
        let observations = value["observations"].as_array().expect("validated observations");
        for ((source, _), gate) in &mut self.gates {
            for observation in observations {
                if recover && observation["resource"]["source"] == *source && successful(observation) {
                    gate.failures.remove(observation["key"].as_str().unwrap());
                }
            }
        }
        for hint in value["retry_hints"].as_array().unwrap() {
            let key = hint["observation_key"].as_str().unwrap();
            let observation = observations.iter().find(|o| o["key"] == key).unwrap();
            let source = observation["resource"]["source"].as_str().unwrap().to_owned();
            let scope = hint["scope"].as_str().unwrap().to_owned();
            let identity = (source, scope);
            if !self.gates.contains_key(&identity) && self.gates.len() >= MAX_SCOPES {
                self.overflow = true; continue;
            }
            let gate = self.gates.entry(identity).or_default();
            let mut seconds = hint["after_seconds"].as_u64().unwrap();
            if hint["basis"] == "fallback" {
                if !gate.failures.contains_key(key) && gate.failures.len() >= MAX_FAILURES {
                    self.overflow = true; continue;
                }
                let count = gate.failures.entry(key.to_owned()).or_default();
                *count = count.saturating_add(1);
                seconds = seconds.max(FALLBACK[(*count as usize).saturating_sub(1).min(4)]);
            }
            let wait = Duration::from_secs(seconds);
            if wait > remaining(gate.wait, now) { gate.wait = Some((now, wait)); }
        }
    }
    pub fn wait_seconds(&self, source: &str, scope: &str, now: Instant, explicit_recovery: bool) -> Result<u64, &'static str> {
        if self.overflow { return Err("read_policy_capacity_held"); }
        let Some(gate) = self.gates.get(&(source.to_owned(), scope.to_owned())) else { return Ok(0); };
        let wait = remaining(gate.wait, now);
        if !wait.is_zero() { return Ok(wait.as_secs().saturating_add(u64::from(wait.subsec_nanos() != 0))); }
        // Initial failure followed by five failed automatic retries exhausts the lane.
        if !explicit_recovery && gate.failures.values().any(|count| *count > 5) {
            return Err("explicit_recovery_required");
        }
        Ok(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{path::PathBuf, process::Command};
    fn frame(seconds: u64, basis: &str, query: &str) -> ReadPayload {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_wire.py");
        let output = Command::new("python3").arg("-I").arg(path).output().unwrap();
        assert!(output.status.success());
        let rows: Value = serde_json::from_slice(&output.stdout).unwrap();
        let mut value: Value = serde_json::from_str(rows[0]["wire"].as_str().unwrap()).unwrap();
        let mut o = value["observations"][0].clone();
        o["key"] = query.into(); o["reason"] = "provider_wait".into();
        value["observations"].as_array_mut().unwrap().push(o);
        value["retry_hints"] = serde_json::json!([{"observation_key":query,"scope":"connection:example", "after_seconds":seconds,"basis":basis}]);
        ReadPayload::parse(&serde_json::to_vec(&value).unwrap()).unwrap()
    }
    #[test]
    fn provider_wait_is_never_capped_by_fallback_or_unrelated_recovery() {
        let now = Instant::now(); let mut p = ReadPolicy::default();
        p.observe(&frame(3600,"provider","query:a"),now,true);
        p.observe(&frame(60,"fallback","query:b"),now+Duration::from_secs(10),true);
        assert_eq!(p.wait_seconds("hydra","connection:example",now+Duration::from_secs(20),true),Ok(3580));
        assert_eq!(p.wait_seconds("github","connection:example",now,false),Ok(0));
        // A backwards clock cannot erase the wait.
        assert_eq!(p.wait_seconds("hydra","connection:example",now-Duration::from_secs(10),true),Ok(3600));
    }
    #[test]
    fn fallback_increases_and_requires_explicit_recovery_after_five_retries() {
        let mut p = ReadPolicy::default(); let mut now = Instant::now();
        for seconds in [60,120,240,480,900,900] {
            p.observe(&frame(60,"fallback","query:a"),now,true);
            assert_eq!(p.wait_seconds("hydra","connection:example",now,true),Ok(seconds));
            now += Duration::from_secs(seconds);
        }
        assert_eq!(p.wait_seconds("hydra","connection:example",now,false),Err("explicit_recovery_required"));
        assert_eq!(p.wait_seconds("hydra","connection:example",now,true),Ok(0));
        // Recovery of the exact failed query resets its counter; another query does not.
        let value=frame(0,"provider","query:b"); p.observe(&value,now,true);
        assert_eq!(p.wait_seconds("hydra","connection:example",now,false),Err("explicit_recovery_required"));
        let mut value=serde_json::to_value(&value).unwrap();
        let o=value["observations"].as_array_mut().unwrap().last_mut().unwrap();
        o["key"]="query:a".into(); o["reason"]=Value::Null; value["retry_hints"]=serde_json::json!([]);
        let value=ReadPayload::parse(&serde_json::to_vec(&value).unwrap()).unwrap();
        p.observe(&value,now,true);
        assert_eq!(p.wait_seconds("hydra","connection:example",now,false),Ok(0));
    }
    #[test]
    fn known_provider_zero_is_not_a_missing_header_fallback() {
        let now=Instant::now();let mut p=ReadPolicy::default();
        p.observe(&frame(0,"provider","query:a"),now,true);
        assert_eq!(p.wait_seconds("hydra","connection:example",now,false),Ok(0));
        p.observe(&frame(60,"fallback","query:a"),now,true);
        assert_eq!(p.wait_seconds("hydra","connection:example",now,false),Ok(60));
    }
}
