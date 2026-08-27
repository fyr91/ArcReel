import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import {
  overviewAnalysisKey,
  useOverviewAnalysisStore,
} from "./overview-analysis-store";

describe("overview-analysis-store", () => {
  beforeEach(() => {
    useOverviewAnalysisStore.getState().reset();
    vi.restoreAllMocks();
  });

  it("deduplicates an in-flight request for the same project episode", async () => {
    let resolveAnalysis:
      | ((value: Awaited<ReturnType<typeof API.generateEpisodeOverview>>) => void)
      | undefined;
    const generateEpisodeOverview = vi
      .spyOn(API, "generateEpisodeOverview")
      .mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveAnalysis = resolve;
          }),
      );

    const first = useOverviewAnalysisStore.getState().startAnalysis("course-a", 2);
    const second = useOverviewAnalysisStore.getState().startAnalysis("course-a", 2);

    expect(first).toBe(second);
    expect(generateEpisodeOverview).toHaveBeenCalledTimes(1);
    expect(
      useOverviewAnalysisStore.getState().statuses[overviewAnalysisKey("course-a", 2)],
    ).toBe("running");

    resolveAnalysis?.({ success: true, overview: {} as never });
    await first;
    expect(
      useOverviewAnalysisStore.getState().statuses[overviewAnalysisKey("course-a", 2)],
    ).toBe("succeeded");
  });

  it("releases the busy state after failure so the analysis can be retried", async () => {
    vi.spyOn(API, "generateOverview")
      .mockRejectedValueOnce(new Error("failed"))
      .mockResolvedValueOnce({ success: true, overview: {} as never });

    await expect(
      useOverviewAnalysisStore.getState().startAnalysis("project-a"),
    ).rejects.toThrow("failed");
    expect(
      useOverviewAnalysisStore.getState().statuses[overviewAnalysisKey("project-a")],
    ).toBe("failed");

    await useOverviewAnalysisStore.getState().startAnalysis("project-a");
    expect(API.generateOverview).toHaveBeenCalledTimes(2);
    expect(
      useOverviewAnalysisStore.getState().statuses[overviewAnalysisKey("project-a")],
    ).toBe("succeeded");
  });
});
