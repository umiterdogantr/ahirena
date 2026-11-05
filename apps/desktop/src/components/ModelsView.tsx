import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { bytes, dateTime, ms, shortDigest } from "../format";
import type { BenchReport, LoadedModel, ModelInfo } from "../types";

interface Props {
  models: ModelInfo[];
  loaded: LoadedModel[];
  errors: string[];
  onRefresh: () => Promise<void>;
}

const CAP_LABEL: Record<string, string> = {
  completion: "metin",
  tools: "araç çağırma",
  thinking: "düşünme",
  vision: "görüntü",
  audio: "ses",
  embedding: "embedding",
};

export default function ModelsView({ models, loaded, errors, onRefresh }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bench, setBench] = useState<{ report: BenchReport | null; path: string | null } | null>(null);

  useEffect(() => {
    api<{ report: BenchReport | null; path: string | null }>("GET", "/api/benchmarks").then(setBench).catch((e) => setError(errorText(e)));
  }, []);

  const unload = async (m: LoadedModel) => {
    setBusy(m.model_id);
    try {
      await api("POST", "/api/models/unload", { provider_id: m.provider_id, model_id: m.model_id });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const refresh = async () => {
    setBusy("refresh");
    await onRefresh();
    setBusy(null);
  };

  return (
    <section className="page">
      <header className="page-header">
        <h2>Model merkezi</h2>
        <button onClick={refresh} disabled={busy === "refresh"}>
          {busy === "refresh" ? "Yenileniyor…" : "Listeyi yenile"}
        </button>
      </header>
      {[...errors, ...(error ? [error] : [])].map((e) => (
        <div key={e} className="error-inline">
          {e}
        </div>
      ))}

      <h3>Bellekteki modeller</h3>
      {loaded.length === 0 ? (
        <p className="muted">Şu anda belleğe yüklü model yok. Model ilk istekte yüklenir, 5 dakika boşta kalınca boşaltılır.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Bellek</th>
              <th>Yerleşim</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {loaded.map((m) => (
              <tr key={m.model_id}>
                <td>{m.model_id}</td>
                <td>{bytes(m.size_bytes)}</td>
                <td>{m.gpu_percent >= 100 ? "Tamamen GPU" : m.gpu_percent <= 0 ? "Tamamen CPU" : `%${m.gpu_percent} GPU / %${100 - m.gpu_percent} CPU`}</td>
                <td>
                  <button onClick={() => unload(m)} disabled={busy === m.model_id}>
                    Bellekten boşalt
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Yüklü modeller</h3>
      {models.length === 0 ? (
        <p className="muted">Yüklü yerel model yok.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Boyut</th>
              <th>Parametre</th>
              <th>Nicemleme</th>
              <th>Bağlam</th>
              <th>Yetenekler</th>
              <th>Digest</th>
              <th>Lisans</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={`${m.provider_id}/${m.model_id}`}>
                <td>
                  {m.model_id}
                  <div className="muted small">{m.location === "local" ? "yerel" : "uzak"} · {m.provider_id}</div>
                </td>
                <td>{bytes(m.size_bytes)}</td>
                <td>{m.parameter_size ?? "—"}</td>
                <td>{m.quantization ?? "—"}</td>
                <td>{m.context_length ? `${Math.round(m.context_length / 1024)}K` : "—"}</td>
                <td>{m.capabilities.map((c) => CAP_LABEL[c] ?? c).join(", ") || "—"}</td>
                <td title={m.digest ?? undefined}>{shortDigest(m.digest)}</td>
                <td className="small">{m.license_name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">Yetenekler model paketinin beyanıdır; uygulamada doğru çalıştığı ayrıca test edilir.</p>

      <h3>Cihaz ölçümleri</h3>
      {!bench?.report ? (
        <p className="muted">
          Henüz ölçüm yok. Ölçüm, depo kökündeki <code>scripts\olcum.cmd</code> ile çalıştırılır (modelleri sırayla yükler, birkaç dakika sürer).
        </p>
      ) : (
        <>
          <p className="muted small">
            {dateTime(bench.report.created_at)} · soru seti {bench.report.prompts_version} · {bench.path}
          </p>
          <BenchTable report={bench.report} />
        </>
      )}
    </section>
  );
}

function BenchTable({ report }: { report: BenchReport }) {
  const groups = new Map<string, BenchReport["results"]>();
  for (const r of report.results) {
    const key = `${r.model_id}|${r.phase}`;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const avg = (xs: (number | null)[]) => {
    const v = xs.filter((x): x is number => x != null);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  return (
    <table>
      <thead>
        <tr>
          <th>Model</th>
          <th>Durum</th>
          <th>İlk token (ort.)</th>
          <th>Hız (ort.)</th>
          <th>Yükleme</th>
          <th>Yerleşim</th>
          <th>Model belleği</th>
          <th>GPU kullanımı</th>
          <th>Hata</th>
        </tr>
      </thead>
      <tbody>
        {[...groups.entries()].map(([key, rs]) => {
          const tps = avg(rs.map((r) => r.tokens_per_s));
          const gpu = rs.find((r) => r.gpu_percent != null)?.gpu_percent;
          return (
            <tr key={key}>
              <td>{rs[0].model_id}</td>
              <td>{rs[0].phase === "cold" ? "soğuk" : "sıcak"}</td>
              <td>{ms(avg(rs.map((r) => r.ttft_ms)))}</td>
              <td>{tps != null ? `${tps.toFixed(1)} token/sn` : "—"}</td>
              <td>{ms(avg(rs.map((r) => r.load_ms)))}</td>
              <td>{gpu == null ? "—" : gpu >= 100 ? "Tamamen GPU" : `%${gpu} GPU`}</td>
              <td>{bytes(rs.find((r) => r.model_memory_bytes)?.model_memory_bytes)}</td>
              <td>{rs.find((r) => r.gpu_used_mib_after != null)?.gpu_used_mib_after ?? "—"} MiB</td>
              <td className="small">{rs.filter((r) => r.error).length || ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
