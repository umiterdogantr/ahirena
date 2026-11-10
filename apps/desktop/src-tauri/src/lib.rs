mod core;

use core::{CoreHandle, CoreStatus};
use futures_util::StreamExt;
use serde::Serialize;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::Command;
use tauri::{ipc::Channel, RunEvent, State};

#[derive(Serialize)]
struct RawResponse {
    status: u16,
    body: Value,
}

const METHODS: [&str; 5] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

fn check_path(path: &str) -> Result<(), String> {
    if !path.starts_with("/api/") || path.contains("..") || path.contains("://") || path.contains('\\') {
        return Err(format!("İzin verilmeyen yol: {path}"));
    }
    Ok(())
}

#[tauri::command]
fn core_status(core: State<'_, CoreHandle>) -> CoreStatus {
    core.status()
}

/// Yerel dosya veya klasörü Windows Gezgini'nde gösterir. Yalnızca var olan mutlak yollar.
#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() || trimmed.contains('\0') {
        return Err("Geçersiz yol.".into());
    }
    let p = PathBuf::from(trimmed);
    if !p.is_absolute() {
        return Err("Yalnızca mutlak yol açılır.".into());
    }
    if !p.exists() {
        return Err("Dosya veya klasör bulunamadı.".into());
    }
    let display = p.to_string_lossy().to_string();
    let status = if p.is_dir() {
        Command::new("explorer.exe").arg(&display).status()
    } else {
        Command::new("explorer.exe")
            .arg(format!("/select,{display}"))
            .status()
    }
    .map_err(|e| format!("Gezgin açılamadı: {e}"))?;
    if !status.success() {
        return Err("Gezgin komutu başarısız.".into());
    }
    Ok(())
}

/// Yerel Windows dosya seçici. İptalde null.
#[tauri::command]
fn pick_file(title: Option<String>, extensions: Option<Vec<String>>) -> Result<Option<String>, String> {
    let mut dialog = rfd::FileDialog::new().set_title(title.unwrap_or_else(|| "Dosya seç".into()));
    if let Some(exts) = extensions {
        let clean: Vec<String> = exts
            .into_iter()
            .map(|e| e.trim().trim_start_matches('.').to_ascii_lowercase())
            .filter(|e| !e.is_empty() && e.chars().all(|c| c.is_ascii_alphanumeric()))
            .collect();
        if !clean.is_empty() {
            let refs: Vec<&str> = clean.iter().map(|s| s.as_str()).collect();
            dialog = dialog.add_filter("Dosyalar", &refs);
        }
    }
    Ok(dialog.pick_file().map(|p| p.to_string_lossy().into_owned()))
}

/// Yerel Windows klasör seçici. İptalde null.
#[tauri::command]
fn pick_folder(title: Option<String>) -> Result<Option<String>, String> {
    let dialog = rfd::FileDialog::new().set_title(title.unwrap_or_else(|| "Klasör seç".into()));
    Ok(dialog.pick_folder().map(|p| p.to_string_lossy().into_owned()))
}

#[tauri::command]
async fn api(
    core: State<'_, CoreHandle>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<RawResponse, String> {
    check_path(&path)?;
    let method = method.to_uppercase();
    if !METHODS.contains(&method.as_str()) {
        return Err(format!("İzin verilmeyen yöntem: {method}"));
    }
    let (base, token) = core.endpoint()?;
    let m = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
    let mut req = core
        .client()
        .request(m, format!("{base}{path}"))
        .bearer_auth(token)
        .timeout(std::time::Duration::from_secs(60));
    if let Some(b) = body {
        if method != "GET" {
            req = req.json(&b);
        }
    }
    let res = req.send().await.map_err(|e| format!("Çekirdeğe ulaşılamadı: {e}"))?;
    let status = res.status().as_u16();
    let text = res.text().await.map_err(|e| e.to_string())?;
    let body = serde_json::from_str(&text).unwrap_or(Value::String(text));
    Ok(RawResponse { status, body })
}

/// SSE akışını okuyup her olayı `{event, data}` olarak arayüze iletir.
#[tauri::command]
async fn api_stream(
    core: State<'_, CoreHandle>,
    path: String,
    body: Value,
    on_event: Channel<Value>,
) -> Result<(), String> {
    check_path(&path)?;
    let (base, token) = core.endpoint()?;
    let transport_error = |msg: String| {
        let _ = on_event.send(json!({"event": "transport_error", "data": {"message": msg}}));
    };

    let res = match core
        .client()
        .post(format!("{base}{path}"))
        .bearer_auth(token)
        .json(&body)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            transport_error(format!("Çekirdeğe ulaşılamadı: {e}"));
            return Ok(());
        }
    };
    if !res.status().is_success() {
        let status = res.status().as_u16();
        let text = res.text().await.unwrap_or_default();
        let detail = serde_json::from_str::<Value>(&text)
            .ok()
            .and_then(|v| v.get("detail").and_then(|d| d.as_str()).map(str::to_owned))
            .unwrap_or_else(|| format!("İstek başarısız (HTTP {status})"));
        transport_error(detail);
        return Ok(());
    }

    let mut stream = res.bytes_stream();
    let mut buf: Vec<u8> = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = match chunk {
            Ok(c) => c,
            Err(e) => {
                transport_error(format!("Akış kesildi: {e}"));
                return Ok(());
            }
        };
        buf.extend_from_slice(&chunk);
        while let Some(pos) = find_frame_end(&buf) {
            let frame: Vec<u8> = buf.drain(..pos + 2).collect();
            if let Some(ev) = parse_frame(&frame) {
                if on_event.send(ev).is_err() {
                    return Ok(());
                }
            }
        }
    }
    Ok(())
}

fn find_frame_end(buf: &[u8]) -> Option<usize> {
    buf.windows(2).position(|w| w == b"\n\n")
}

fn parse_frame(frame: &[u8]) -> Option<Value> {
    let text = std::str::from_utf8(frame).ok()?;
    let mut event = None;
    let mut data = String::new();
    for line in text.lines() {
        if let Some(e) = line.strip_prefix("event: ") {
            event = Some(e.trim().to_owned());
        } else if let Some(d) = line.strip_prefix("data: ") {
            data.push_str(d);
        }
    }
    let data: Value = serde_json::from_str(&data).ok()?;
    Some(json!({"event": event?, "data": data}))
}

pub fn run() {
    let core = CoreHandle::start();
    let app = tauri::Builder::default()
        .manage(core)
        .invoke_handler(tauri::generate_handler![
            core_status,
            api,
            api_stream,
            reveal_path,
            pick_file,
            pick_folder
        ])
        .build(tauri::generate_context!())
        .expect("Tauri uygulaması başlatılamadı");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            use tauri::Manager;
            handle.state::<CoreHandle>().stop();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_paths_outside_api() {
        assert!(check_path("/api/health").is_ok());
        assert!(check_path("/health").is_err());
        assert!(check_path("/api/../x").is_err());
        assert!(check_path("/api/http://evil").is_err());
    }

    #[test]
    fn parses_sse_frame() {
        let v = parse_frame(b"event: token\ndata: {\"delta\":\"merhaba\"}\n\n").unwrap();
        assert_eq!(v["event"], "token");
        assert_eq!(v["data"]["delta"], "merhaba");
        assert!(parse_frame(b": yorum\n\n").is_none());
    }
}
