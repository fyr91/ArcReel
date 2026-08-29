import { useEffect, useMemo } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppStore } from "@/stores/app-store";
import { useAssetsStore } from "@/stores/assets-store";
import { useAuthStore } from "@/stores/auth-store";
import {
  isCompanyAssetJobActive,
  useCompanyAssetSyncStore,
} from "@/stores/company-asset-sync-store";
import type { AssetType } from "@/types/asset";
import { UI_LAYERS } from "@/utils/ui-layers";

const TYPES: AssetType[] = ["character", "scene", "prop"];
const handledTerminalJobs = new Set<string>();

export function CompanyAssetSyncMonitor() {
  const { t } = useTranslation("assets");
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const jobs = useCompanyAssetSyncStore((state) => state.jobs);
  const startAllOnce = useCompanyAssetSyncStore((state) => state.startAllOnce);
  const resetAutoSync = useCompanyAssetSyncStore((state) => state.resetAutoSync);
  const refresh = useCompanyAssetSyncStore((state) => state.refresh);
  const active = useMemo(
    () => TYPES.flatMap((type) => isCompanyAssetJobActive(jobs[type]) ? [{ type, job: jobs[type] }] : []),
    [jobs],
  );

  useEffect(() => {
    if (!isAuthenticated) {
      resetAutoSync();
      return;
    }
    void startAllOnce().catch(() => undefined);
  }, [isAuthenticated, resetAutoSync, startAllOnce]);

  useEffect(() => {
    if (!isAuthenticated || active.length === 0) return;
    const timer = window.setInterval(() => {
      for (const { type } of active) void refresh(type).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active, isAuthenticated, refresh]);

  useEffect(() => {
    for (const type of TYPES) {
      const job = jobs[type];
      if (!job || isCompanyAssetJobActive(job) || handledTerminalJobs.has(job.job_id)) continue;
      handledTerminalJobs.add(job.job_id);
      if (job.status === "succeeded" && job.result) {
        useAssetsStore.getState().invalidateCatalog(type);
        useAppStore.getState().pushNotification(t("sync_library_success", {
          type: t(`type.${type}`),
          added: job.result.added,
          updated: job.result.updated,
          archived: job.result.archived,
          unchanged: job.result.unchanged,
          assetsDownloaded: job.result.assetsDownloaded,
        }), "success");
      } else if (job.status === "failed") {
        useAppStore.getState().pushNotification(job.error_message || t("sync_library_failed", {
          type: t(`type.${type}`),
        }), "error");
      }
    }
  }, [jobs, t]);

  if (!isAuthenticated || active.length === 0) return null;
  const current = active[0];
  const hasTotal = current.job.progress_total > 0;
  const percent = hasTotal
    ? Math.min(100, Math.round((current.job.progress_current / current.job.progress_total) * 100))
    : 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-5 right-5 ${UI_LAYERS.toast} w-72 rounded-xl border p-3.5 shadow-2xl backdrop-blur-xl`}
      style={{ borderColor: "var(--color-accent-soft)", background: "oklch(0.17 0.012 260 / 0.94)" }}
    >
      <div className="flex items-center gap-2.5">
        {current.job.status === "queued"
          ? <RefreshCw aria-hidden className="h-4 w-4 text-accent" />
          : <Loader2 aria-hidden className="h-4 w-4 animate-spin text-accent" />}
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-text">
            {t("sync_background_title", { type: t(`type.${current.type}`) })}
          </div>
          <div className="mt-0.5 text-[10px] text-text-4">
            {hasTotal
              ? t("sync_progress_compact", {
                  current: current.job.progress_current,
                  total: current.job.progress_total,
                })
              : t("syncing_library")}
          </div>
        </div>
        {active.length > 1 && <span className="text-[10px] text-text-4">+{active.length - 1}</span>}
        {hasTotal && <span className="num text-[11px] text-text-3">{percent}%</span>}
      </div>
    </div>
  );
}
