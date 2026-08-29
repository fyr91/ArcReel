import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowLeft, CirclePause, CirclePlay, RefreshCw, RotateCcw, XCircle } from "lucide-react";
import { useLocation } from "wouter";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { CompanyAssetSourceSyncDashboard } from "@/types";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";
import { ACCENT_BTN_SM_CLS, INPUT_CLS } from "@/components/ui/darkroom-tokens";
import { CompanyCatalogAdminSection } from "@/components/assets/CompanyCatalogAdminSection";

const ACTIVE_RUNS = new Set(["queued", "running", "cancelling"]);

export function CompanyAssetSourceSyncPage() {
  const { t } = useTranslation("assets");
  const [, navigate] = useLocation();
  const [dashboard, setDashboard] = useState<CompanyAssetSourceSyncDashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [intervals, setIntervals] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const data = await API.getCompanyAssetSourceSyncDashboard();
    setDashboard(data);
    setIntervals((current) => {
      const next = { ...current };
      for (const source of data.sources) next[source.source_key] ??= String(source.interval_seconds);
      return next;
    });
  }, []);

  useEffect(() => {
    // Remote dashboard state is applied only after the API promise resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load().catch((error) => useAppStore.getState().pushToast(errMsg(error), "error"));
  }, [load]);

  useEffect(() => {
    if (!dashboard?.runs.some((run) => ACTIVE_RUNS.has(run.status))) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [dashboard, load]);

  const act = async (key: string, action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(key);
    try {
      await action();
      await load();
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen bg-bg px-6 py-8 text-text">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <button
              type="button"
              onClick={() => navigate("/app/assets")}
              className="mt-1 rounded-md p-2 text-text-3 hover:bg-white/5 hover:text-text focus-ring"
              aria-label={t("source_sync_back")}
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-4">company assets · monitor</div>
              <h1 className="font-editorial mt-1 text-3xl">{t("source_sync_title")}</h1>
              <p className="mt-2 max-w-2xl text-sm text-text-3">{t("source_sync_subtitle")}</p>
            </div>
          </div>
          <button type="button" onClick={() => void load()} className={ACCENT_BTN_SM_CLS}>
            <RefreshCw className="h-4 w-4" /> {t("source_sync_refresh")}
          </button>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          {dashboard?.sources.map((source) => {
            const unavailable = !source.enabled || source.adapter === "unconfigured";
            return (
              <article key={source.id} className="rounded-xl border border-hairline-soft bg-bg-grad-a/60 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold">{source.display_name}</div>
                    <div className="mt-1 text-xs text-text-4">{t(`type.${source.asset_type}`)} · {source.adapter}</div>
                  </div>
                  <span className="rounded-full border border-hairline px-2 py-1 text-[10px] text-text-3">
                    {t(unavailable ? "source_sync_unconfigured" : source.paused ? "source_sync_paused" : "source_sync_active")}
                  </span>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div><dt className="text-text-4">{t("source_sync_last_status")}</dt><dd className="mt-1">{source.last_status ?? "—"}</dd></div>
                  <div><dt className="text-text-4">{t("source_sync_last_success")}</dt><dd className="mt-1">{source.last_success_at ? new Date(source.last_success_at).toLocaleString() : "—"}</dd></div>
                </dl>
                {source.last_error && <p className="mt-3 line-clamp-3 text-xs text-warm-bright">{source.last_error}</p>}
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={unavailable || busy !== null}
                    onClick={() => void act(`run:${source.id}`, () => API.runCompanyAssetSourceSync(source.source_key))}
                    className={ACCENT_BTN_SM_CLS}
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> {t("source_sync_run_now")}
                  </button>
                  {!unavailable && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void act(`pause:${source.id}`, () => API.controlCompanyAssetSourceSync(
                        source.source_key,
                        { action: source.paused ? "resume" : "pause" },
                      ))}
                      className="inline-flex items-center gap-1 rounded-md border border-hairline px-2.5 py-1.5 text-xs text-text-2 hover:text-text disabled:opacity-50"
                    >
                      {source.paused ? <CirclePlay className="h-3.5 w-3.5" /> : <CirclePause className="h-3.5 w-3.5" />}
                      {t(source.paused ? "source_sync_resume" : "source_sync_pause")}
                    </button>
                  )}
                </div>
                {!unavailable && (
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="number"
                      min={30}
                      max={86400}
                      aria-label={t("source_sync_interval")}
                      value={intervals[source.source_key] ?? source.interval_seconds}
                      onChange={(event) => setIntervals((current) => ({ ...current, [source.source_key]: event.target.value }))}
                      className={`${INPUT_CLS} w-24`}
                    />
                    <span className="text-xs text-text-4">{t("source_sync_seconds")}</span>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void act(`interval:${source.id}`, () => API.controlCompanyAssetSourceSync(
                        source.source_key,
                        { action: "set_interval", interval_seconds: Number(intervals[source.source_key]) },
                      ))}
                      className="text-xs text-accent-2 hover:underline disabled:opacity-50"
                    >
                      {t("save")}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </section>

        <CompanyCatalogAdminSection />

        <section className="mt-8 overflow-hidden rounded-xl border border-hairline-soft bg-bg-grad-a/40">
          <div className="flex items-center gap-2 border-b border-hairline-soft px-4 py-3">
            <Activity className="h-4 w-4 text-accent-2" />
            <h2 className="text-sm font-semibold">{t("source_sync_history")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-left text-xs">
              <thead className="text-text-4"><tr>{["source_sync_source", "source_sync_trigger", "source_sync_status", "source_sync_counts", "source_sync_started", "source_sync_actions"].map((key) => <th key={key} className="px-4 py-3 font-medium">{t(key)}</th>)}</tr></thead>
              <tbody>
                {dashboard?.runs.map((run) => (
                  <tr key={run.id} className="border-t border-hairline-soft/70">
                    <td className="px-4 py-3">{run.display_name}</td>
                    <td className="px-4 py-3 text-text-3">{run.trigger_kind}</td>
                    <td className="px-4 py-3"><span className="rounded-full border border-hairline px-2 py-1">{run.status}</span></td>
                    <td className="px-4 py-3 font-mono text-text-3">+{run.imported_count} · ↻{run.updated_count} · ={run.unchanged_count} · −{run.archived_count}</td>
                    <td className="px-4 py-3 text-text-3">{new Date(run.started_at ?? run.queued_at).toLocaleString()}</td>
                    <td className="px-4 py-3">
                      {ACTIVE_RUNS.has(run.status) ? (
                        <button type="button" disabled={busy !== null} onClick={() => void act(`cancel:${run.id}`, () => API.cancelCompanyAssetSourceSync(run.id))} className="inline-flex items-center gap-1 text-warm-bright hover:underline"><XCircle className="h-3.5 w-3.5" />{t("source_sync_cancel")}</button>
                      ) : (
                        <button type="button" disabled={busy !== null} onClick={() => void act(`retry:${run.id}`, () => API.retryCompanyAssetSourceSync(run.id))} className="inline-flex items-center gap-1 text-accent-2 hover:underline"><RotateCcw className="h-3.5 w-3.5" />{t("source_sync_retry")}</button>
                      )}
                      {run.error_detail && <div className="mt-1 max-w-xs truncate text-warm-bright" title={run.error_detail}>{run.error_detail}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
