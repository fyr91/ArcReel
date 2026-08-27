import { create } from "zustand";

import { API } from "@/api";

export type OverviewAnalysisStatus = "idle" | "running" | "succeeded" | "failed";

interface OverviewAnalysisState {
  statuses: Record<string, OverviewAnalysisStatus>;
  startAnalysis: (projectName: string, episode?: number) => Promise<void>;
  reset: () => void;
}

/** 项目概览与课程分集共用一个 key 口径；同项目的不同分集必须互不占用。 */
export function overviewAnalysisKey(projectName: string, episode?: number): string {
  return `${projectName}\0${episode ?? "project"}`;
}

export const useOverviewAnalysisStore = create<OverviewAnalysisState>((set) => {
  // Promise 不进入响应式 state：组件只消费状态，协调器负责让同一分析 key 的所有调用方
  // 复用同一个请求。页面卸载不会销毁模块级 store，因此切项目/切集后仍能恢复占用态。
  const inFlight = new Map<string, Promise<void>>();

  return {
    statuses: {},

    startAnalysis: (projectName, episode) => {
      const key = overviewAnalysisKey(projectName, episode);
      const existing = inFlight.get(key);
      if (existing) return existing;

      set((state) => ({
        statuses: { ...state.statuses, [key]: "running" },
      }));

      const request = (
        episode == null
          ? API.generateOverview(projectName)
          : API.generateEpisodeOverview(projectName, episode)
      )
        .then(() => {
          set((state) => ({
            statuses: { ...state.statuses, [key]: "succeeded" },
          }));
        })
        .catch((error: unknown) => {
          set((state) => ({
            statuses: { ...state.statuses, [key]: "failed" },
          }));
          throw error;
        })
        .finally(() => {
          inFlight.delete(key);
        });

      inFlight.set(key, request);
      return request;
    },

    reset: () => set({ statuses: {} }),
  };
});
