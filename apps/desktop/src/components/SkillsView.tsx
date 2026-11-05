import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";

interface Grant {
  permission: string;
  scope: { roots?: string[]; mode?: string };
}

interface Skill {
  id: string;
  description: string;
  enabled: boolean;
  content_hash: string;
  tools: string[];
  grants: Grant[];
  scripts: string;
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
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setSkills(await api<Skill[]>("GET", "/api/skills"));
      setServers(await api<McpServer[]>("GET", "/api/mcp"));
      setSql(await api<SqlStatus>("GET", "/api/sql"));
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
      <button className="primary" onClick={() => run("İçe aktarıldı", () => api("POST", "/api/skills/import", { path }))}>
        İçe aktar
      </button>

      {skills.length === 0 && <p className="muted">Yüklü yetenek yok. Örnek: depodaki examples\skills\saat</p>}
      {skills.map((skill) => (
        <article key={skill.id} className="facts">
          <h3>
            {skill.id} {skill.enabled ? "· açık" : "· kapalı"}
          </h3>
          <p>{skill.description}</p>
          <p className="muted small">
            Araçlar: {skill.tools.join(", ")} · betikler: {skill.scripts} · özet {skill.content_hash.slice(0, 12)}
          </p>
          {skill.tools.includes("files.read") && (
            <label>
              Okunacak klasörler (noktalı virgülle)
              <input value={roots[skill.id] || ""} onChange={(e) => setRoots({ ...roots, [skill.id]: e.target.value })} />
            </label>
          )}
          <div className="row">
            <button className="primary" onClick={() => enable(skill)}>
              İzin ver ve aç
            </button>
            <button onClick={() => run("Kapatıldı", () => api("POST", `/api/skills/${skill.id}/disable`))}>Kapat</button>
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
      <div className="row">
        <button
          className="primary"
          onClick={() =>
            run("SQL kaydedildi", () => api("PUT", "/api/sql", { enabled: true, server: sql.server, database: sql.database, driver: "" }))
          }
        >
          Kaydet
        </button>
        <button onClick={() => run("Bağlantı", () => api("POST", "/api/sql/probe"))}>Bağlantıyı dene</button>
      </div>

      <h3>MCP sunucusu</h3>
      <p className="muted small">Yerel süreç, uygulamanın sırlarını almaz. Araç listesi değişince izinler düşer.</p>
      <label>
        Komut (exe yolu)
        <input value={mcpCmd} onChange={(e) => setMcpCmd(e.target.value)} />
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
          </div>
          {server.tools.map((tool) => (
            <div key={tool.name} className="row">
              <span>
                {tool.name} {server.grants.includes(tool.name) ? "· izinli" : ""}
              </span>
              <button onClick={() => run("İzin", () => api("POST", `/api/mcp/${server.id}/grant`, { tool: tool.name }))}>İzin ver</button>
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
