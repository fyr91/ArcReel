---
status: accepted
---

# 课程视频复用 Reference Video Unit 流程

项目创建只暴露 `drama`、`course`、`ad` 三种 `content_mode`。退役独立的
`narration` 项目模式，也不迁移或兼容该模式的数据。剧情演绎的上传内容固定视为剧本文档，
不再持久化或选择 `source_kind`。课程视频固定使用 `reference_video` 路线，每次上传一份文档
只创建或填充一个 Episode，不做自动分集。

课程视频不建立第二套制作画布。资产确认、Video Unit 文稿编辑、Storyboard Sheet、Keyframes、
版本管理、视频生成、确认和 HyperFrames 自动剪辑均复用现有 Reference Video 组件与服务。
课程模式只扩展以下领域事实：

- 角色资产增加 `course_role`：恰好一位 `main_lecturer`、零到多位
  `guest_lecturer`，其余为 `actor`。讲师仍是角色资产；全局库匹配失败时按普通新角色生成。
- Unit 增加 `opening`、`story`、`explanation`、`closing` 类型；类型由工作流规划，在文稿编辑器中
  以只读 tag 展示。场景、角色和道具不提供独立编辑入口，编辑器按当前正文的 `@[名称]` mention
  实时派生圆形素材预览；台词说话人也进入角色信息组。首尾各一个，位于固定首尾，共用一个场景
  和同一组至少一位角色。
- 第一条 explanation 依赖前一条 story；连续 explanation 依赖前一条 explanation；新 story
  开启新的依赖链。不同 story 链的基础视频可并行生成。
- 先生成并确认 opening/story/closing，再生成 explanation。执行 explanation 时，从直接前置
  视频提取尾帧，并在右下角程序合成带固定边框的 1:1 讲师图，合成结果作为该 Unit 的首帧。
- 所有 Unit 的当前视频版本确认后，才允许进入既有 HyperFrames 导出。HyperFrames 不理解
  课程专属效果，只按 Unit 顺序拼接现有视频；箭头、图标等教学元素不属于此领域模型。

## Consequences

- 课程逻辑集中在结构验证、依赖派生和 explanation 首帧准备，不复制 Reference Video 的编辑、
  生成和导出实现。
- 重新生成视频会清除该 Unit 的确认状态；确认绑定当前版本，切换或恢复版本后必须重新确认。
- Episode 列右上角的添加入口只对课程项目启用，上传成功后沿同一资产解析与 Unit 制作流程继续。
- `narration` 仍可作为单元内部的语音/字幕交付能力名称存在，但不再是可创建的项目模式。
