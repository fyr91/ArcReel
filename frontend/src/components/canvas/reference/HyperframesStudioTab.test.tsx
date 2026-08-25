import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import type { HyperframesWorkspaceStatus } from "@/types";
import type { TaskItem } from "@/types";
import { useTasksStore } from "@/stores/tasks-store";
import { HyperframesStudioTab } from "./HyperframesStudioTab";

const READY: HyperframesWorkspaceStatus = {
  project_name: "demo",
  episode: 1,
  exists: true,
  workspace_path: "hyperframes/episode_01",
  composition_path: "hyperframes/episode_01/index.html",
  manifest_path: "hyperframes/episode_01/manifest.json",
  studio_status: "ready",
  studio_url: "http://localhost:12507",
  editing_state: "assembly_draft",
  editing_analysis: {
    state: "assembly_draft",
    picture_edit_count: 0,
    source_unit_count: 18,
    video_clip_count: 18,
    timing_changes: 0,
    split_ranges: 0,
    reordered_units: 0,
    overlapping_handoffs: 0,
    retimed_clips: 0,
    visual_treatments: 0,
    audio_automations: 0,
  },
};

describe("HyperframesStudioTab", () => {
  afterEach(() => {
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("embeds the complete official Studio project after starting it", async () => {
    vi.spyOn(API, "startHyperframesStudio").mockResolvedValue(READY);

    render(<HyperframesStudioTab projectName="demo" episode={1} />);

    const frame = await screen.findByTitle("HyperFrames Studio 编辑器");
    expect(frame).toHaveAttribute(
      "src",
      "http://localhost:12507/#project/episode_01",
    );
    expect(frame).toHaveAttribute("sandbox", expect.stringContaining("allow-scripts"));
    expect(screen.getByRole("link", { name: "在新窗口打开" })).toHaveAttribute(
      "href",
      "http://localhost:12507/#project/episode_01",
    );
    expect(screen.getByText("顺序拼接底稿 · 尚未应用 AI 画面剪辑")).toBeInTheDocument();
  });

  it("shows structural evidence after AI picture editing", async () => {
    vi.spyOn(API, "startHyperframesStudio").mockResolvedValue({
      ...READY,
      editing_state: "edited",
      editing_analysis: {
        ...READY.editing_analysis!,
        state: "edited",
        picture_edit_count: 6,
        timing_changes: 4,
        overlapping_handoffs: 2,
      },
    });

    render(<HyperframesStudioTab projectName="demo" episode={1} />);

    expect(await screen.findByText("AI 画面剪辑已应用（6 项证据）")).toBeInTheDocument();
  });

  it("shows the startup error and retries only after user action", async () => {
    const start = vi
      .spyOn(API, "startHyperframesStudio")
      .mockRejectedValueOnce(new Error("node unavailable"))
      .mockResolvedValueOnce(READY);

    render(<HyperframesStudioTab projectName="demo" episode={1} />);

    expect(await screen.findByText("node unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
    expect(await screen.findByTitle("HyperFrames Studio 编辑器")).toBeInTheDocument();
  });

  it("shows async music progress and reloads Studio when the track is attached", async () => {
    vi.spyOn(API, "startHyperframesStudio").mockResolvedValue(READY);
    const task = {
      task_id: "bgm-1",
      project_name: "demo",
      task_type: "hyperframes_bgm",
      media_type: "audio",
      resource_id: "episode_01",
      resource_type: null,
      script_file: null,
      payload: {},
      status: "running",
      result: null,
      error_message: null,
      cancelled_by: null,
      provider_id: "croco",
      provider_job_id: "music-job-1",
      execution_progress: {
        kind: "minimax_music",
        phase: "running",
        provider_status: "running",
        stage: "generating",
        progress: 48,
        can_cancel: true,
        queue_position: 1,
        queue_length: 1,
        queue_ahead: 0,
      },
      source: "agent",
      queued_at: "2026-08-25T00:00:00Z",
      started_at: "2026-08-25T00:00:01Z",
      finished_at: null,
      updated_at: "2026-08-25T00:00:02Z",
    } satisfies TaskItem;
    useTasksStore.setState({ tasks: [task] });

    render(<HyperframesStudioTab projectName="demo" episode={1} />);

    expect(await screen.findByText("正在生成背景音乐 48%")).toBeInTheDocument();
    const firstFrame = await screen.findByTitle("HyperFrames Studio 编辑器");
    useTasksStore.setState({
      tasks: [
        {
          ...task,
          status: "succeeded",
          result: { relative_path: "media/background.mp3" },
          finished_at: "2026-08-25T00:01:00Z",
          updated_at: "2026-08-25T00:01:00Z",
        },
      ],
    });

    expect(await screen.findByText("背景音乐已生成并加入时间线")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTitle("HyperFrames Studio 编辑器")).not.toBe(firstFrame);
    });
  });

  it("shows the provider queue position after the worker has claimed the task", async () => {
    vi.spyOn(API, "startHyperframesStudio").mockResolvedValue(READY);
    useTasksStore.setState({
      tasks: [
        {
          task_id: "bgm-queued",
          project_name: "demo",
          task_type: "hyperframes_bgm",
          media_type: "audio",
          resource_id: "episode_01",
          resource_type: null,
          script_file: null,
          payload: {},
          status: "running",
          result: null,
          error_message: null,
          cancelled_by: null,
          provider_id: "croco",
          provider_job_id: "music-job-queued",
          execution_progress: {
            kind: "minimax_music",
            phase: "queued",
            provider_status: "queued",
            stage: "waiting_for_route",
            progress: 0,
            can_cancel: true,
            queue_position: 2,
            queue_length: 2,
            queue_ahead: 1,
          },
          source: "agent",
          queued_at: "2026-08-25T00:00:00Z",
          started_at: "2026-08-25T00:00:01Z",
          finished_at: null,
          updated_at: "2026-08-25T00:00:02Z",
        },
      ],
    });

    render(<HyperframesStudioTab projectName="demo" episode={1} />);

    expect(await screen.findByText("背景音乐等待生成（队列位置 2）")).toBeInTheDocument();
  });
});
