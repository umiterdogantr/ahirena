import { useCallback, useEffect, useState } from "react";
import { api, errorText, pickFile, pickFolder, revealPath } from "../api";

interface Grant {
  permission: string;
  scope: { roots?: string[]; mode?: string };
}

interface SkillTest {
  status: string;
  note?: string;
  tested_at?: string;
}

interface Skill {
  id: string;
  version?: string;
  description: string;
  enabled: boolean;
  content_hash: string;
  package_dir?: string | null;
  tools: string[];
  grants: Grant[];
  scripts: string;
  last_test?: SkillTest | null;
}

interface SkillVersion {
  content_hash: string;
  version: string;
  description: string;
  package_dir: string;
  tools: string[];
  active: boolean;
  exists: boolean;
  archived_at: string | null;
}

interface McpServer {
  id: string;
  name: string;
  enabled: boolean;
  protocol_version: string | null;
  tools_hash: string | null;
  tools: { name: string; description?: string }[];
  grants: string[];
  last_error: string | null;
  grants_revoked?: boolean;
}

interface SqlStatus {
  enabled: boolean;
  server: string;
  database: string;
  writes: string;
  auth: string;
}

interface CallResult {
  ok: boolean;
  error: string | null;
  result?: unknown;
}

export default function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [sql, setSql] = useState<SqlStatus>({ enabled: false, server: "", database: "", writes: "kapalı", auth: "windows" });
  const [path, setPath] = useState("");
  const [roots, setRoots] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("SELECT 1 AS ok");
  const [mcpCmd, setMcpCmd] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [candidates, setCandidates] = useState<{ id: string; name: string; description: string; tools: string[]; package_dir: string }[]>([]);
  const [versions, setVersions] = useState<Record<string, SkillVersion[]>>({});
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setSkills(await api<Skill[]>("GET", "/api/skills"));
      setServers(await api<McpServer[]>("GET", "/api/mcp"));
      setSql(await api<SqlStatus>("GET", "/api/sql"));
      setCandidates(await api("GET", "/api/skills/candidates"));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const run = async (label: string, work: () => Promise<unknown>) => {
    setNote(null);
    setError(null);
    try {
      const out = await work();
      setNote(`${label}: ${typeof out === "string" ? out : JSON.stringify(out, null, 2)}`);
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const enable = (skill: Skill) => {
    const grants = skill.tools.map((permission) => {
      if (permission === "files.read") {
        return { permission, scope: { roots: (roots[skill.id] || "").split(";").map((s) => s.trim()).filter(Boolean) } };
      }
      if (permission.startsWith("sql.")) return { permission, scope: { mode: "read" } };
      return { permission, scope: {} };
    });
    return run(`${skill.id} etkin`, () => api("POST", `/api/skills/${skill.id}/enable`, { grants }));
  };

  return (
    <section className="page">
      <header className="page-header">
        <h2>Yetenekler</h2>
      </header>
      <p className="muted">
        Paket yalnızca ad, açıklama ve istediği araçları bildirir. İzni siz verirsiniz. Betik ve kabuk çalıştırma kapalıdır.
        SQL yazma kapalıdır; parola kaydedilmez.
      </p>

      <label>
        Paket klasörü (SKILL.md + capabilities.json)
        <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\paketler\saat" />
      </label>
      <div className="row">
        <button
          type="button"
          onClick={async () => {
            try {
              const p = await pickFolder("Yetenek paketi klasörü");
              if (p) setPath(p);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Klasör seç…
        </button>
        <button
          type="button"
          disabled={!path.trim()}
          onClick={() => run("Doğrulama", () => api("POST", "/api/skills/validate-path", { path }))}
        >
          Klasörü doğrula
        </button>
        <button className="primary" onClick={() => run("İçe aktarıldı", () => api("POST", "/api/skills/import", { path }))}>
          İçe aktar
        </button>
      </div>
      <h3>Taslak yetenek</h3>
      <p className="muted small">Doğal dil taslak üretir; aday karantinada kalır. İzin ve içe aktarma olmadan çalışmaz.</p>
      <label>
        Ne yapsın?
        <textarea rows={2} value={draftPrompt} onChange={(e) => setDraftPrompt(e.target.value)} />
      </label>
      <button
        onClick={() =>
          run("Taslak", async () => {
            const out = await api("POST", "/api/skills/draft", { prompt: draftPrompt });
            setDraftPrompt("");
            return out;
          })
        }
      >
        Taslak üret
      </button>
      {candidates.map((c) => (
        <article key={c.id} className="facts">
          <h3>
            {c.name} · aday
          </h3>
          <p>{c.description}</p>
          <p className="muted small">
            Araçlar: {c.tools.join(", ")} · {c.package_dir}
          </p>
          <div className="row">
            <button
              type="button"
              onClick={() => run("Doğrulama", () => api("POST", "/api/skills/validate-path", { path: c.package_dir }))}
            >
              Doğrula
            </button>
            <button
              className="primary"
              onClick={() => run("İçe aktarıldı", () => api("POST", "/api/skills/import", { path: c.package_dir }))}
            >
              İçe aktar
            </button>
            <button onClick={() => run("Silindi", () => api("POST", `/api/skills/candidates/${c.id}/discard`))}>Adayı sil</button>
          </div>
        </article>
      ))}

      {skills.length === 0 && <p className="muted">Yüklü yetenek yok. Örnek: depodaki examples\skills\saat</p>}
      {skills.map((skill) => (
        <article key={skill.id} className="facts">
          <h3>
            {skill.id} {skill.enabled ? "· açık" : "· kapalı"}
          </h3>
          <p>{skill.description}</p>
          <p className="muted small">
            Sürüm {skill.version ?? "?"} · araçlar: {skill.tools.join(", ")} · betikler: {skill.scripts} · özet{" "}
            {skill.content_hash.slice(0, 12)}
            {skill.last_test && (
              <>
                <br />
                Son doğrulama: {skill.last_test.status}
                {skill.last_test.tested_at ? ` · ${skill.last_test.tested_at}` : ""}
                {skill.last_test.note ? ` — ${skill.last_test.note}` : ""}
              </>
            )}
          </p>
          {skill.tools.includes("files.read") && (
            <label>
              Okunacak klasörler (noktalı virgülle)
              <input value={roots[skill.id] || ""} onChange={(e) => setRoots({ ...roots, [skill.id]: e.target.value })} />
              <button
                type="button"
                onClick={async () => {
                  try {
                    const p = await pickFolder("Okuma kökü");
                    if (!p) return;
                    const prev = (roots[skill.id] || "").split(";").map((s) => s.trim()).filter(Boolean);
                    if (!prev.includes(p)) setRoots({ ...roots, [skill.id]: [...prev, p].join(";") });
                  } catch (e) {
                    setError(errorText(e));
                  }
                }}
              >
                Klasör ekle…
              </button>
            </label>
          )}
          <div className="row">
            <button
              type="button"
              onClick={() => run("Doğrulama", () => api("POST", `/api/skills/${skill.id}/validate`))}
            >
              Paketi doğrula
            </button>
            {skill.package_dir && (
              <button
                type="button"
                onClick={() => revealPath(skill.package_dir!).catch((e) => setError(errorText(e)))}
              >
                Paketi klasörde aç
              </button>
            )}
            <button className="primary" onClick={() => enable(skill)}>
              İzin ver ve aç
            </button>
            <button onClick={() => run("Kapatıldı", () => api("POST", `/api/skills/${skill.id}/disable`))}>Kapat</button>
            <button
              onClick={() => run("Kaldırıldı", () => api("DELETE", `/api/skills/${skill.id}`))}
              title="Kayıt ve uygulama veri klasöründeki paket kopyası silinir"
            >
              Kaldır
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  const r = await api<{ versions: SkillVersion[] }>("GET", `/api/skills/${skill.id}/versions`);
                  setVersions((v) => ({ ...v, [skill.id]: r.versions }));
                  setError(null);
                } catch (e) {
                  setError(errorText(e));
                }
              }}
            >
              Sürümler
            </button>
            {skill.tools.includes("clock.now") && (
              <button
                onClick={() =>
                  run("Saat", () => api<CallResult>("POST", `/api/skills/${skill.id}/call`, { tool: "clock.now", arguments: {} }))
                }
              >
                Saati çalıştır
              </button>
            )}
          </div>
          {versions[skill.id] && versions[skill.id].length > 0 && (
            <div className="facts">
              <p className="muted small">Önceki sürüme dönüş izni düşürür; otomatik açılmaz.</p>
              {versions[skill.id].map((v) => (
                <div key={v.content_hash} className="row">
                  <span className="muted small">
                    v{v.version} · {v.active ? "aktif" : "arşiv"} · {v.exists ? "diskte" : "dosya yok"} ·{" "}
                    {v.content_hash.slice(0, 12)} · {v.tools.join(", ")}
                  </span>
                  {!v.active && (
                    <button
                      type="button"
                      disabled={!v.exists}
                      onClick={() =>
                        run("Geri dönüldü", async () => {
                          const out = await api("POST", `/api/skills/${skill.id}/rollback`, {
                            content_hash: v.content_hash,
                          });
                          const r = await api<{ versions: SkillVersion[] }>("GET", `/api/skills/${skill.id}/versions`);
                          setVersions((prev) => ({ ...prev, [skill.id]: r.versions }));
                          return out;
                        })
                      }
                    >
                      Bu sürüme dön
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {skill.tools.includes("files.read") && (
            <FileCall skillId={skill.id} onRun={run} />
          )}
          {skill.tools.includes("sql.query") && (
            <label>
              Salt okunur sorgu
              <textarea rows={3} value={query} onChange={(e) => setQuery(e.target.value)} />
              <button
                onClick={() =>
                  run("Sorgu", () => api<CallResult>("POST", `/api/skills/${skill.id}/call`, { tool: "sql.query", arguments: { sql: query } }))
                }
              >
                Sorguyu çalıştır
              </button>
            </label>
          )}
        </article>
      ))}

      <h3>SQL Server</h3>
      <p className="muted small">Windows kimliğiyle bağlanır. Yazma yoktur. Sunucu tanımlı değilse sonuç uydurulmaz.</p>
      <label>
        Sunucu
        <input value={sql.server} onChange={(e) => setSql({ ...sql, server: e.target.value })} />
      </label>
      <label>
        Veritabanı
        <input value={sql.database} onChange={(e) => setSql({ ...sql, database: e.target.value })} />
      </label>
      <p className="muted small">Durum: {sql.enabled ? "açık" : "kapalı"} · yazma {sql.writes}</p>
      <div className="row">
        <button
          className="primary"
          onClick={() =>
            run("SQL kaydedildi", () => api("PUT", "/api/sql", { enabled: true, server: sql.server, database: sql.database, driver: "" }))
          }
        >
          Kaydet ve aç
        </button>
        <button
          onClick={() =>
            run("SQL kapatıldı", () => api("PUT", "/api/sql", { enabled: false, server: sql.server, database: sql.database, driver: "" }))
          }
        >
          Kapat
        </button>
        <button onClick={() => run("Bağlantı", () => api("POST", "/api/sql/probe"))}>Bağlantıyı dene</button>
      </div>

      <h3>MCP sunucusu</h3>
      <p className="muted small">Yerel süreç, uygulamanın sırlarını almaz. Araç listesi değişince izinler düşer.</p>
      <label>
        Komut (exe yolu)
        <input value={mcpCmd} onChange={(e) => setMcpCmd(e.target.value)} />
        <button
          type="button"
          onClick={async () => {
            try {
              const p = await pickFile("MCP komutu", ["exe", "cmd", "bat"]);
              if (p) setMcpCmd(p);
            } catch (e) {
              setError(errorText(e));
            }
          }}
        >
          Exe seç…
        </button>
      </label>
      <label>
        Argümanlar (boşlukla)
        <input value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} />
      </label>
      <button
        className="primary"
        onClick={() =>
          run("MCP eklendi", () =>
            api("POST", "/api/mcp", { name: "yerel", command: mcpCmd, args: mcpArgs.split(" ").filter(Boolean) }),
          )
        }
      >
        Ekle
      </button>
      {servers.map((server) => (
        <article key={server.id} className="facts">
          <h3>
            {server.name} {server.enabled ? "· izinli" : "· onaysız"}
          </h3>
          <p className="muted small">
            Sürüm: {server.protocol_version ?? "—"} · özet {server.tools_hash?.slice(0, 12) ?? "—"}
          </p>
          {server.last_error && <p className="error-inline">{server.last_error}</p>}
          <div className="row">
            <button onClick={() => run("Liste", () => api("POST", `/api/mcp/${server.id}/refresh`))}>Listeyi yenile</button>
            <button onClick={() => run("Silindi", () => api("DELETE", `/api/mcp/${server.id}`))}>Sil</button>
          </div>
          {server.tools.map((tool) => (
            <div key={tool.name} className="row">
              <span>
                {tool.name} {server.grants.includes(tool.name) ? "· izinli" : ""}
              </span>
              {server.grants.includes(tool.name) ? (
                <button onClick={() => run("İzin alındı", () => api("POST", `/api/mcp/${server.id}/revoke`, { tool: tool.name }))}>
                  İzni geri al
                </button>
              ) : (
                <button onClick={() => run("İzin", () => api("POST", `/api/mcp/${server.id}/grant`, { tool: tool.name }))}>İzin ver</button>
              )}
            </div>
          ))}
        </article>
      ))}

      {note && <pre className="facts">{note}</pre>}
      {error && <p className="error-inline">{error}</p>}
    </section>
  );
}

function FileCall({ skillId, onRun }: { skillId: string; onRun: (label: string, work: () => Promise<unknown>) => void }) {
  const [file, setFile] = useState("");
  return (
    <label>
      Göreli dosya
      <input value={file} onChange={(e) => setFile(e.target.value)} />
      <button
        onClick={() =>
          onRun("Dosya", () => api<CallResult>("POST", `/api/skills/${skillId}/call`, { tool: "files.read", arguments: { path: file } }))
        }
      >
        Dosyayı oku
      </button>
    </label>
  );
}
