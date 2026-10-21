mod process;
mod protocol;
mod projection;
mod projection_cache;
mod projection_policy;

use process::{bounded_output, LaunchConfig};
use protocol::{Action, RecordKind, Snapshot, Target};
use projection_cache::{CachedRead,ReadCache};
use std::time::Instant;
use serde::Serialize;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::{Emitter, Manager};
use tokio::sync::Mutex;

#[derive(Clone, Debug, Serialize)]
struct BridgeError {
    code: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<Snapshot>,
}

impl BridgeError {
    fn new(code: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            status: None,
        }
    }
    fn with_status(code: impl Into<String>, status: Option<Snapshot>) -> Self {
        Self {
            code: code.into(),
            status,
        }
    }
}

struct Bridge {
    launch: Result<LaunchConfig, &'static str>,
    projection: Mutex<Result<ReadCache, &'static str>>,
    mutation: Mutex<()>,
    local_read: Mutex<()>,
    remote_read: Mutex<()>,
    context_probe: Mutex<()>,
    record_open: Mutex<()>,
    quitting: AtomicBool,
    exit_confirmed: AtomicBool,
}

fn read_context_scope(bytes:&[u8])->Option<String> {
    if bytes.len()>1024 {return None;}
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Context {scope:Option<String>}
    let context:Context=serde_json::from_slice(bytes).ok()?;
    let scope=context.scope?;
    let suffix=scope.strip_prefix("github:read:")?;
    (suffix.len()==64 && suffix.bytes().all(|c|c.is_ascii_digit() || (b'a'..=b'f').contains(&c))).then_some(scope)
}
impl Bridge {
    fn new() -> Self {
        Self {
            launch: LaunchConfig::from_arguments(std::env::args_os().skip(1)),
            projection: Mutex::new(read_epoch().and_then(ReadCache::new)),
            mutation: Mutex::new(()),
            local_read: Mutex::new(()),
            remote_read: Mutex::new(()),
            context_probe: Mutex::new(()),
            record_open: Mutex::new(()),
            quitting: AtomicBool::new(false),
            exit_confirmed: AtomicBool::new(false),
        }
    }

