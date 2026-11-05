//! Python çekirdeğinin yaşam döngüsü.
//!
//! Çekirdek rastgele bir gizli anahtarla başlatılır; anahtar yalnızca bu süreçte
//! ve çekirdeğin ortam değişkenlerinde bulunur, arayüz JavaScript'ine verilmez.
//! Çekirdek 127.0.0.1 üzerinde boş bir porta bağlanıp stdout'a
//! `AHIRENA_READY port=<n>` yazınca hazır sayılır.

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const READY_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Clone, Serialize)]
pub struct CoreStatus {
    pub state: &'static str,
    pub error: Option<String>,
    pub log_hint: Option<String>,
}

struct Inner {
    state: &'static str,
    error: Option<String>,
    base_url: Option<String>,
    child: Option<Child>,
    stderr_tail: Vec<String>,
}

pub struct CoreHandle {
    inner: Arc<Mutex<Inner>>,
    token: String,
    client: reqwest::Client,
}

fn data_dir() -> PathBuf {
    if let Ok(d) = std::env::var("AHIRENA_DATA_DIR") {
        if !d.is_empty() {
            return PathBuf::from(d);
        }
    }
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join("com.ahirena.desktop")
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::fill(&mut buf).expect("işletim sistemi rastgele sayı üretemedi");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn core_command() -> Command {
    if cfg!(debug_assertions) {
        let project = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/core");
        let mut c = Command::new("uv");
        c.arg("run").arg("--project").arg(project).arg("ahirena-core");
        c
    } else {
        let exe = std::env::current_exe().expect("uygulama yolu okunamadı");
        Command::new(exe.with_file_name("ahirena-core.exe"))
    }
}

impl CoreHandle {
    pub fn start() -> Self {
        let token = random_token();
        let inner = Arc::new(Mutex::new(Inner {
            state: "starting",
            error: None,
            base_url: None,
            child: None,
            stderr_tail: Vec::new(),
        }));
        let client = reqwest::Client::builder()
            .no_proxy()
            .connect_timeout(Duration::from_secs(5))
            .build()
            .expect("HTTP istemcisi oluşturulamadı");

        let mut cmd = core_command();
        cmd.env("AHIRENA_TOKEN", &token)
            .env("AHIRENA_PARENT_PID", std::process::id().to_string())
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        match cmd.spawn() {
            Ok(mut child) => {
                let stdout = child.stdout.take();
                let stderr = child.stderr.take();
                inner.lock().unwrap().child = Some(child);
                if let Some(err) = stderr {
                    let inner = inner.clone();
                    std::thread::spawn(move || {
                        for line in BufReader::new(err).lines().map_while(Result::ok) {
                            let mut g = inner.lock().unwrap();
                            g.stderr_tail.push(line);
                            if g.stderr_tail.len() > 30 {
                                g.stderr_tail.remove(0);
                            }
                        }
                    });
                }
                if let Some(out) = stdout {
                    let inner = inner.clone();
                    std::thread::spawn(move || {
                        for line in BufReader::new(out).lines().map_while(Result::ok) {
                            if let Some(port) = line.trim().strip_prefix("AHIRENA_READY port=") {
                                if let Ok(port) = port.parse::<u16>() {
                                    let mut g = inner.lock().unwrap();
                                    g.base_url = Some(format!("http://127.0.0.1:{port}"));
                                    g.state = "ready";
                                }
                            }
                        }
                        let mut g = inner.lock().unwrap();
                        if g.state != "stopped" {
                            g.state = "failed";
                            g.base_url = None;
                            let tail = g.stderr_tail.join("\n");
                            g.error = Some(if tail.is_empty() {
                                "Çekirdek süreci beklenmedik biçimde kapandı.".into()
                            } else {
                                format!("Çekirdek süreci kapandı:\n{tail}")
                            });
                        }
                    });
                }
                let watchdog = inner.clone();
                std::thread::spawn(move || {
                    let started = Instant::now();
                    while started.elapsed() < READY_TIMEOUT {
                        if watchdog.lock().unwrap().state != "starting" {
                            return;
                        }
                        std::thread::sleep(Duration::from_millis(200));
                    }
                    let mut g = watchdog.lock().unwrap();
                    if g.state == "starting" {
                        g.state = "failed";
                        g.error = Some(format!("Çekirdek {} saniye içinde hazır olmadı.", READY_TIMEOUT.as_secs()));
                        if let Some(c) = g.child.as_mut() {
                            let _ = c.kill();
                        }
                    }
                });
            }
            Err(e) => {
                let mut g = inner.lock().unwrap();
                g.state = "failed";
                g.error = Some(format!("Çekirdek başlatılamadı: {e}"));
            }
        }

        Self { inner, token, client }
    }

    pub fn status(&self) -> CoreStatus {
        let g = self.inner.lock().unwrap();
        CoreStatus {
            state: if g.state == "stopped" { "failed" } else { g.state },
            error: g.error.clone(),
            log_hint: Some(data_dir().join("logs").join("core.log").display().to_string()),
        }
    }

    pub fn endpoint(&self) -> Result<(String, String), String> {
        let g = self.inner.lock().unwrap();
        match (&g.base_url, g.state) {
            (Some(url), "ready") => Ok((url.clone(), self.token.clone())),
            _ => Err(g.error.clone().unwrap_or_else(|| "Çekirdek hazır değil.".into())),
        }
    }

    pub fn client(&self) -> &reqwest::Client {
        &self.client
    }

    pub fn stop(&self) {
        let mut g = self.inner.lock().unwrap();
        g.state = "stopped";
        if let Some(mut c) = g.child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}
