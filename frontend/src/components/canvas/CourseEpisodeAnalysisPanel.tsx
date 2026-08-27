import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";

interface CourseEpisodeAnalysisPanelProps {
  projectName: string;
  episode: number;
  sourceFile: string;
  onComplete: () => Promise<unknown>;
}

export function CourseEpisodeAnalysisPanel({
  projectName,
  episode,
  sourceFile,
  onComplete,
}: CourseEpisodeAnalysisPanelProps) {
  const { t } = useTranslation("dashboard");
  const [analyzing, setAnalyzing] = useState(false);

  const analyze = async () => {
    setAnalyzing(true);
    try {
      await API.generateEpisodeOverview(projectName, episode);
      await onComplete();
      useAppStore.getState().pushToast(t("course_episode_analysis_success", { episode }), "success");
    } catch (error) {
      useAppStore.getState().pushToast(
        t("course_episode_analysis_failed", { message: errMsg(error) }),
        "error",
      );
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="w-full max-w-xl rounded-2xl border border-white/10 bg-white/[0.03] p-8 text-center shadow-xl">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
          <Sparkles className="h-6 w-6" aria-hidden="true" />
        </div>
        <h2 className="text-xl font-semibold text-white">
          {t("course_episode_analysis_title", { episode })}
        </h2>
        <p className="mt-3 text-sm leading-6 text-gray-400">
          {t("course_episode_analysis_description")}
        </p>
        <p className="mt-3 truncate text-xs text-gray-500" title={sourceFile}>{sourceFile}</p>
        <button
          type="button"
          disabled={analyzing}
          onClick={() => void analyze()}
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          {analyzing ? t("course_episode_analyzing") : t("course_episode_analyze")}
        </button>
      </div>
    </div>
  );
}