    async fn projection_read(&self,epoch:&str,request:String,refresh:bool,repository:Option<&str>,cursor:Option<&str>,recovery:bool)->Result<CachedRead,BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        if repository.is_some_and(|r|!protocol::repository_valid(r)) {
            return Err(BridgeError::new("project_unregistered"));
        }
        let _lane=if refresh {self.remote_read.lock().await}else{self.local_read.lock().await};
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let launch=self.launch.as_ref().map_err(|code|BridgeError::new(*code))?;
        if cursor.is_some_and(|c|c.len()>2048 || c.is_empty() || !c.bytes().all(|b|b.is_ascii_alphanumeric() || b==b'-' || b==b'_')) || (cursor.is_some() && repository.is_some() && !refresh) {
            return Err(BridgeError::new("invalid_cursor"));
        }
        {
            let _probe=self.context_probe.lock().await;
            let due={
                let mut state=self.projection.lock().await;
                let cache=state.as_mut().map_err(|code|BridgeError::new(*code))?;
                if cache.epoch()!=epoch {return Err(BridgeError::new("read_binding_mismatch"));}
                cache.context_probe_due(Instant::now())
            };
            if due {
                let scope=match bounded_output(launch.read_context_command(epoch),Duration::from_secs(3)).await {
                    Ok(bytes)=>read_context_scope(&bytes),Err(_)=>None,
                };
                let mut state=self.projection.lock().await;
                let cache=state.as_mut().map_err(|code|BridgeError::new(*code))?;
                if cache.epoch()!=epoch {return Err(BridgeError::new("read_binding_mismatch"));}
                cache.context_changed(scope).map_err(BridgeError::new)?;
            }
        }
        let scope=format!("{}:{}:{}",if refresh {"remote"}else{"local"},repository.unwrap_or("overview"),cursor.unwrap_or(""));
        let (ticket,repository_bindings)={
            let mut state=self.projection.lock().await;
            let cache=state.as_mut().map_err(|code|BridgeError::new(*code))?;
            if cache.epoch()!=epoch {return Err(BridgeError::new("read_binding_mismatch"));}
            let now=Instant::now();
            let held=cache.read_held(now,refresh,&scope,cursor.is_some(),recovery).map_err(BridgeError::new)?;
            if held {
                return cache.get(&scope,!refresh,now).ok_or_else(||BridgeError::new("source_wait"));
            }
            let ticket=cache.issue(scope,request,repository.is_some()).map_err(BridgeError::new)?;
            let bindings=if refresh {cache.repository_binding_hints().map_err(BridgeError::new)?}else{"{}".into()};
            if refresh {cache.remote_started(now);}else{cache.local_started(now);}
            (ticket,bindings)
        };
        let credential_scope=ticket.credential_scope.clone();
        let mut command=launch.projection_command(&ticket.epoch,&ticket.request_id,refresh,repository,cursor);
        if refresh {command.arg("--credential-scope").arg(credential_scope.ok_or_else(||BridgeError::new("read_context_unavailable"))?);}
        if repository_bindings!="{}" {command.arg("--repository-bindings").arg(repository_bindings);}
        let output=bounded_output(command,Duration::from_secs(if refresh {60}else{15})).await;
        let mut state=self.projection.lock().await;
        let cache=state.as_mut().map_err(|code|BridgeError::new(*code))?;
        match output {
            Ok(bytes)=>cache.accept(&ticket,&bytes,Instant::now()).map_err(BridgeError::new),
            Err(code)=>{cache.failed(&ticket);Err(BridgeError::new(code))}
        }
    }

    async fn call(
        &self,
        action: Option<Action>,
        target: Option<&Target>,
        refresh: bool,
    ) -> Result<Snapshot, BridgeError> {
        let launch = self
            .launch
            .as_ref()
            .map_err(|code| BridgeError::new(*code))?;
        let duration = if refresh {
            Duration::from_secs(60)
        } else if action.is_some() {
            Duration::from_secs(30)
        } else {
            Duration::from_secs(15)
        };
        let bytes = bounded_output(launch.command(action, target, refresh), duration)
            .await
            .map_err(BridgeError::new)?;
        Snapshot::parse(&bytes).map_err(BridgeError::new)
    }

    async fn snapshot(&self, refresh: bool) -> Result<Snapshot, BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        // Remote reads cannot hold the mutation lane needed by Pause and Stop.
        let _guard = if refresh {
            self.remote_read.lock().await
        } else {
            self.local_read.lock().await
        };
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        self.call(None, None, refresh).await
    }

    async fn open_record(
        &self,
        repository: &str,
        kind: RecordKind,
        issue: Option<u64>,
        expected_pr: Option<u64>,
    ) -> Result<(), BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let _guard = self.record_open.lock().await;
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let snapshot = self.snapshot(!matches!(kind, RecordKind::Chat)).await?;
        let url = protocol::selected_record(&snapshot, repository, kind, issue, expected_pr)
            .map_err(BridgeError::new)?;
        process::open_record_url(&url)
            .await
            .map_err(BridgeError::new)
    }

    async fn mutate_locked(
        &self,
        action: Action,
        target: &Target,
    ) -> Result<Snapshot, BridgeError> {
        self.launch
            .as_ref()
            .map_err(|code| BridgeError::new(*code))?;
        if let Target::Project { repository } = target {
            if !protocol::repository_valid(repository) {
                return Err(BridgeError::new("project_unregistered"));
            }
            let snapshot = self.call(None, None, false).await?;
            if snapshot.project(repository).is_none() {
                return Err(BridgeError::new("project_unregistered"));
            }
        }
        match self.call(Some(action), Some(target), false).await {
            Ok(snapshot) if snapshot.acknowledges(action, target) => Ok(snapshot),
            Err(error) if error.code == "backend_unavailable" => Err(error),
            Err(error) if error.code == "unsupported_runtime" => {
                // An incompatible response cannot confirm whether the effect
                // happened. Preserve its cause and reconcile without retrying.
                let status = self.call(None, None, false).await.ok();
                Err(BridgeError::with_status("unsupported_runtime", status))
            }
            _ => {
                // The effect may have happened before the response was lost.
                // Reconcile once; never resend the mutation automatically.
                let status = self.call(None, None, false).await.ok();
                Err(BridgeError::with_status("mutation_response_lost", status))
            }
        }
    }

    async fn mutate(&self, action: Action, target: Target) -> Result<Snapshot, BridgeError> {
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        let _guard = self.mutation.lock().await;
        if self.quitting.load(Ordering::Acquire) || self.exit_confirmed.load(Ordering::Acquire) {
            return Err(BridgeError::new("quit_in_progress"));
        }
        self.mutate_locked(action, &target).await
    }
}

