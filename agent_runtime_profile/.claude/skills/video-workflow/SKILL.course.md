---
name: video-workflow
description: 编排课程视频项目的单文档单集工作流；用户说继续、下一步、查看进度或制作课程视频时使用。
---
<!-- mode: course -->

# 课程视频工作流编排

始终先调用 `mcp__arcreel__get_workflow_plan`，按服务端 `next_action` 推进。课程模式只复用现有参考生视频动作和工具，不自动拆集，不建立课程专用剪辑流程。

## 固定流程

1. 用户在 Episode 栏右上角添加文档；一份文档只绑定一个 Episode。
2. `analyze_episode`：调用 `mcp__arcreel__generate_episode_overview`，只分析 `next_action.args.episode` 绑定的文档。各集可完全无关，禁止读取或回退到其他集剧情。第 1 集首次解析在项目尚无配置时会一并创建统一视频风格；后续集只复用并展示该项目级对象，不重新分析。生成结果是待复核草稿：先向用户展示并允许修改，得到明确确认后把完整四字段与原样 `source_revision` 交给 `mcp__arcreel__confirm_episode_overview`；不得替用户自动确认。
3. `analyze_assets`：严格传入计划给出的 `episode`、单文件 `scope` 和 revision；提取角色、场景、道具。角色以 `course_role` 区分一位主讲、零到多位特邀和故事演员。能匹配全局角色则复用，否则新建。
4. `generate_asset_sheets`：沿用现有资产图流程；讲师额外生成 1:1 方形头像衍生图。
5. `prepare_step1`：dispatch `next_action.args.preprocessor` 指定的子任务，产出单集 course video units；不调用 episode planning。
6. `confirm_step1`：展示可编辑的文稿与时长；unit 类型以只读 tag 展示，场景、角色和道具按文稿
   `@[名称]` mention 实时派生为只读预览。用户通过修改文稿引用改变相关素材，确认后继续。
7. `generate_script`：沿用现有 ReferenceVideoScript 生成。
8. 沿用 Storyboard Sheet 与 Keyframes 的生成、编辑和确认。
9. 先并行生成 `opening`、全部 `story`、`closing`，逐条确认视频。
10. 基础视频全部确认后生成 `explanation`。第一条 explanation 使用前一 story 尾帧，连续 explanation 使用前一 explanation 尾帧；程序在右下角合成讲师方形框作为实际首帧。
11. 全部视频生成并确认后，沿用现有 HyperFrames 自动剪辑入口，按 unit 顺序拼接和导出。

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
