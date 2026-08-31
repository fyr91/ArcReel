import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { KeyframePreviewPanel } from "./KeyframePreviewPanel";
import { StoryboardSheetPanel } from "./StoryboardSheetPanel";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import type { ProjectData, ReferenceVideoUnit } from "@/types";

const CONTENT_MODES = ["drama", "course"] as const;

function project(contentMode: (typeof CONTENT_MODES)[number]): ProjectData {
  return {
    title: "Prompt save test",
    content_mode: contentMode,
    style: "",
    episodes: [],
    characters: {},
    scenes: {},
    props: {},
  };
}

function unit(): ReferenceVideoUnit {
  return {
    unit_id: "E1U01",
    text: "@[阿离] 推开门。",
    duration_seconds: 5,
    transition_to_next: "cut",
    note: null,
    storyboard_description: "@[阿离] 站在门前。",
    storyboard_sheet: {
      image_path: "storyboard_sheets/E1U01.png",
      status: "pending_review",
      confirmed_at: null,
    },
    keyframes: [
      {
        keyframe_id: "E1U01K01",
        description: "@[阿离] 伸手触碰门把手。",
        image_path: "keyframes/E1U01K01.png",
      },
    ],
    generated_assets: {
      storyboard_image: null,
      storyboard_last_image: null,
      grid_id: null,
      grid_cell_index: null,
      video_clip: null,
      video_uri: null,
      status: "pending",
      video_generated_at: null,
    },
  };
}