// A fresh process connection identity, with no persisted task, credential or conversation state.
fn read_epoch()->Result<String,&'static str> {
    use std::io::Read;
    let mut bytes=[0u8;16];
    std::fs::File::open("/dev/urandom").and_then(|mut file|file.read_exact(&mut bytes))
        .map_err(|_|"binding_unavailable")?;
    bytes[6]=(bytes[6]&0x0f)|0x40;bytes[8]=(bytes[8]&0x3f)|0x80;
    let hex=bytes.iter().map(|b|format!("{b:02x}")).collect::<String>();
    Ok(format!("{}-{}-{}-{}-{}",&hex[..8],&hex[8..12],&hex[12..16],&hex[16..20],&hex[20..]))
}

#[tauri::command]
async fn projection_binding(window:tauri::WebviewWindow,state:tauri::State<'_,Arc<Bridge>>)->Result<String,BridgeError> {
    main_window(&window)?;
    let cache=state.projection.lock().await;
    Ok(cache.as_ref().map_err(|code|BridgeError::new(*code))?.epoch().to_owned())
}
#[tauri::command(rename_all="camelCase")]
async fn projection_status(window:tauri::WebviewWindow,state:tauri::State<'_,Arc<Bridge>>,
    epoch:String,request_id:String,refresh:bool,repository:Option<String>,cursor:Option<String>,explicit_recovery:bool)->Result<CachedRead,BridgeError> {
    main_window(&window)?;
    state.projection_read(&epoch,request_id,refresh,repository.as_deref(),cursor.as_deref(),explicit_recovery).await
}
#[tauri::command]
async fn projection_clock_resumed(window:tauri::WebviewWindow,state:tauri::State<'_,Arc<Bridge>>)->Result<(),BridgeError> {
    main_window(&window)?;
    let mut cache=state.projection.lock().await;
    cache.as_mut().map_err(|code|BridgeError::new(*code))?.clock_resumed();
    Ok(())
}

fn main_window(window: &tauri::WebviewWindow) -> Result<(), BridgeError> {
    if window.label() == "main" && window.url().is_ok_and(|url| bundled_navigation(&url)) {
        Ok(())
    } else {
        Err(BridgeError::new("window_not_authorized"))
    }
}

#[tauri::command]
async fn status(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    refresh: bool,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    state.snapshot(refresh).await
}

#[tauri::command]
async fn control(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    action: Action,
    target: Target,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    state.mutate(action, target).await
}

#[tauri::command(rename_all = "camelCase")]
async fn open_record(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Bridge>>,
    repository: String,
    kind: RecordKind,
    issue: Option<u64>,
    expected_pr: Option<u64>,
) -> Result<(), BridgeError> {
    main_window(&window)?;
    if !protocol::repository_valid(&repository) {
        return Err(BridgeError::new("project_unregistered"));
    }
    state
        .open_record(&repository, kind, issue, expected_pr)
        .await
}

#[derive(Clone, Serialize)]
struct QuitEvent {
    state: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<Snapshot>,
}

struct QuitAttempt<'a>(&'a AtomicBool);
impl Drop for QuitAttempt<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

