import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReferenceVideoUnit } from "@/types";
import { CourseUnitFields } from "./CourseUnitFields";

function unit(unitType: ReferenceVideoUnit["unit_type"]): ReferenceVideoUnit {
  return {
    unit_id: "E1U01",
    unit_type: unitType,
    text: "课程正文",
    duration_seconds: 5,
    transition_to_next: "cut",
    note: null,
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

const commonProps = {
  sceneNames: ["教室"],
  characterNames: ["老师", "演员"],
  actorNames: ["演员"],
  lecturerNames: ["老师"],
  propNames: ["课本"],
  onPatchBookends: vi.fn(),
};

describe("CourseUnitFields", () => {
  it("only lets body units switch between story and explanation", () => {
    const onPatch = vi.fn();
    const { container } = render(
      <CourseUnitFields {...commonProps} unit={unit("story")} onPatch={onPatch} />,
    );
    const typeSelect = container.querySelector("select")!;
    expect(Array.from(typeSelect.options, (option) => option.value)).toEqual(["story", "explanation"]);

    fireEvent.change(typeSelect, { target: { value: "explanation" } });
    expect(onPatch).toHaveBeenCalledWith({ unit_type: "explanation" });
  });

  it("keeps opening and closing types fixed", () => {
    const { container } = render(
      <CourseUnitFields {...commonProps} unit={unit("opening")} onPatch={vi.fn()} />,
    );
    const typeSelect = container.querySelector("select")!;
    expect(typeSelect).toBeDisabled();
    expect(Array.from(typeSelect.options, (option) => option.value)).toEqual(["opening"]);
  });
});
