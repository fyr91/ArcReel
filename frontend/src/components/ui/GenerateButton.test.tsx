import { createElement } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GenerateButton } from "./GenerateButton";

const motionCapture = vi.hoisted(() => ({
  buttonProps: null as Record<string, unknown> | null,
}));

vi.mock("framer-motion", () => {
  const motion = new Proxy(
    {},
    {
      get: (_target, tag: string) =>
        function MotionStub({
          children,
          animate,
          exit,
          initial,
          transition,
          whileHover,
          ...rest
        }: Record<string, unknown> & { children?: React.ReactNode }) {
          if (tag === "button") {
            motionCapture.buttonProps = {
              ...rest,
              animate,
              exit,
              initial,
              transition,
              whileHover,
            };
          }
          return createElement(tag, rest, children);
        },
    },
  );

  return {
    motion,
    AnimatePresence: ({ children }: { children?: React.ReactNode }) => children,
  };
});

describe("GenerateButton", () => {
  it("keeps its label width reserved while entering the loading state", () => {
    const { rerender } = render(
      <GenerateButton onClick={() => {}} label="重新生成故事板" />,
    );

    const idleButton = screen.getByRole("button", { name: "重新生成故事板" });
    expect(
      idleButton.querySelector('.invisible[aria-hidden="true"]'),
    ).toHaveTextContent("生成中...");

    rerender(
      <GenerateButton onClick={() => {}} label="重新生成故事板" loading />,
    );

    const loadingButton = screen.getByRole("button", { name: "生成中..." });
    expect(loadingButton).toBeDisabled();
    expect(
      loadingButton.querySelector('.invisible[aria-hidden="true"]'),
    ).toHaveTextContent("重新生成故事板");
  });

  it("limits the infinite loading transition to opacity", () => {
    render(<GenerateButton onClick={() => {}} loading />);

    expect(motionCapture.buttonProps).not.toHaveProperty("layout");
    expect(motionCapture.buttonProps?.transition).toEqual({
      opacity: { duration: 1.5, repeat: Infinity, ease: "easeInOut" },
      y: { duration: 0.3 },
    });
    expect(motionCapture.buttonProps?.transition).not.toHaveProperty("repeat");
  });
});