async fn quit_flow(app: tauri::AppHandle) -> Result<Snapshot, BridgeError> {
    let bridge = app.state::<Arc<Bridge>>().inner().clone();
    if bridge.exit_confirmed.load(Ordering::Acquire) {
        return Err(BridgeError::new("quit_in_progress"));
    }
    if bridge
        .quitting
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err(BridgeError::new("quit_in_progress"));
    }
    let _attempt = QuitAttempt(&bridge.quitting);
    show_window(&app);
    let _ = app.emit_to(
        "main",
        "hydra:quit",
        QuitEvent {
            state: "stopping",
            code: None,
            status: None,
        },
    );
    let _guard = bridge.mutation.lock().await;
    let result = async {
        let stopped = match bridge.mutate_locked(Action::Stop, &Target::All).await {
            Ok(snapshot) => snapshot,
            Err(error) => match error.status {
                Some(snapshot) => snapshot,
                None => return Err(error),
            },
        };
        // Fence new commands, then join every lane that can own a child before
        // accepting the final observation. Lock order matches record -> read.
        let _record = bridge.record_open.lock().await;
        let _local = bridge.local_read.lock().await;
        let _remote = bridge.remote_read.lock().await;
        // A fresh read is required even after an apparently successful Stop.
        // Source support or a free local lock alone never authorizes Quit.
        let snapshot = bridge.call(None, None, true).await?;
        if !snapshot.permits_quit()
            || !snapshot.same_targets(&stopped)
            || !snapshot.same_runtime(&stopped)
            || stopped.revision.is_none()
            || snapshot.revision < stopped.revision
        {
            return Err(BridgeError::with_status("quit_blocked", Some(snapshot)));
        }
        Ok(snapshot)
    }
    .await;
    match result {
        Ok(snapshot) => {
            bridge.exit_confirmed.store(true, Ordering::Release);
            app.exit(0);
            Ok(snapshot)
        }
        Err(error) => {
            show_window(&app);
            let _ = app.emit_to(
                "main",
                "hydra:quit",
                QuitEvent {
                    state: "blocked",
                    code: Some(error.code.clone()),
                    status: error.status.clone(),
                },
            );
            Err(error)
        }
    }
}

#[tauri::command]
async fn request_quit(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<Snapshot, BridgeError> {
    main_window(&window)?;
    quit_flow(app).await
}

fn launch_quit(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let _ = quit_flow(app).await;
    });
}

fn bundled_navigation(url: &tauri::Url) -> bool {
    url.scheme() == "tauri"
        && url.host_str() == Some("localhost")
        // Tauri uses the bare custom-scheme origin for its index document.
        && matches!(url.path(), "" | "/" | "/index.html")
        && url.query().is_none()
        && url.fragment().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
}

fn tray_image() -> tauri::image::Image<'static> {
    // Three horizontal control tracks form a functional operations symbol.
    let mut pixels = vec![0; 18 * 18 * 4];
    for (y, knob) in [(4, 6), (9, 12), (14, 8)] {
        for x in 2..16 {
            for dy in 0..2 {
                pixels[((y + dy) * 18 + x) * 4 + 3] = 255;
            }
        }
        for yy in y - 1..=y + 2 {
            for xx in knob - 1..=knob + 1 {
                pixels[(yy * 18 + xx) * 4 + 3] = 255;
            }
        }
    }
    tauri::image::Image::new_owned(pixels, 18, 18)
}

