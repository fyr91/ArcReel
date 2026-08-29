import { create } from "zustand";
import { API } from "@/api";
import type { AssetType } from "@/types/asset";
import type { CompanyAssetSyncJob } from "@/types";

const EMPTY_JOBS: Record<AssetType, CompanyAssetSyncJob | null> = {
  character: null,
  scene: null,
  prop: null,
};

interface CompanyAssetSyncState {
  jobs: Record<AssetType, CompanyAssetSyncJob | null>;
  requestPending: Partial<Record<AssetType, boolean>>;
  autoSyncAttempted: boolean;
  setJob: (type: AssetType, job: CompanyAssetSyncJob | null) => void;
  refresh: (type: AssetType) => Promise<void>;
  start: (type: AssetType) => Promise<CompanyAssetSyncJob>;
  startAllOnce: () => Promise<void>;
  resetAutoSync: () => void;
}

export function isCompanyAssetJobActive(
  job: CompanyAssetSyncJob | null,
): job is CompanyAssetSyncJob & { status: "queued" | "running" } {
  return job?.status === "queued" || job?.status === "running";
}

export const useCompanyAssetSyncStore = create<CompanyAssetSyncState>((set, get) => ({
  jobs: { ...EMPTY_JOBS },
  requestPending: {},
  autoSyncAttempted: false,
  setJob: (type, job) => set((state) => ({ jobs: { ...state.jobs, [type]: job } })),
  refresh: async (type) => {
    const response = await API.getCompanyAssetSyncStatus(type);
    set((state) => ({ jobs: { ...state.jobs, [type]: response.job } }));
  },
  start: async (type) => {
    set((state) => ({ requestPending: { ...state.requestPending, [type]: true } }));
    try {
      const response = await API.syncCompanyAssets(type);
      set((state) => ({ jobs: { ...state.jobs, [type]: response.job } }));
      return response.job;
    } finally {
      set((state) => ({ requestPending: { ...state.requestPending, [type]: false } }));
    }
  },
  startAllOnce: async () => {
    if (get().autoSyncAttempted) return;
    set({ autoSyncAttempted: true });
    const response = await API.syncAllCompanyAssets();
    set((state) => {
      const jobs = { ...state.jobs };
      for (const item of response.jobs) {
        const type = item.job.payload?.asset_type;
        if (type) jobs[type] = item.job;
      }
      return { jobs };
    });
  },
  resetAutoSync: () => set({ autoSyncAttempted: false, jobs: { ...EMPTY_JOBS } }),
}));
