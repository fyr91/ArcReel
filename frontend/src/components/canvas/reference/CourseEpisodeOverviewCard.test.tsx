import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CourseEpisodeOverviewCard } from "./CourseEpisodeOverviewCard";

const overview = {
  synopsis: "介绍景泰蓝从掐丝到点蓝的完整制作流程。",
  genre: "传统工艺",
  theme: "非遗传承",
  world_setting: "北京工艺美术课堂",
};

describe("CourseEpisodeOverviewCard", () => {
  it("shows a confirmed episode analysis and can enter editing", () => {
    render(
      <CourseEpisodeOverviewCard
        projectName="demo"
        overview={overview}
        videoStyle={{
          prompt: "项目统一固定机位风格",
          source: "agent",
          updated_at: "2026-08-28T01:00:00Z",
        }}
        status="confirmed"
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "本集概述" })).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText(overview.synopsis)).toBeInTheDocument();
    expect(screen.getByText(overview.genre)).toBeInTheDocument();
    expect(screen.getByText(overview.theme)).toBeInTheDocument();
    expect(screen.getByText(overview.world_setting)).toBeInTheDocument();
    expect(screen.getByDisplayValue("项目统一固定机位风格")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(screen.getByLabelText("故事梗概")).toHaveValue(overview.synopsis);
  });

  it("opens an AI draft for editing and saves it as confirmed", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <CourseEpisodeOverviewCard
        projectName="demo"
        overview={overview}
        status="draft"
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText("待确认")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("故事梗概"), {
      target: { value: "  人工修订后的课程概述  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并标记完成" }));

    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        ...overview,
        synopsis: "人工修订后的课程概述",
      }),
    );
  });

  it("can regenerate the current episode analysis", async () => {
    const onRegenerate = vi.fn().mockResolvedValue(undefined);
    render(
      <CourseEpisodeOverviewCard
        projectName="demo"
        overview={overview}
        onRegenerate={onRegenerate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));

    await waitFor(() => expect(onRegenerate).toHaveBeenCalledOnce());
  });
});
