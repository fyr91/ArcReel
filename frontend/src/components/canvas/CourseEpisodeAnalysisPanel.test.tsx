import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useOverviewAnalysisStore } from "@/stores/overview-analysis-store";
import { CourseEpisodeAnalysisPanel } from "./CourseEpisodeAnalysisPanel";

describe("CourseEpisodeAnalysisPanel", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useOverviewAnalysisStore.getState().reset();
    vi.restoreAllMocks();
  });

  it("keeps an episode busy after switching away and back without submitting twice", async () => {
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
    const onComplete = vi.fn().mockResolvedValue(undefined);

    const first = render(
      <CourseEpisodeAnalysisPanel
        projectName="course-a"
        episode={2}
        sourceFile="source/episode-2.txt"
        onComplete={onComplete}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "开始分析本集" }));
    await waitFor(() => expect(generateEpisodeOverview).toHaveBeenCalledTimes(1));
    first.unmount();

    const otherEpisode = render(
      <CourseEpisodeAnalysisPanel
        projectName="course-a"
        episode={3}
        sourceFile="source/episode-3.txt"
        onComplete={onComplete}
      />,
    );
    expect(screen.getByRole("button", { name: "开始分析本集" })).toBeEnabled();
    otherEpisode.unmount();

    const returned = render(
      <CourseEpisodeAnalysisPanel
        projectName="course-a"
        episode={2}
        sourceFile="source/episode-2.txt"
        onComplete={onComplete}
      />,
    );

    const busyButton = screen.getByRole("button", { name: "正在分析…" });
    expect(busyButton).toBeDisabled();
    fireEvent.click(busyButton);
    expect(generateEpisodeOverview).toHaveBeenCalledTimes(1);

    resolveAnalysis?.({ success: true, overview: {} as never });
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    returned.unmount();
  });
});
