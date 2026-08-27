import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router, useLocation } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData } from "@/types";
import { AssetSidebar } from "./AssetSidebar";

vi.mock("@/stores/cost-store", () => ({
  useCostStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      debouncedFetch: vi.fn(),
      getEpisodeCost: () => null,
    }),
}));

vi.mock("@/onboarding/use-demo-workbench", () => ({
  useDemoWorkbench: () => false,
}));

const courseProject = (episodes: ProjectData["episodes"]): ProjectData => ({
  title: "Course",
  content_mode: "course",
  style: "Anime",
  generation_mode: "reference_video",
  episodes,
  characters: {},
  scenes: {},
  props: {},
  products: {},
});

function LocationProbe() {
  const [location] = useLocation();
  return <output data-testid="location">{location}</output>;
}

describe("AssetSidebar course episode deletion", () => {
  beforeEach(() => {
    useProjectsStore.getState().setCurrentProject(
      "course",
      courseProject([
        { episode: 1, title: "Lesson One", script_file: "scripts/episode_1.json" },
        { episode: 2, title: "Lesson Two", script_file: "scripts/episode_2.json" },
      ]),
      {},
      {},
    );
    vi.spyOn(API, "listFiles").mockResolvedValue({ files: { source: [] } } as never);
  });

  it("previews, confirms, deletes, and navigates away from the removed episode", async () => {
    const user = userEvent.setup();
    vi.spyOn(API, "previewCourseEpisodeDeletion").mockResolvedValue({
      episode: 1,
      title: "Lesson One",
      effects: {
        source_files: 1,
        scripts: 1,
        drafts: 2,
        generated_artifacts: 3,
        workspace_files: 4,
      },
      total_files: 11,
      artifact_claims: 5,
      confirmation_token: "signed-preview",
      expires_in: 300,
    });
    const deleteSpy = vi.spyOn(API, "deleteCourseEpisode").mockResolvedValue({
      success: true,
      episode: 1,
      title: "Lesson One",
      deleted_files: [],
      deleted_file_count: 0,
      removed_artifact_claims: 5,
    });
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: courseProject([
        { episode: 2, title: "Lesson Two", script_file: "scripts/episode_2.json" },
      ]),
      scripts: {},
      asset_fingerprints: {},
    });
    const memory = memoryLocation({ path: "/episodes/1" });
    render(
      <Router hook={memory.hook}>
        <AssetSidebar />
        <LocationProbe />
      </Router>,
    );

    await user.click(screen.getByRole("button", { name: "删除 Episode 1" }));

    expect(API.previewCourseEpisodeDeletion).toHaveBeenCalledWith("course", 1);
    expect(await screen.findByText("删除 Episode 1？")).toBeInTheDocument();
    expect(screen.getByText(/项目与全局资源库/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "确认删除分集" }));

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("course", 1, "signed-preview");
      expect(screen.getByTestId("location")).toHaveTextContent("/episodes/2");
    });
  });
});
