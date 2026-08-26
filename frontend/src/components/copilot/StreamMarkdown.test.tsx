import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { projectPathFromHref, StreamMarkdown } from "./StreamMarkdown";

vi.mock("@/api", () => ({
  API: {
    revealProjectPath: vi.fn(),
  },
}));

describe("StreamMarkdown project path links", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
  });

  it("recognizes only the reserved same-origin path", () => {
    expect(projectPathFromHref("/__arcreel_open_project_path__?path=videos%2Fclip.mp4"))
      .toBe("videos/clip.mp4");
    expect(projectPathFromHref("https://example.com/__arcreel_open_project_path__?path=videos"))
      .toBeNull();
    expect(projectPathFromHref("/app/projects/demo"))
      .toBeNull();
  });

  it("reveals the validated path through the current project API", async () => {
    vi.mocked(API.revealProjectPath).mockResolvedValue({
      success: true,
      relative_path: "videos/clip.mp4",
      kind: "file",
    });
    render(
      <StreamMarkdown
        content="[打开视频](/__arcreel_open_project_path__?path=videos%2Fclip.mp4)"
        projectName="demo"
      />,
    );

    fireEvent.click(await screen.findByRole("link", { name: "打开视频" }));

    await waitFor(() => {
      expect(API.revealProjectPath).toHaveBeenCalledWith("demo", "videos/clip.mp4");
      expect(useAppStore.getState().toast?.tone).toBe("success");
      expect(useAppStore.getState().toast?.text).toContain("videos/clip.mp4");
    });
  });

  it("reports reveal failures without navigating", async () => {
    vi.mocked(API.revealProjectPath).mockRejectedValue(new Error("file manager unavailable"));
    render(
      <StreamMarkdown
        content="[打开视频](/__arcreel_open_project_path__?path=videos%2Fclip.mp4)"
        projectName="demo"
      />,
    );

    fireEvent.click(await screen.findByRole("link", { name: "打开视频" }));

    await waitFor(() => {
      expect(useAppStore.getState().toast?.tone).toBe("error");
      expect(useAppStore.getState().toast?.text).toContain("file manager unavailable");
    });
  });

  it("does not call the API without an active project", async () => {
    render(
      <StreamMarkdown content="[打开视频](/__arcreel_open_project_path__?path=videos%2Fclip.mp4)" />,
    );

    fireEvent.click(await screen.findByRole("link", { name: "打开视频" }));

    expect(API.revealProjectPath).not.toHaveBeenCalled();
    expect(useAppStore.getState().toast?.tone).toBe("error");
  });
});