fn main() {
    let application = tauri::Builder::default()
        .manage(Arc::new(Bridge::new()))
        .invoke_handler(tauri::generate_handler![
            status,
            projection_binding,
            projection_status,
            projection_clock_resumed,
            control,
            open_record,
            request_quit
        ])
        .setup(|app| {
            let show =
                tauri::menu::MenuItem::with_id(app, "app-show", "Show Hydra", true, None::<&str>)?;
            let quit = tauri::menu::MenuItem::with_id(
                app,
                "app-quit",
                "Stop All and Quit Hydra",
                true,
                Some("CmdOrCtrl+Q"),
            )?;
            let submenu = tauri::menu::Submenu::with_items(app, "Hydra", true, &[&show, &quit])?;
            let app_menu = tauri::menu::Menu::with_items(app, &[&submenu])?;
            app.set_menu(app_menu)?;
            let tray_show =
                tauri::menu::MenuItem::with_id(app, "tray-show", "Show Hydra", true, None::<&str>)?;
            let tray_quit = tauri::menu::MenuItem::with_id(
                app,
                "tray-quit",
                "Stop All and Quit Hydra",
                true,
                None::<&str>,
            )?;
            let tray_menu = tauri::menu::Menu::with_items(app, &[&tray_show, &tray_quit])?;
            tauri::tray::TrayIconBuilder::with_id("hydra-operations")
                .icon(tray_image())
                .icon_as_template(true)
                .tooltip("Hydra operating controls")
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .build(app)?;
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("Hydra")
            .inner_size(720.0, 820.0)
            .min_inner_size(480.0, 520.0)
            .devtools(false)
            .disable_drag_drop_handler()
            .center()
            .on_navigation(bundled_navigation)
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
            .on_permission_request(|_, _| tauri::webview::PermissionResponse::Deny)
            .on_download(|_, _| false)
            .build()?;
            Ok(())
        })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "app-show" | "tray-show" => show_window(app),
            "app-quit" | "tray-quit" => launch_quit(app),
            _ => {}
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!());
    match application {
        Ok(app) => app.run(|handle, event| {
            #[cfg(target_os = "macos")]
            if matches!(&event, tauri::RunEvent::Reopen { .. }) {
                show_window(handle);
            }
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if !handle
                    .state::<Arc<Bridge>>()
                    .exit_confirmed
                    .load(Ordering::Acquire)
                {
                    api.prevent_exit();
                    launch_quit(handle);
                }
            }
        }),
        Err(_) => eprintln!("Hydra could not initialize its application window."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    struct ProjectionFixture {root:std::path::PathBuf,epoch:String,bridge:Bridge}
    #[cfg(unix)]
    impl ProjectionFixture {
        fn new(provider_wait:bool)->Self {
            use std::{fs,os::unix::fs::PermissionsExt,path::PathBuf,process::Command};
            let epoch=read_epoch().unwrap();
            let root=std::env::temp_dir().join(format!("hydra-projection-read-{epoch}"));
            fs::create_dir(&root).unwrap();
            let emitter=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/control-v3/emit_wire.py");
            let output=Command::new("python3").arg("-I").arg(emitter).output().unwrap();
            assert!(output.status.success());
            let vectors:serde_json::Value=serde_json::from_slice(&output.stdout).unwrap();
            let mut value:serde_json::Value=serde_json::from_str(vectors[0]["wire"].as_str().unwrap()).unwrap();
            if provider_wait {
                let mut o=value["observations"].as_array().unwrap().iter()
                    .find(|o|o["resource"]["source"]=="github").unwrap().clone();
                o["key"]="query:provider-hold".into();o["reason"]="provider_wait".into();
                value["observations"].as_array_mut().unwrap().push(o);
                value["retry_hints"]=serde_json::json!([{"observation_key":"query:provider-hold",
                    "scope":format!("github:read:{}","a".repeat(64)),"after_seconds":600,"basis":"provider"}]);
            }
            value["page"]["next_cursor"]="continuation_page".into();
            let config=root.join("frame.json");fs::write(&config,serde_json::to_vec(&value).unwrap()).unwrap();
            let runtime=root.join("runtime");
            fs::write(&runtime,br#"#!/usr/bin/env python3
import json,sys
a=sys.argv
if 'read-context' in a:
 print(json.dumps({'scope':'github:read:'+'a'*64}))
 sys.exit(0)
p=a[a.index('--config')+1]
v=json.load(open(p))
v['request_id']=a[a.index('--request-id')+1]
v['binding_epoch']=a[a.index('--binding-epoch')+1]
with open(p+'.calls','a') as f: f.write('read\n')
print(json.dumps(v))
"#).unwrap();
            fs::set_permissions(&runtime,fs::Permissions::from_mode(0o700)).unwrap();
            let mut bridge=Bridge::new();
            bridge.launch=Ok(LaunchConfig{runtime,config,home:root.as_os_str().into()});
            bridge.projection=Mutex::new(Ok(ReadCache::new(epoch.clone()).unwrap()));
            Self{root,epoch,bridge}
        }
        fn count(&self)->usize {std::fs::read_to_string(self.root.join("frame.json.calls")).unwrap().lines().count()}
        async fn read(&self,remote:bool,cursor:Option<&str>,recovery:bool)->Result<CachedRead,BridgeError> {
            self.bridge.projection_read(&self.epoch,read_epoch().unwrap(),remote,
                if remote {Some("example/alpha")} else {None},cursor,recovery).await
        }
    }
    #[cfg(unix)]
    impl Drop for ProjectionFixture {fn drop(&mut self){let _=std::fs::remove_dir_all(&self.root);}}
    #[cfg(unix)]
    async fn continuation_during_poll_floor(remote:bool) {
        let f=ProjectionFixture::new(false);
        let first=f.read(remote,None,false).await.unwrap();
        let repeated=f.read(remote,None,true).await.unwrap();
        assert!(repeated.cached);assert_eq!(repeated.sequence,first.sequence);assert_eq!(f.count(),1);
        assert_eq!(f.read(remote,Some("altered_page"),false).await.unwrap_err().code,"source_wait");
        assert_eq!(f.count(),1,"An unissued cursor invoked the core reader");
        let next=f.read(remote,Some("continuation_page"),false).await;
        assert!(next.is_ok(),"Ordinary poll floor held an unread continuation: {:?}",next.err());
        let next=next.unwrap();assert!(!next.cached);assert!(next.sequence>first.sequence);assert_eq!(f.count(),2);
        let replay=f.read(remote,Some("continuation_page"),true).await.unwrap();
        assert!(replay.cached);assert_eq!(replay.sequence,next.sequence);assert_eq!(f.count(),2);
        let repeated=f.read(remote,None,false).await.unwrap();
        assert!(repeated.cached);assert_eq!(f.count(),2);
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn local_continuation_is_not_a_repeat_poll() {continuation_during_poll_floor(false).await;}
    #[cfg(unix)]
    #[tokio::test]
    async fn remote_continuation_is_not_a_repeat_poll() {continuation_during_poll_floor(true).await;}
    #[cfg(unix)]
    #[tokio::test]
    async fn continuation_and_manual_recovery_still_honor_provider_wait() {
        let f=ProjectionFixture::new(true);f.read(true,None,false).await.unwrap();
        for recovery in [false,true] {
            assert_eq!(f.read(true,Some("continuation_page"),recovery).await.unwrap_err().code,"source_wait");
        }
        assert_eq!(f.count(),1);
    }
    #[tokio::test]
    async fn queued_refresh_cannot_spawn_after_quit_fence() {
        let bridge = Arc::new(Bridge::new());
        let guard = bridge.remote_read.lock().await;
        let pending_bridge = bridge.clone();
        let pending = tokio::spawn(async move { pending_bridge.snapshot(true).await });
        tokio::task::yield_now().await;
        bridge.quitting.store(true, Ordering::Release);
        drop(guard);
        assert_eq!(pending.await.unwrap().unwrap_err().code, "quit_in_progress");
        bridge.quitting.store(false, Ordering::Release);
        bridge.exit_confirmed.store(true, Ordering::Release);
        assert_eq!(
            bridge
                .mutate(Action::Start, Target::All)
                .await
                .unwrap_err()
                .code,
            "quit_in_progress"
        );
    }
    #[test]
    fn navigation_only_accepts_bundled_document() {
        for input in [
            "tauri://localhost",
            "tauri://localhost/",
            "tauri://localhost/index.html",
        ] {
            assert!(bundled_navigation(&tauri::Url::parse(input).unwrap()));
        }
        for input in [
            "https://example.test",
            "tauri://other/index.html",
            "tauri://localhost/file",
            "tauri://localhost/?command=stop",
            "tauri://localhost#fragment",
            "tauri://user@localhost",
            "tauri://user:password@localhost/index.html",
            "tauri://localhost:80",
            "http://tauri.localhost",
            "file:///tmp/index.html",
        ] {
            assert!(!bundled_navigation(&tauri::Url::parse(input).unwrap()));
        }
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn retained_repository_identity_reaches_fixed_reader_and_respects_context_fences() {
        use std::fs;
        let mut f=ProjectionFixture::new(false);
        let runtime=f.root.join("runtime");let original=fs::read_to_string(&runtime).unwrap();
        let script=original.replace("print(json.dumps(v))", "with open(p+'.arguments','a') as out: out.write(json.dumps(a)+'\\n')\nprint(json.dumps(v))");
        assert_ne!(script,original);fs::write(&runtime,&script).unwrap();
        fn hints(f:&ProjectionFixture)->serde_json::Value {
            let raw=fs::read_to_string(f.root.join("frame.json.arguments")).unwrap();
            let args:Vec<String>=serde_json::from_str(raw.lines().last().unwrap()).unwrap();
            args.iter().position(|a|a=="--repository-bindings").map(|i|serde_json::from_str(&args[i+1]).unwrap())
                .unwrap_or_else(||serde_json::json!({}))
        }
        async fn fresh(f:&ProjectionFixture)->Result<CachedRead,BridgeError> {
            f.bridge.projection.lock().await.as_mut().unwrap().remote_started(Instant::now()-Duration::from_secs(61));
            f.read(true,None,false).await
        }
        f.read(true,None,false).await.unwrap();assert_eq!(hints(&f),serde_json::json!({}));
        fresh(&f).await.unwrap();assert_eq!(hints(&f)["example/alpha"],101,"Retained numeric repository never reached the fixed reader");

        fs::write(&runtime,script.replace("print(json.dumps(v))","print('{')")).unwrap();
        assert!(fresh(&f).await.is_err());fs::write(&runtime,&script).unwrap();
        fresh(&f).await.unwrap();assert_eq!(hints(&f)["example/alpha"],101,"Read failure forgot an identity pin");

        {
            let mut state=f.bridge.projection.lock().await;let cache=state.as_mut().unwrap();
            cache.context_changed(Some(format!("github:read:{}","b".repeat(64)))).unwrap();
            cache.context_probe_due(Instant::now()+Duration::from_secs(10));
        }
        fresh(&f).await.unwrap();assert_eq!(hints(&f),serde_json::json!({}),"Another credential inherited repository pins");

        let epoch=read_epoch().unwrap();f.bridge.projection.lock().await.as_mut().unwrap().binding_changed(epoch.clone()).unwrap();f.epoch=epoch;
        f.read(true,None,false).await.unwrap();assert_eq!(hints(&f),serde_json::json!({}),"Another binding inherited repository pins");

        let config=f.root.join("frame.json");let mut value:serde_json::Value=serde_json::from_slice(&fs::read(&config).unwrap()).unwrap();
        value["runtime"]["code_digest"]="f".repeat(64).into();
        for source in value["observations"].as_array_mut().unwrap().iter_mut().filter(|o|o["resource"]["kind"]=="repository") {
            source["value"]=serde_json::Value::Null;source["observed_at"]=serde_json::Value::Null;source["availability"]="unavailable".into();
            source["reason"]="fixture_unavailable".into();source["coverage"]=serde_json::json!({"state":"unavailable","scope":"fixture","returned_count":0,"total_count":null,"next_cursor":null,"reason":"fixture_unavailable"});
        }
        fs::write(&config,serde_json::to_vec(&value).unwrap()).unwrap();fresh(&f).await.unwrap();
        fresh(&f).await.unwrap();assert_eq!(hints(&f),serde_json::json!({}),"A new runtime reused old repository pins");
    }

}
