---
name: video-workflow
description: 编排课程视频项目的单文档单集工作流；用户说继续、下一步、查看进度或制作课程视频时使用。
---
<!-- mode: course -->

# 课程视频工作流编排

始终先调用 `mcp__arcreel__get_workflow_plan`，按服务端 `next_action` 推进。课程模式只复用现有参考生视频动作和工具，不自动拆集，不建立课程专用剪辑流程。

## 固定流程

1. 用户在 Episode 栏右上角添加文档；一份文档只绑定一个 Episode。
2. `analyze_assets`：提取角色、场景、道具；角色以 `course_role` 区分一位主讲、零到多位特邀和故事演员。能匹配全局角色则复用，否则新建。
3. `generate_asset_sheets`：沿用现有资产图流程；讲师额外生成 1:1 方形头像衍生图。
4. `prepare_step1`：dispatch `next_action.args.preprocessor` 指定的子任务，产出单集 course video units；不调用 episode planning。
5. `confirm_step1`：展示可编辑的 unit 类型、文稿、场景、角色、道具与讲师，用户确认后继续。
6. `generate_script`：沿用现有 ReferenceVideoScript 生成。
7. 沿用 Storyboard Sheet 与 Keyframes 的生成、编辑和确认。
8. 先并行生成 `opening`、全部 `story`、`closing`，逐条确认视频。
9. 基础视频全部确认后生成 `explanation`。第一条 explanation 使用前一 story 尾帧，连续 explanation 使用前一 explanation 尾帧；程序在右下角合成讲师方形框作为实际首帧。
10. 全部视频生成并确认后，沿用现有 HyperFrames 自动剪辑入口，按 unit 顺序拼接和导出。

课程文稿中的讲解、对白与画外音直接进入 H3/视频 provider prompt，由视频模型原生音轨生成。
工作流不出现 `choose_narration_delivery`，调用 `get_workflow_plan` 或 `generate_video_*` 时都不要传
`narration_delivery`。独立 TTS 与 HyperFrames 后期仍可单独使用，但不参与视频准入和时长求解。

## 结构约束

- 仅一个 opening 和一个 closing，至少一个 story。
- opening 与 closing 共用同一场景、同一组至少一位角色。
- explanation 至少一位 presenter，依赖由 unit 顺序机械派生。
- 不强制生成箭头、图标、文字提醒等教学元素。
- 不为 explanation 定义独立的 HyperFrames 验收或渲染规则；所有视频确认完成即可送剪辑。

批量生成只有服务端返回 `admitted` 才表示任务已入队。逐项结果按 `succeeded`、`failed`、`blocked` 展示；失败或阻塞时报告对应原因并重新查询计划，不把未入队条目当作已完成。
