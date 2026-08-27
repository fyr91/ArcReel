import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "@/stores/app-store";
import { ContextBanner } from "./ContextBanner";

describe("ContextBanner", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
  });

  it("shows the immutable episode focus and its current title", () => {
    render(<ContextBanner episode={3} episodeTitle="关键转折" />);

    expect(screen.getByText("第 3 集 · 关键转折")).toBeInTheDocument();
  });

  it("shows project scope while retaining an optional object focus", () => {
    useAppStore.getState().setFocusedContext({ type: "scene", id: "城门" });
    render(<ContextBanner />);

    expect(screen.getByText("全项目")).toBeInTheDocument();
    expect(screen.getByText("城门")).toBeInTheDocument();
  });
});
