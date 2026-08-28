import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { UnifiedVideoStyleEditor } from "./UnifiedVideoStyleEditor";

describe("UnifiedVideoStyleEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
  });

  it("shows the shared project style and saves a user edit", async () => {
    const updated = {
      prompt: "固定机位为主，节奏舒缓，突出环境声。",
      source: "user" as const,
      updated_at: "2026-08-28T02:00:00Z",
    };
    const update = vi.spyOn(API, "updateVideoStyle").mockResolvedValue({ video_style: updated });
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        content_mode: "course",
        style: "Anime",
        episodes: [],
        characters: {},
        video_style: updated,
      },
      scripts: {},
    });

    render(
      <UnifiedVideoStyleEditor
        projectName="demo"
        videoStyle={{
          prompt: "初始风格",
          source: "agent",
          updated_at: "2026-08-28T01:00:00Z",
        }}
      />,
    );

    const field = screen.getByLabelText("视频风格提示词");
    expect(field).toHaveValue("初始风格");
    fireEvent.change(field, { target: { value: `  ${updated.prompt}  ` } });
    fireEvent.click(screen.getByRole("button", { name: "保存视频风格" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith("demo", { prompt: updated.prompt }));
  });

  it("shows an empty editable field without triggering another analysis", () => {
    const analyze = vi.spyOn(API, "analyzeVideoStyle");

    render(<UnifiedVideoStyleEditor projectName="demo" videoStyle={null} />);

    expect(screen.getByLabelText("视频风格提示词")).toHaveValue("");
    expect(screen.getByRole("button", { name: "保存视频风格" })).toBeDisabled();
    expect(analyze).not.toHaveBeenCalled();
  });
});
