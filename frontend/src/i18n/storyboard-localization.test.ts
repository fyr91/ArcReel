import { describe, expect, it } from "vitest";
import viDashboard from "@/i18n/vi/dashboard";
import viEvents from "@/i18n/vi/events";
import viTemplates from "@/i18n/vi/templates";
import viWorkflow from "@/i18n/vi/workflow";
import zhDashboard from "@/i18n/zh/dashboard";
import zhEvents from "@/i18n/zh/events";
import zhTemplates from "@/i18n/zh/templates";
import zhWorkflow from "@/i18n/zh/workflow";

const FORBIDDEN_ENGLISH_TERMS = /\b(?:Video Unit|Storyboard|Keyframes?|Sheet)\b/i;

function storyboardTranslationValues(
  dashboard: Record<string, string>,
  events: Record<string, string>,
  templates: Record<string, string>,
  workflow: Record<string, string>,
): string[] {
  const dashboardValues = Object.entries(dashboard)
    .filter(([key]) =>
      key.startsWith("reference_storyboard_sheet_")
      || key === "reference_editor_view_storyboard"
      || key === "reference_keyframe_storyboard_gate"
      || key === "reference_keyframe_manuscript_changed_hint"
      || key === "route_reference_video_desc"
      || key === "tool_name_generate_reference_storyboard_sheets",
    )
    .map(([, value]) => value);
  const workflowValues = Object.entries(workflow)
    .filter(
      ([key]) =>
        key.includes("reference_storyboard_sheet")
        || key.includes("video_unit_storyboard_sheet"),
    )
    .map(([, value]) => value);

  return [
    ...dashboardValues,
    ...workflowValues,
    events["label.reference_storyboard_sheet"],
    templates.image_stage_storyboard_label,
    templates.image_stage_storyboard_caption,
  ];
}

describe("视频单元故事板本地化", () => {
  it.each([
    ["zh", storyboardTranslationValues(zhDashboard, zhEvents, zhTemplates, zhWorkflow), "故事板"],
    [
      "vi",
      storyboardTranslationValues(viDashboard, viEvents, viTemplates, viWorkflow),
      "Bảng phân cảnh",
    ],
  ])("%s 文案不残留英文产品名称", (_locale, values, localizedTerm) => {
    expect(values.length).toBeGreaterThan(20);
    expect(
      values.some((value) => value.toLocaleLowerCase().includes(localizedTerm.toLocaleLowerCase())),
    ).toBe(true);
    for (const value of values) {
      expect(value).not.toMatch(FORBIDDEN_ENGLISH_TERMS);
    }
  });
});
