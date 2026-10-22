use crate::protocol::{Action, Target, MAX_OUTPUT};
use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::Command,
    time::timeout,
};

const CHILD_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
const MAX_STDERR: usize = 16_384;

#[derive(Clone, Debug)]
pub struct LaunchConfig {
    pub runtime: PathBuf,
    pub config: PathBuf,
    pub home: OsString,
}

impl LaunchConfig {
    pub fn from_arguments(
        arguments: impl IntoIterator<Item = OsString>,
    ) -> Result<Self, &'static str> {
        let mut arguments = arguments.into_iter();
        let mut runtime = None;
        let mut config = None;
        while let Some(argument) = arguments.next() {
            let slot = match argument.to_str() {
                Some("--runtime") if runtime.is_none() => &mut runtime,
                Some("--config") if config.is_none() => &mut config,
                _ => return Err("launch_configuration_invalid"),
            };
            let path = PathBuf::from(arguments.next().ok_or("launch_configuration_invalid")?);
            if !path.is_absolute()
                || path
                    .components()
                    .any(|part| matches!(part, std::path::Component::ParentDir))
                || !path.is_file()
            {
                return Err("launch_configuration_invalid");
            }
            *slot = Some(path);
        }
        let home = std::env::var_os("HOME")
            .filter(|value| Path::new(value).is_absolute())
            .ok_or("launch_configuration_invalid")?;
        Ok(Self {
            runtime: runtime.ok_or("launch_configuration_invalid")?,
            config: config.ok_or("launch_configuration_invalid")?,
            home,
        })
    }

    pub fn read_context_command(&self,epoch:&str)->Command {
        let mut command=Command::new(&self.runtime);
        command.args(["-I","-m","hydra_sdlc.cli","read-context","--binding-epoch",epoch]);
        command.current_dir("/").env_clear().env("HOME",&self.home).env("PATH",CHILD_PATH);command
    }
    pub fn projection_command(&self, epoch:&str, request:&str, refresh:bool, repository:Option<&str>, cursor:Option<&str>) -> Command {
        let mut command=self.command(None,None,refresh);
        command.args(["--projection-schema","3","--binding-epoch",epoch,"--request-id",request]);
        if let Some(repository)=repository {command.arg("--repository").arg(repository);}
        if let Some(cursor)=cursor {command.arg("--cursor").arg(cursor);}
        command
    }

    pub fn command(
        &self,
        action: Option<Action>,
        target: Option<&Target>,
        refresh: bool,
    ) -> Command {
        let mut command = Command::new(&self.runtime);
        command.args(["-I", "-m", "hydra_sdlc.cli", "control"]);
        command.arg(action.map(Action::argument).unwrap_or("status"));
        command.arg("--config").arg(&self.config);
        match target {
            Some(Target::All) => {
                command.arg("--all");
            }
            Some(Target::Project { repository }) => {
                command.arg("--project").arg(repository);
            }
            None => {}
        }
        if refresh {
            command.arg("--refresh");
        }
        command
            .current_dir("/")
            .env_clear()
            .env("HOME", &self.home)
            .env("PATH", CHILD_PATH);
        command
    }
}

async fn read_bounded(
    mut reader: impl AsyncRead + Unpin,
    bound: usize,
) -> Result<Vec<u8>, &'static str> {
    let mut data = Vec::with_capacity(bound.min(8192));
    let mut chunk = [0; 8192];
    loop {
        let length = reader
            .read(&mut chunk)
            .await
            .map_err(|_| "backend_read_failed")?;
        if length == 0 {
            return Ok(data);
        }
        if data.len() + length > bound {
            return Err("backend_output_too_large");
        }
        data.extend_from_slice(&chunk[..length]);
    }
}

