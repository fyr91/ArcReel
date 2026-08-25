import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Loader2, RefreshCw, Scissors, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { HyperframesWorkspaceStatus } from "@/types";
import { useTasksStore } from "@/stores/tasks-store";
import { errMsg } from "@/utils/async";

interface HyperframesStudioTabProps {
  projectName: string;
  episode: number;
}

function studioProjectUrl(status: HyperframesWorkspaceStatus): string | null {
  if (!status.studio_url || !status.workspace_path) return null;
  const projectName = status.workspace_path.split("/").at(-1);
  if (!projectName) return status.studio_url;
  return `${status.studio_url}/#project/${encodeURIComponent(projectName)}`;
}

export function HyperframesStudioTab({ projectName, episode }: HyperframesStudioTabProps) {
  const { t } = useTranslation("dashboard");
  const requestKey = `${projectName}:${episode}`;
  const [statusState, setStatusState] = useState<{
    key: string;
    value: HyperframesWorkspaceStatus;
  } | null>(null);
  const [errorState, setErrorState] = useState<{ key: string; message: string } | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [studioRevision, setStudioRevision] = useState(0);
  const tasks = useTasksStore((state) => state.tasks);
  const bgmTask = useMemo(() => {
    const resourceId = `episode_${String(episode).padStart(2, "0")}`;
    return tasks
      .filter(
        (task) =>
          task.project_name === projectName &&
          task.task_type === "hyperframes_bgm" &&
          task.resource_id === resourceId,
      )
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
  }, [episode, projectName, tasks]);
  const previousBgmState = useRef<{ taskId: string; status: string } | null>(null);

  useEffect(() => {
    const previous = previousBgmState.current;
    if (
      bgmTask?.status === "succeeded" &&
      previous?.taskId === bgmTask.task_id &&
      previous.status !== "succeeded"
    ) {
      setStudioRevision((value) => value + 1);
    }
    previousBgmState.current = bgmTask
      ? { taskId: bgmTask.task_id, status: bgmTask.status }
      : null;
  }, [bgmTask]);

  useEffect(() => {
    let cancelled = false;
    API.startHyperframesStudio(projectName, episode)
      .then((next) => {
        if (!cancelled) setStatusState({ key: `${projectName}:${episode}`, value: next });
      })
      .catch((reason) => {
        if (!cancelled) {
          setErrorState({ key: `${projectName}:${episode}`, message: errMsg(reason) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectName, episode, retryToken]);

  const retry = useCallback(() => {
    setErrorState(null);
    setStatusState(null);
    setRetryToken((value) => value + 1);
  }, []);
  const status = statusState?.key === requestKey ? statusState.value : null;
  const error = errorState?.key === requestKey ? errorState.message : null;
  const studioUrl = status ? studioProjectUrl(status) : null;
  const musicProgress =
    bgmTask?.execution_progress?.kind === "minimax_music"
      ? bgmTask.execution_progress
      : null;
  const bgmDisplayStatus =
    bgmTask?.status === "running" && musicProgress?.phase === "queued"
      ? "queued"
      : bgmTask?.status;
  const bgmStatusText = bgmTask
    ? t(`hyperframes_bgm_status_${bgmDisplayStatus}`, {
        progress: musicProgress?.progress ?? 0,
        position: musicProgress?.queue_position ?? "—",
        defaultValue: bgmTask.status,
      })
    : null;

  if (error) {
    return (
      <div className="grid h-full place-items-center bg-[oklch(0.16_0.01_260)] px-6">
        <div className="max-w-lg rounded-xl border border-red-500/20 bg-red-500/5 p-5 text-center">
          <TriangleAlert className="mx-auto mb-3 h-6 w-6 text-red-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-[var(--color-text)]">
            {t("hyperframes_studio_start_failed")}
          </h3>
          <p className="mt-2 break-words text-xs leading-5 text-[var(--color-text-3)]">{error}</p>
          <button
            type="button"
            onClick={retry}
            className="focus-ring mt-4 inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-xs text-[var(--color-text-2)]"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            {t("hyperframes_retry")}
          </button>
        </div>
      </div>
    );
  }

  if (!status || !studioUrl) {
    return (
      <div
        role="status"
        className="flex h-full items-center justify-center gap-2 bg-[oklch(0.16_0.01_260)] text-xs text-[var(--color-text-3)]"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t("hyperframes_studio_starting")}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[oklch(0.12_0.01_260)]">
      <div className="flex min-h-9 shrink-0 items-center gap-3 border-b border-[var(--color-hairline)] px-3 py-1">
        {status.editing_state === "assembly_draft" && (
          <div
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-amber-400/25 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-300"
            role="status"
          >
            <TriangleAlert className="h-3 w-3" aria-hidden="true" />
            {t("hyperframes_editing_state_assembly_draft")}
          </div>
        )}
        {status.editing_state === "edited" && (
          <div
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-emerald-400/25 bg-emerald-400/10 px-2 py-1 text-[11px] text-emerald-300"
            role="status"
          >
            <Scissors className="h-3 w-3" aria-hidden="true" />
            {t("hyperframes_editing_state_edited", {
              count: status.editing_analysis?.picture_edit_count ?? 0,
            })}
          </div>
        )}
        {bgmTask && (
          <div
            className="min-w-0 flex-1"
            role={bgmTask.status === "failed" ? "alert" : "status"}
            aria-label={t("hyperframes_bgm_task_progress")}
          >
            <div className="flex items-center gap-2 text-[11px] text-[var(--color-text-3)]">
              {(bgmTask.status === "queued" || bgmTask.status === "running" || bgmTask.status === "cancelling") && (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden="true" />
              )}
              <span className="truncate">{bgmStatusText}</span>
              {bgmTask.status === "failed" && bgmTask.error_message && (
                <span className="truncate text-red-400">{bgmTask.error_message}</span>
              )}
            </div>
            {musicProgress?.progress != null && bgmTask.status !== "succeeded" && (
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-emerald-400 transition-[width]"
                  style={{ width: `${Math.max(0, Math.min(100, musicProgress.progress))}%` }}
                />
              </div>
            )}
          </div>
        )}
        <a
          href={studioUrl}
          target="_blank"
          rel="noreferrer"
          className="focus-ring inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] text-[var(--color-text-3)] hover:text-[var(--color-text)]"
        >
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
          {t("hyperframes_open_new_window")}
        </a>
      </div>
      <iframe
        key={`${studioUrl}:${studioRevision}`}
        src={studioUrl}
        title={t("hyperframes_studio_title")}
        className="min-h-0 flex-1 border-0 bg-[#0b0f14]"
        sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
        allow="clipboard-read; clipboard-write; fullscreen"
        allowFullScreen
      />
    </div>
  );
}
