use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const MAX_OUTPUT: usize = 1_048_576;
const MAX_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    Running,
    Paused,
    Stopped,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Gate {
    Allowed,
    Blocked,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionState {
    Idle,
    Running,
    Pausing,
    Paused,
    Stopping,
    Stopped,
    Unknown,
    Blocked,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Execution {
    pub state: ExecutionState,
    pub active_count: Option<u64>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Coverage {
    pub state: CoverageState,
    pub reason: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageState {
    Unverified,
    Confirmed,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Remote {
    pub state: RemoteState,
    pub observed_at: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RemoteState {
    NotRequested,
    Fresh,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Work {
    pub issue: u64,
    pub phase: Option<String>,
    pub wait_reason: Option<String>,
    pub next_action: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Links {
    pub issue: Option<String>,
    pub pr: Option<String>,
    pub chat: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Project {
    pub repository: String,
    pub override_mode: Option<Mode>,
    pub effective_mode: Mode,
    pub gate_status: Gate,
    pub gate_reason: Option<String>,
    pub execution: Execution,
    pub work: Vec<Work>,
    pub links: Links,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Start,
    Pause,
    Resume,
    Stop,
}

impl Action {
    pub fn argument(self) -> &'static str {
        match self {
            Self::Start => "start",
            Self::Pause => "pause",
            Self::Resume => "resume",
            Self::Stop => "stop",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "scope", rename_all = "snake_case")]
pub enum Target {
    All,
    Project { repository: String },
}

impl<'de> Deserialize<'de> for Target {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireTarget {
            scope: String,
            #[serde(default, deserialize_with = "present_repository")]
            repository: Option<String>,
        }

        fn present_repository<'de, D: serde::Deserializer<'de>>(
            deserializer: D,
        ) -> Result<Option<String>, D::Error> {
            // Missing is distinct from present-null: a supplied repository must
            // be a string, and must never silently become the host target.
            String::deserialize(deserializer).map(Some)
        }

        let wire = WireTarget::deserialize(deserializer)?;
        match (wire.scope.as_str(), wire.repository) {
            ("all", None) => Ok(Self::All),
            ("project", Some(repository)) if repository_valid(&repository) => {
                Ok(Self::Project { repository })
            }
            _ => Err(serde::de::Error::custom("invalid operating target")),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub action: Action,
    pub target: String,
    pub status: RequestState,
    pub revision: Option<u64>,
    pub reason: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestState {
    Applied,
    Held,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeControl {
    Unsupported,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub schema_version: u64,
    pub observed_at: String,
    pub host_alias: String,
    pub revision: Option<u64>,
    pub global_mode: Mode,
    pub gate_status: Gate,
    pub gate_reason: Option<String>,
    pub native_turn_control: NativeControl,
    pub execution: Execution,
    pub coverage: Coverage,
    pub can_quit: bool,
    pub quit_reason: Option<String>,
    pub remote: Remote,
    pub projects: Vec<Project>,
    pub request: Option<Request>,
}

pub fn repository_valid(repository: &str) -> bool {
    let Some((owner, name)) = repository.split_once('/') else {
        return false;
    };
    !owner.is_empty()
        && owner.len() <= 39
        && !name.is_empty()
        && name.len() <= 100
        && (owner.as_bytes()[0].is_ascii_lowercase() || owner.as_bytes()[0].is_ascii_digit())
        && owner
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
        && name
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c))
        && name != "."
        && name != ".."
}

fn bounded_text(value: &Option<String>) -> bool {
    value.as_ref().is_none_or(|text| text.len() <= 4096)
}
fn valid_execution(value: &Execution) -> bool {
    value.active_count.is_none_or(|count| count <= MAX_INTEGER) && bounded_text(&value.reason)
}

fn timestamp_millis(value: &str) -> Option<i64> {
    if value.len() > 64 || !value.is_ascii() {
        return None;
    }
    chrono::DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|date| date.timestamp_millis())
}

impl Snapshot {
    pub fn parse(bytes: &[u8]) -> Result<Self, &'static str> {
        if bytes.len() > MAX_OUTPUT {
            return Err("backend_output_too_large");
        }
        let value: Self = serde_json::from_slice(bytes).map_err(|_| "backend_response_invalid")?;
        if value.schema_version != 1
            || timestamp_millis(&value.observed_at).is_none()
            || value.host_alias.is_empty()
            || value.host_alias.len() > 255
            || value.revision.is_some_and(|n| n > MAX_INTEGER)
            || value.projects.len() > 1024
            || !valid_execution(&value.execution)
            || !bounded_text(&value.gate_reason)
            || !bounded_text(&value.quit_reason)
            || !bounded_text(&value.coverage.reason)
            || value
                .remote
                .observed_at
                .as_ref()
                .is_some_and(|s| timestamp_millis(s).is_none())
        {
            return Err("backend_response_invalid");
        }
        let mut seen = BTreeSet::new();
        for project in &value.projects {
            if !repository_valid(&project.repository)
                || !seen.insert(&project.repository)
                || project.override_mode == Some(Mode::Unknown)
                || project.work.len() > 1024
                || !valid_execution(&project.execution)
                || !bounded_text(&project.gate_reason)
                || !bounded_text(&project.links.issue)
                || !bounded_text(&project.links.pr)
                || !bounded_text(&project.links.chat)
                || project.work.iter().any(|work| {
                    work.issue == 0
                        || work.issue > MAX_INTEGER
                        || !bounded_text(&work.phase)
                        || !bounded_text(&work.wait_reason)
                        || !bounded_text(&work.next_action)
                })
            {
                return Err("backend_response_invalid");
            }
        }
        if let Some(request) = &value.request {
            if (request.target != "all" && !repository_valid(&request.target))
                || request.revision.is_some_and(|n| n > MAX_INTEGER)
                || !bounded_text(&request.reason)
            {
                return Err("backend_response_invalid");
            }
        }
        Ok(value)
    }

    pub fn project(&self, repository: &str) -> Option<&Project> {
        self.projects
            .iter()
            .find(|project| project.repository == repository)
    }

    pub fn same_targets(&self, other: &Self) -> bool {
        self.projects
            .iter()
            .map(|project| &project.repository)
            .collect::<BTreeSet<_>>()
            == other
                .projects
                .iter()
                .map(|project| &project.repository)
                .collect::<BTreeSet<_>>()
    }

    pub fn acknowledges(&self, action: Action, target: &Target) -> bool {
        let Some(request) = &self.request else {
            return false;
        };
        let target_name = match target {
            Target::All => "all",
            Target::Project { repository } => repository,
        };
        if request.action != action || request.target != target_name {
            return false;
        }
        if request.status != RequestState::Applied {
            return true;
        }
        let desired = match action {
            Action::Start | Action::Resume => Mode::Running,
            Action::Pause => Mode::Paused,
            Action::Stop => Mode::Stopped,
        };
        request.revision.is_some()
            && request.revision == self.revision
            && match target {
                Target::All => self.global_mode == desired,
                Target::Project { repository } => self
                    .project(repository)
                    .is_some_and(|project| project.override_mode == Some(desired)),
            }
    }

    pub fn permits_quit(&self) -> bool {
        let Ok(now) = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) else {
            return false;
        };
        let Ok(now) = i64::try_from(now.as_millis()) else {
            return false;
        };
        self.permits_quit_at(now)
    }

    fn permits_quit_at(&self, now: i64) -> bool {
        let Some(observed) = timestamp_millis(&self.observed_at) else {
            return false;
        };
        let remote = self
            .remote
            .observed_at
            .as_deref()
            .and_then(timestamp_millis);
        self.can_quit
            && self
                .revision
                .is_some_and(|revision| revision > 0 && revision <= MAX_INTEGER)
            && self.request.is_none()
            && self.remote.state == RemoteState::Fresh
            && remote == Some(observed)
            && observed >= now.saturating_sub(15_000)
            && observed <= now.saturating_add(5_000)
            && self.quit_reason.is_none()
            && self.execution.reason.is_none()
            && self.coverage.reason.is_none()
            && !self.projects.is_empty()
            && self.global_mode == Mode::Stopped
            && self.gate_status == Gate::Blocked
            && self.coverage.state == CoverageState::Confirmed
            && self.execution.active_count == Some(0)
            && matches!(
                self.execution.state,
                ExecutionState::Stopped | ExecutionState::Idle
            )
            && self.projects.iter().all(|project| {
                project.effective_mode == Mode::Stopped
                    && project.gate_status == Gate::Blocked
                    && project.execution.active_count == Some(0)
                    && project.execution.reason.is_none()
                    && matches!(
                        project.execution.state,
                        ExecutionState::Stopped | ExecutionState::Idle
                    )
            })
    }
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordKind {
    Issue,
    Pr,
    Chat,
}

pub fn selected_record(
    snapshot: &Snapshot,
    repository: &str,
    kind: RecordKind,
) -> Result<String, &'static str> {
    let project = snapshot.project(repository).ok_or("project_unregistered")?;
    let selected = match kind {
        RecordKind::Issue => &project.links.issue,
        RecordKind::Pr => &project.links.pr,
        RecordKind::Chat => &project.links.chat,
    };
    let text = selected.as_ref().ok_or("record_unavailable")?;
    if text.len() > 2048
        || !text.is_ascii()
        || text
            .bytes()
            .any(|c| c.is_ascii_whitespace() || c.is_ascii_control())
    {
        return Err("record_url_rejected");
    }
    let url = tauri::Url::parse(text).map_err(|_| "record_url_rejected")?;
    if !url.username().is_empty()
        || url.password().is_some()
        || url.port().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("record_url_rejected");
    }
    let valid = match kind {
        RecordKind::Chat => {
            let id = url.path().strip_prefix('/').unwrap_or_default();
            url.scheme() == "codex"
                && url.host_str() == Some("threads")
                && uuid_valid(id)
                && text == &format!("codex://threads/{id}")
        }
        RecordKind::Issue | RecordKind::Pr => {
            let segment = match kind {
                RecordKind::Issue => "issues",
                _ => "pull",
            };
            let prefix = format!("/{repository}/{segment}/");
            let number = url.path().strip_prefix(&prefix).unwrap_or_default();
            url.scheme() == "https"
                && url.host_str() == Some("github.com")
                && !number.is_empty()
                && number.bytes().all(|c| c.is_ascii_digit())
                && number.parse::<u64>().is_ok_and(|n| n > 0)
                && text == &format!("https://github.com{prefix}{number}")
        }
    };
    if valid {
        Ok(text.clone())
    } else {
        Err("record_url_rejected")
    }
}

fn uuid_valid(id: &str) -> bool {
    id.len() == 36
        && id.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_hexdigit()
            }
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot() -> Snapshot {
        serde_json::from_value(serde_json::json!({
            "schema_version":1,"observed_at":"2026-10-12T00:00:00Z","host_alias":"test",
            "revision":1,"global_mode":"stopped","gate_status":"blocked","gate_reason":"host_stopped",
            "native_turn_control":"unsupported","execution":{"state":"stopped","active_count":0,"reason":null},
            "coverage":{"state":"confirmed","reason":null},"can_quit":true,"quit_reason":null,
            "remote":{"state":"fresh","observed_at":"2026-10-12T00:00:00Z"},
            "projects":[{"repository":"example/project","override_mode":null,"effective_mode":"stopped",
                "gate_status":"blocked","gate_reason":"host_stopped","execution":{"state":"stopped","active_count":0,"reason":null},
                "work":[],"links":{"issue":"https://github.com/example/project/issues/3","pr":null,"chat":"codex://threads/00000000-0000-0000-0000-000000000001"}}],"request":null
        })).unwrap()
    }
    #[test]
    fn quit_requires_positive_observation_and_blocked_gates() {
        let now = timestamp_millis("2026-10-12T00:00:00Z").unwrap();
        let mut s = snapshot();
        assert!(s.permits_quit_at(now));
        s.execution.active_count = None;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.coverage.state = CoverageState::Unverified;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.projects[0].execution.state = ExecutionState::Unknown;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.projects[0].gate_status = Gate::Allowed;
        assert!(!s.permits_quit_at(now));
    }
    #[test]
    fn quit_rejects_stale_future_inconsistent_or_missing_observation() {
        let now = timestamp_millis("2026-10-12T00:00:00Z").unwrap();
        let mut s = snapshot();
        assert!(!s.permits_quit_at(now + 15_001));
        assert!(!s.permits_quit_at(now - 5_001));
        s.remote.state = RemoteState::Unavailable;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.remote.observed_at = None;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.remote.observed_at = Some("2026-10-11T23:59:59Z".into());
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.revision = None;
        assert!(!s.permits_quit_at(now));
        s = snapshot();
        s.observed_at = "not-a-date".into();
        assert!(!s.permits_quit_at(now));
        assert!(Snapshot::parse(&serde_json::to_vec(&s).unwrap()).is_err());
    }
    #[test]
    fn parser_rejects_truthy_quit_duplicate_keys_and_foreign_protocol() {
        let s = serde_json::to_string(&snapshot()).unwrap();
        assert!(Snapshot::parse(
            s.replace("\"can_quit\":true", "\"can_quit\":\"true\"")
                .as_bytes()
        )
        .is_err());
        assert!(Snapshot::parse(s.replacen("{", "{\"can_quit\":true,", 1).as_bytes()).is_err());
        assert!(Snapshot::parse(
            s.replace("\"schema_version\":1", "\"schema_version\":2")
                .as_bytes()
        )
        .is_err());
        assert!(Snapshot::parse(s.as_bytes()).is_ok());
    }
    #[test]
    fn targets_never_default_to_host() {
        for input in [
            r#"{"scope":"project"}"#,
            r#"{"scope":"all","repository":"example/project"}"#,
            r#"{"scope":"all","repository":null}"#,
            r#"{"scope":"project","repository":null}"#,
            r#"{"scope":"project","repository":"../target"}"#,
            r#"{"scope":"all","extra":true}"#,
            r#"{"scope":"unknown"}"#,
            r#"{"scope":"all","scope":"project"}"#,
            "null",
        ] {
            assert!(
                serde_json::from_str::<Target>(input).is_err(),
                "accepted {input}"
            );
        }
        for target in [
            Target::All,
            Target::Project {
                repository: "example/project".into(),
            },
        ] {
            let serialized = serde_json::to_string(&target).unwrap();
            assert_eq!(serde_json::from_str::<Target>(&serialized).unwrap(), target);
        }
        assert!(!repository_valid("../target"));
        assert!(!repository_valid("Example/project"));
        assert!(repository_valid("1example/project-name"));
    }
    #[test]
    fn mutation_acknowledgement_is_bound_to_action_target_and_revision() {
        let mut s = snapshot();
        assert!(!s.acknowledges(Action::Stop, &Target::All));
        s.request = Some(Request {
            action: Action::Stop,
            target: "all".into(),
            status: RequestState::Applied,
            revision: Some(1),
            reason: None,
        });
        assert!(s.acknowledges(Action::Stop, &Target::All));
        assert!(!s.acknowledges(Action::Pause, &Target::All));
        s.revision = Some(2);
        assert!(!s.acknowledges(Action::Stop, &Target::All));
    }
    #[test]
    fn links_are_selected_records_in_the_registered_repository() {
        let mut s = snapshot();
        assert!(selected_record(&s, "example/project", RecordKind::Issue).is_ok());
        assert!(selected_record(&s, "example/project", RecordKind::Chat).is_ok());
        for url in [
            "javascript:alert(1)",
            "https://github.com.attacker.invalid/example/project/issues/3",
            "https://github.com/other/project/issues/3",
            "https://github.com/example/project/issues/3?redirect=x",
            "https://github.com/example/project/issues/%33",
        ] {
            s.projects[0].links.issue = Some(url.into());
            assert!(selected_record(&s, "example/project", RecordKind::Issue).is_err());
        }
        s.projects[0].links.chat =
            Some("codex://threads/00000000-0000-0000-0000-000000000001?prompt=run".into());
        assert!(selected_record(&s, "example/project", RecordKind::Chat).is_err());
    }
}
