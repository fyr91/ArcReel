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
  it("shows the current episode analysis fields", () => {
    render(<CourseEpisodeOverviewCard overview={overview} />);

    expect(screen.getByRole("heading", { name: "本集概述" })).toBeInTheDocument();
    expect(screen.getByText(overview.synopsis)).toBeInTheDocument();
    expect(screen.getByText(overview.genre)).toBeInTheDocument();
    expect(screen.getByText(overview.theme)).toBeInTheDocument();
    expect(screen.getByText(overview.world_setting)).toBeInTheDocument();
  });

  it("can regenerate the current episode analysis", async () => {
    const onRegenerate = vi.fn().mockResolvedValue(undefined);
    render(<CourseEpisodeOverviewCard overview={overview} onRegenerate={onRegenerate} />);

    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));

    await waitFor(() => expect(onRegenerate).toHaveBeenCalledOnce());
  });
});
