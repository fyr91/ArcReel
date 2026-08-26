---
name: generate-video
description: 为剧本场景或自包含 video unit 生成视频。当用户要求生成、重做或续传视频时使用；支持整集、单项与批量自选。
---

# 生成视频

## 路由

让 MCP 工具读取 `project.json`，按 `generation_mode` × `content_mode` 分派，并校验剧本骨架：

| 生成模式 × 创作类型 | 应有骨架 | 分派 | 输出目录 |
|---|---|---|---|
| `reference_video` × drama / course / ad | `video_units[]` | `task_type="reference_video"` → `execute_reference_video_task` | `reference_videos/{unit_id}.mp4` |
| `storyboard` × drama | `scenes[]` | 同上 | `videos/scene_{scene_id}.mp4` |
| `storyboard` × ad | `shots[]` | 同上 | `videos/scene_{shot_id}.mp4` |

骨架失配时停止入队，按项目生成模式重生成剧本。参考生视频直接消费自包含 `video_units[]`，跳过分镜图。

### 参考生视频

把每个 `video_units[]` 条目视为一次独立生成调用：

- 从 unit 正文（`text`）构造统一书写层 prompt。
- 参考图执行期从正文的 `@[名称]` 按首次提及顺序解析，无特殊排序；有资产图用资产图，否则用该资产的全部原图。
- 让生成预检把 unit 编排时长投影到供应商申请档位。
- 遇到 `needs_replan` 或发声归属问题时停止该 unit，先修复规划内容。
- 整集生成只复用 `generated_assets.video_clip` 明确指向的现行成片；同名孤儿文件不代表该 unit 已完成。

让项目配置、剧本模型与视频能力决定比例、时长和参考图上限，不在调用参数中另写一套数值。

## 工具调用

使用 MCP 工具入队；本 skill 不提供 Python 或 Shell 生成脚本。

| 操作 | 工具 |
|------|------|
| 整集生成（默认操作） | `mcp__arcreel__generate_video_episode({"script": "episode_1.json"})` |
| 断点续传 | `mcp__arcreel__generate_video_episode({"script": "episode_1.json", "resume": true})` |
| 单场景 | `mcp__arcreel__generate_video_scene({"script": "episode_1.json", "scene_id": "E1S01"})` |
| 批量自选 | `mcp__arcreel__generate_video_selected({"script": "episode_1.json", "scene_ids": ["E1S01", "E1S05", "E1S10"]})` |
| 自选 + 续传 | `mcp__arcreel__generate_video_selected({"script": "episode_1.json", "scene_ids": [...], "resume": true})` |
| 全部待处理（独立模式） | `mcp__arcreel__generate_video_all({"script": "episode_1.json"})` |

上表适用于 `drama` 与 `course`：不要传 `narration_delivery`。`ad` 仍按广告工作流要求显式携带该参数。

把 `scene_id` / `scene_ids` 在分镜图生视频解释为分镜 ID，在参考生视频解释为 `unit_id`。集号由剧本元数据或文件名解析。

### MiniMax H3 提示词优化

MiniMax H3 优化前会读取项目唯一的 Unified Video Style；缺失时生成链路自动分析并保存，已有配置不重复分析。用户明确提出无 BGM、ASMR、镜头语言或节奏要求时，先调用 `mcp__arcreel__update_video_style` 更新同一份项目配置，再生成视频。

参考生视频且当前模型为 MiniMax H3 时，生成 worker 会在提交付费视频前自动检查六段式提示词产物：
产物缺失或依据已变时，使用同一次请求的 unit、确认时长、参考图、音频与模型事实自动优化并落盘；
产物仍为 current 时直接复用。此步骤不设人工确认门禁，非 H3 模型不经过此步骤。用户只想预览或单独刷新
提示词时，Agent 仍可调用 `mcp__arcreel__optimize_h3_video_prompts`，但正常视频生成无需预先手动调用。
用户要求修改某个已生成且仍为 current 的 H3 提示词时，调用
`mcp__arcreel__update_h3_video_prompt` 提交完整六段式正文；不要重新优化来覆盖用户的定向编辑。
当用户已经集中审核提示词并要求继续生成时，先用
`mcp__arcreel__confirm_h3_video_prompts` 在一次调用中确认全部目标 unit，再调用同一批目标的视频生成工具；
不要逐 unit 确认，也不要把确认与付费视频提交合并成不可审核的隐式动作。

### 点名重新生成 unit

在参考生视频传 `video_units[].unit_id`：