/// Only used for commands constructed in Rust. The renderer cannot select an
/// executable, environment, working directory or argument vector.
pub async fn bounded_output(
    mut command: Command,
    duration: Duration,
) -> Result<Vec<u8>, &'static str> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    command.process_group(0);
    let mut child = command.spawn().map_err(|_| "backend_unavailable")?;
    let process_group = child.id();
    let stdout = child.stdout.take().ok_or("backend_read_failed")?;
    let stderr = child.stderr.take().ok_or("backend_read_failed")?;
    let operation = timeout(duration, async {
        // Read before waiting, so the process group leader is not deliberately
        // reaped while its descendants still hold the pipe descriptors.
        let (out, _) = tokio::try_join!(
            read_bounded(stdout, MAX_OUTPUT),
            read_bounded(stderr, MAX_STDERR)
        )?;
        let status = child.wait().await.map_err(|_| "backend_wait_failed")?;
        if status.success() {
            Ok(out)
        } else {
            Err("backend_process_failed")
        }
    })
    .await;
    match operation {
        Ok(Ok(bytes)) => Ok(bytes),
        Ok(Err("backend_process_failed")) => Err("backend_process_failed"),
        failure => {
            #[cfg(unix)]
            if let Some(pid) = process_group {
                // SAFETY: this group was created for this still-owned child at
                // spawn, never selected from a persisted PID or another app.
                unsafe {
                    libc::kill(-(pid as libc::pid_t), libc::SIGKILL);
                }
            }
            let _ = child.start_kill();
            let _ = timeout(Duration::from_secs(2), child.wait()).await;
            match failure {
                Err(_) => Err("backend_timeout"),
                Ok(Err(code)) => Err(code),
                _ => unreachable!(),
            }
        }
    }
}

pub async fn open_record_url(url: &str) -> Result<(), &'static str> {
    #[cfg(target_os = "macos")]
    {
        let mut command = Command::new("/usr/bin/open");
        command
            .arg(url)
            .current_dir("/")
            .env_clear()
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin");
        bounded_output(command, Duration::from_secs(5))
            .await
            .map(|_| ())
            .map_err(|_| "record_open_failed")
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = url;
        Err("platform_unsupported")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn projection_is_an_explicit_read_profile_in_the_same_isolated_process_boundary() {
        let launch=LaunchConfig{runtime:"/opt/example/bin/python3".into(),config:"/opt/example/host.toml".into(),home:"/Users/example".into()};
        let command=launch.projection_command("00000000-0000-4000-8000-000000000001","00000000-0000-4000-8000-000000000002",true,Some("example/alpha"),Some("opaque_cursor"));
        let command=command.as_std();
        assert_eq!(command.get_args().collect::<Vec<_>>(),[
            "-I","-m","hydra_sdlc.cli","control","status","--config","/opt/example/host.toml","--refresh",
            "--projection-schema","3","--binding-epoch","00000000-0000-4000-8000-000000000001",
            "--request-id","00000000-0000-4000-8000-000000000002","--repository","example/alpha","--cursor","opaque_cursor"
        ].map(std::ffi::OsStr::new));
        assert_eq!(command.get_current_dir(),Some(Path::new("/")));
        assert_eq!(command.get_envs().count(),2);
    }
    #[test]
    fn fixed_invocation_ignores_repository_environment_and_cwd() {
        let launch = LaunchConfig {
            runtime: "/opt/example/bin/python3".into(),
            config: "/opt/example/host.toml".into(),
            home: "/Users/example".into(),
        };
        let target = Target::Project {
            repository: "example/project".into(),
        };
        let command = launch.command(Some(Action::Pause), Some(&target), false);
        let command = command.as_std();
        assert_eq!(command.get_program(), "/opt/example/bin/python3");
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            [
                "-I",
                "-m",
                "hydra_sdlc.cli",
                "control",
                "pause",
                "--config",
                "/opt/example/host.toml",
                "--project",
                "example/project"
            ]
            .map(std::ffi::OsStr::new)
        );
        assert_eq!(command.get_current_dir(), Some(Path::new("/")));
        assert_eq!(command.get_envs().count(), 2);
        assert!(!command
            .get_envs()
            .any(|(key, _)| key == "PYTHONPATH" || key == "PYTHONHOME"));
    }
    #[tokio::test]
    async fn oversized_output_is_rejected_without_retaining_it() {
        let input = [0u8; 65];
        assert_eq!(
            read_bounded(&input[..], 64).await.unwrap_err(),
            "backend_output_too_large"
        );
        assert_eq!(read_bounded(&input[..64], 64).await.unwrap().len(), 64);
    }
    #[tokio::test]
    async fn real_owned_child_timeout_is_bounded() {
        let mut command = Command::new("/bin/sleep");
        command.arg("10");
        let start = std::time::Instant::now();
        assert_eq!(
            bounded_output(command, Duration::from_millis(30))
                .await
                .unwrap_err(),
            "backend_timeout"
        );
        assert!(start.elapsed() < Duration::from_secs(3));
    }
}