describe("reference visual prompts save before generation", () => {
  beforeEach(() => {
    useTasksStore.setState({
      tasks: [],
      connected: false,
      optimisticActive: new Set(),
      optimisticActiveScriptFile: new Set(),
    });
    useAppStore.setState({ toast: null });
    vi.spyOn(API, "getModelCandidates").mockResolvedValue({
      image: { default: [], buckets: {} },
      provider_names: {},
    } as never);
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      options: { provider_names: {} },
      settings: {},
    } as never);
  });

  describe.each(CONTENT_MODES)("%s content mode", (contentMode) => {
    it("saves an edited keyframe prompt before generating", async () => {
      const current = unit();
      const nextDescription = "@[阿离] 双手推开沉重的木门。";
      useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project(contentMode) });
      const patch = vi.spyOn(API, "patchReferenceKeyframe").mockResolvedValue({
        keyframe: { ...current.keyframes![0], description: nextDescription },
      });
      const generate = vi.spyOn(API, "generateReferenceKeyframe").mockResolvedValue({
        success: true,
        task_id: `keyframe-${contentMode}`,
        deduped: false,
        message: "queued",
      });

      render(
        <KeyframePreviewPanel
          projectName="proj"
          episode={1}
          unit={current}
          scriptFile="episode_1.json"
          onChanged={vi.fn().mockResolvedValue(undefined)}
        />,
      );

      fireEvent.change(screen.getByRole("combobox", { name: /画面描述|Image description/ }), {
        target: { value: nextDescription },
      });
      expect(screen.queryByRole("button", { name: /^(保存|Save)$/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /重新生成关键首帧|Regenerate keyframe/ }));

      await waitFor(() => expect(generate).toHaveBeenCalledOnce());
      expect(patch).toHaveBeenCalledWith("proj", 1, "E1U01K01", {
        description: nextDescription,
      });
      expect(patch.mock.invocationCallOrder[0]).toBeLessThan(generate.mock.invocationCallOrder[0]);
    });

    it("saves an edited storyboard prompt before generating", async () => {
      const current = unit();
      const nextDescription = "@[阿离] 推门进入房间，镜头跟随她向前移动。";
      useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project(contentMode) });
      const patch = vi.spyOn(API, "patchReferenceVideoUnit").mockResolvedValue({
        unit: { ...current, storyboard_description: nextDescription },
      });
      const generate = vi.spyOn(API, "generateReferenceStoryboardSheet").mockResolvedValue({
        success: true,
        task_id: `storyboard-${contentMode}`,
        deduped: false,
        message: "queued",
      });

      render(
        <StoryboardSheetPanel
          projectName="proj"
          episode={1}
          unit={current}
          scriptFile="episode_1.json"
          onChanged={vi.fn().mockResolvedValue(undefined)}
        />,
      );

      fireEvent.change(screen.getByRole("combobox", { name: /故事板(?:图片)?描述|Storyboard description/ }), {
        target: { value: nextDescription },
      });
      expect(screen.queryByRole("button", { name: /^(保存|Save)$/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /重新生成故事板|Regenerate storyboard/ }));

      await waitFor(() => expect(generate).toHaveBeenCalledOnce());
      expect(patch).toHaveBeenCalledWith("proj", 1, "E1U01", {
        storyboard_description: nextDescription,
      });
      expect(patch.mock.invocationCallOrder[0]).toBeLessThan(generate.mock.invocationCallOrder[0]);
    });
  });

  it("does not generate a keyframe when saving its edited prompt fails", async () => {
    const current = unit();
    useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project("drama") });
    vi.spyOn(API, "patchReferenceKeyframe").mockRejectedValue(new Error("save failed"));
    const generate = vi.spyOn(API, "generateReferenceKeyframe");

    render(
      <KeyframePreviewPanel
        projectName="proj"
        episode={1}
        unit={current}
        onChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: /画面描述|Image description/ }), {
      target: { value: "新的关键帧提示词" },
    });
    fireEvent.click(screen.getByRole("button", { name: /重新生成关键首帧|Regenerate keyframe/ }));

    await waitFor(() => expect(useAppStore.getState().toast?.text).toContain("save failed"));
    expect(generate).not.toHaveBeenCalled();
  });

  it("does not generate a storyboard when saving its edited prompt fails", async () => {
    const current = unit();
    useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project("course") });
    vi.spyOn(API, "patchReferenceVideoUnit").mockRejectedValue(new Error("save failed"));
    const generate = vi.spyOn(API, "generateReferenceStoryboardSheet");

    render(
      <StoryboardSheetPanel
        projectName="proj"
        episode={1}
        unit={current}
        onChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: /故事板(?:图片)?描述|Storyboard description/ }), {
      target: { value: "新的故事版提示词" },
    });
    fireEvent.click(screen.getByRole("button", { name: /重新生成故事板|Regenerate storyboard/ }));

    await waitFor(() => expect(useAppStore.getState().toast?.text).toContain("save failed"));
    expect(generate).not.toHaveBeenCalled();
  });

  it("persists and generates with an edited full keyframe prompt", async () => {
    const current = unit();
    useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project("drama") });
    const preview = vi.spyOn(API, "previewReferenceKeyframePrompt").mockResolvedValue({
      prompt: "系统组装的完整 Prompt",
    });
    const patch = vi.spyOn(API, "patchReferenceKeyframe").mockResolvedValue({
      keyframe: current.keyframes![0],
    });
    const generate = vi.spyOn(API, "generateReferenceKeyframe").mockResolvedValue({
      success: true,
      task_id: "full-keyframe",
      deduped: false,
      message: "queued",
    });

    render(
      <KeyframePreviewPanel
        projectName="proj"
        episode={1}
        unit={current}
        onChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /完整 Prompt|Full prompt/ }));
    const editor = await screen.findByRole("textbox", { name: /关键分镜完整 Prompt|Full Keyframe prompt/ });
    expect(preview).toHaveBeenCalledWith(
      "proj",
      1,
      "E1U01K01",
      current.keyframes![0].description,
      {},
    );
    expect(patch).toHaveBeenCalledWith("proj", 1, "E1U01K01", {
      image_prompt_mode: "full_prompt",
      image_full_prompt: "系统组装的完整 Prompt",
    });

    fireEvent.change(editor, { target: { value: "用户修改后的完整 Prompt" } });
    fireEvent.click(screen.getByRole("button", { name: /重新生成关键首帧|Regenerate keyframe/ }));

    await waitFor(() => expect(generate).toHaveBeenCalledOnce());
    expect(patch).toHaveBeenLastCalledWith("proj", 1, "E1U01K01", {
      image_prompt_mode: "full_prompt",
      image_full_prompt: "用户修改后的完整 Prompt",
    });
    expect(patch.mock.invocationCallOrder.at(-1)).toBeLessThan(generate.mock.invocationCallOrder[0]);
  });

  it("restores a Storyboard full prompt and mode from persisted unit data", () => {
    const current = unit();
    current.storyboard_prompt_mode = "full_prompt";
    current.storyboard_full_prompt = "刷新后仍存在的 Storyboard 完整 Prompt";
    useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project("course") });
    const preview = vi.spyOn(API, "previewReferenceStoryboardSheetPrompt");

    render(
      <StoryboardSheetPanel
        projectName="proj"
        episode={1}
        unit={current}
        onChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(
      screen.getByRole("textbox", { name: /故事板完整 Prompt|Full Storyboard prompt/ }),
    ).toHaveValue("刷新后仍存在的 Storyboard 完整 Prompt");
    expect(screen.getByRole("button", { name: /完整 Prompt|Full prompt/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(preview).not.toHaveBeenCalled();
  });

  it("autosaves an edited persisted Storyboard full prompt", async () => {
    const current = unit();
    current.storyboard_prompt_mode = "full_prompt";
    current.storyboard_full_prompt = "已保存全文";
    useProjectsStore.setState({ currentProjectName: "proj", currentProjectData: project("drama") });
    const patch = vi.spyOn(API, "patchReferenceVideoUnit").mockResolvedValue({ unit: current });

    render(
      <StoryboardSheetPanel
        projectName="proj"
        episode={1}
        unit={current}
        onChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: /故事板完整 Prompt|Full Storyboard prompt/ }),
      { target: { value: "自动保存后的全文" } },
    );

    await waitFor(
      () =>
        expect(patch).toHaveBeenCalledWith("proj", 1, "E1U01", {
          storyboard_full_prompt: "自动保存后的全文",
        }),
      { timeout: 1600 },
    );
  });
});
