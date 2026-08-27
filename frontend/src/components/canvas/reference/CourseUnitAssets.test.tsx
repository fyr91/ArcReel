import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ProjectData } from "@/types";
import { CourseUnitAssets, deriveCourseUnitAssets } from "./CourseUnitAssets";

const PROJECT: ProjectData = {
  title: "课程",
  content_mode: "course",
  style: "",
  episodes: [],
  characters: {
    学员: { description: "", character_sheet: "characters/student.png", course_role: "actor" },
    老师: {
      description: "",
      character_sheet: "characters/teacher-sheet.png",
      lecturer_portrait: "characters/teacher-portrait.png",
      course_role: "main_lecturer",
    },
  },
  scenes: {
    教室: { description: "", scene_sheet: "scenes/classroom.png" },
    操场: { description: "" },
  },
  props: {
    课本: { description: "", prop_sheet: "props/book.png" },
  },
};

describe("CourseUnitAssets", () => {
  it("derives scene, character, prop, and speaker previews from the manuscript", () => {
    const groups = deriveCourseUnitAssets(
      "@[教室] 里，@[学员] 拿起 @[课本]。@[老师]：{请翻到第一页。}",
      PROJECT,
    );

    expect(groups.scene).toEqual([{ name: "教室", imagePath: "scenes/classroom.png" }]);
    expect(groups.character).toEqual([
      { name: "学员", imagePath: "characters/student.png" },
      { name: "老师", imagePath: "characters/teacher-portrait.png" },
    ]);
    expect(groups.prop).toEqual([{ name: "课本", imagePath: "props/book.png" }]);
  });

  it("renders informational circular previews without editing controls and follows text changes", () => {
    const { rerender } = render(
      <CourseUnitAssets
        projectName="course"
        project={PROJECT}
        text="@[教室] 里，@[学员] 拿起 @[课本]。"
      />,
    );
    const region = screen.getByRole("region", {
      name: /Assets referenced by the script|文稿相关素材/,
    });

    expect(within(region).getByText("教室")).toBeInTheDocument();
    expect(within(region).getByText("学员")).toBeInTheDocument();
    expect(within(region).getByText("课本")).toBeInTheDocument();
    expect(region.querySelectorAll("img.rounded-full")).toHaveLength(3);
    expect(region.querySelector("select, input, button, textarea")).toBeNull();

    rerender(
      <CourseUnitAssets projectName="course" project={PROJECT} text="@[操场] 空无一人。" />,
    );
    expect(within(region).getByText("操场")).toBeInTheDocument();
    expect(within(region).queryByText("教室")).toBeNull();
    expect(within(region).queryByText("学员")).toBeNull();
    expect(within(region).queryByText("课本")).toBeNull();
    expect(region.querySelector("span.rounded-full")).toHaveTextContent("操");
  });
});