| 操作 | 工具 |
|------|------|
| 重新生成单个 unit | `mcp__arcreel__generate_video_scene({"script": "episode_1.json", "scene_id": "E1U2"})` |
| 重新生成多个 unit | `mcp__arcreel__generate_video_selected({"script": "episode_1.json", "scene_ids": ["E1U2", "E1U3"]})` |

一次调用完成入队、等待与结果回报：

- 把点名视为强制重做，覆盖已有成片。
- 任一目标已有在途任务时等待其完成，再重做整批目标。
- 只生成剧本中点名的自包含 unit；未命中的 ID 记为 `blocked`，带 `generation_unit_not_found`。
- 点名重做不落 checkpoint，忽略 `resume`。
- 结果按 `requested / succeeded / failed / blocked` 逐 ID 返回，
  结构与问题码见 `.claude/references/generation-results.md`。

### 声音与后期解耦

`drama` 与 `course` 的对白、画外音和解说直接写进 H3/视频 provider prompt，由视频模型的原生音轨生成；
视频请求不接受 `narration_delivery`，也不读取 TTS 音频来决定准入、时长或费用。独立 TTS、剪映、
HyperFrames 等后期能力仍可由用户另行触发，但不属于视频生成主流程。`ad` 保留原有交付选择契约。

### 批量准入与档位确认

视频批量请求是**全有或全无**：准入 `admitted` 时整批入队，`blocked` 或 `confirmation_required` 时
**一个任务都不入队**。Web 与 agent 走同一套准入与同一套请求选择语义，没有 agent 专属的宽松通道。

按 unit 的引用状态选择生效档位，把编排时长投影到能容纳内容的申请档位。申请档位不同于当前视觉时长时
预检返回 `reference_duration_confirmation_required`，逐档位向用户说明涉及的 unit、编排秒数、申请秒数
与变长/变短；确认后经 `confirmed_request_durations`（按 unit_id 记档位）让**原目标集合仍作为一批重发**。
`drama/course` 重发只带档位确认，不带旁白交付参数：

```text
mcp__arcreel__generate_video_episode({"script": "episode_1.json",
                                      "confirmed_request_durations": {"E1U1": 8}})
```

被拒时逐 unit 报告 `unit_id`、`problem.code`、原因与 `problem.action`；通过的 unit 带
`generation_batch_admission_withheld`，其 `blocked_unit_ids` 指出是被谁挡住的，如实说明这层因果。
**不要把整批拆小去先跑通过的那一半**——那既绕开全有或全无，也会重复提交已经付过费的 unit。
能力无法解析时把工具错误作为 blocker，先修复模型能力声明。

### 结果怎么读、怎么说

`task_state`（队列任务）、`provider_checkpoint`（供应商是否已提交）、`artifact_status`（产物
current / stale / missing / blocked）与 workflow 步骤状态互相独立，**分开陈述**：「任务成功」不等于
「当前产物有效」。`provider_checkpoint.submitted` 为真表示供应商侧很可能已计费；任务
`interrupted` 表示没有供应商裁决，一律按 `problem.action` 决定；该情形通常交回
`wait_for_task`（任务可能仍在跑并正常落地），不要自行改成 `retry`。

stale 产物照常可预览、可导出、可参与成片，服务端会复用、不会自动重生；是否重做由用户明确决定。
不自动删除、覆盖或重生任何已付费产物与历史版本。

## 工作流程

1. 加载项目和剧本，确认骨架与生成模式一致。
2. 在分镜图生视频确认分镜图可用；在参考生视频确认 unit 正文非空、编排时长合法。
3. 调用相应 MCP 工具，处理准入拒绝与档位确认；`drama/course` 不询问旁白交付方式。
4. 展示结果，按用户选择点名重做不满意的分镜或 unit。
5. 以工具写回的 `generated_assets.video_clip` 作为成片归属。

## Prompt 构建

让 MCP 工具按生成模式构建 Prompt：

- 分镜图生视频读取 `image_prompt`、`video_prompt` 与分镜图。
- 参考生视频读取 unit 正文（`text`）与编排时长。
- `drama/course` 的对白、画外音和解说随正式提示词直接进入视频 provider。
- 自动应用音频开关、角色发声归属与负面 Prompt 规则。

## 生成前检查

按项目生成模式检查：

- storyboard：每个目标分镜都有可用分镜图，动作与发声内容可执行。
- reference：每个目标 unit 有非空书写层、合法编排时长、单一发声归属，且未标记 `needs_replan`。
- reference：参考图由服务端在执行期从正文 `@[名称]` 的首次提及顺序解析；未登记的提及只产生警告、不阻断入队，让服务端按 `max_reference_images` 裁剪。
- reference：输出路径为 `reference_videos/{unit_id}.mp4`。
