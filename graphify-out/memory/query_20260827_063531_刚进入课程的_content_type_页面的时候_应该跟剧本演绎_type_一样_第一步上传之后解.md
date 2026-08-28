---
type: "query"
date: "2026-08-27T06:35:31.528124+00:00"
question: "刚进入课程的 content type 页面的时候，应该跟剧本演绎 type 一样，第一步上传之后解析；现在课程看着不一样"
contributor: "graphify"
outcome: "useful"
source_nodes: ["OverviewCanvas", "WelcomeCanvas", "CourseEpisodeUploadDialog", "API", "ProjectManager"]
---

# Q: 刚进入课程的 content type 页面的时候，应该跟剧本演绎 type 一样，第一步上传之后解析；现在课程看着不一样

## Answer

Expanded from original query via vocab: [course, drama, content, type, upload, parse, source, review, episode, onboarding]. 根因已定位：课程项目创建时会预建一个 source_file=None 的 Episode 1，而 OverviewCanvas 仅在无 overview 且 episodes 为空时显示 WelcomeCanvas，因此课程项目刚进入就跳过了剧本演绎使用的上传并开始 AI 分析首屏。课程上传还必须走 addCourseEpisode 以维持单文档单集绑定，不能直接照搬通用 source 上传。计划是让空的课程占位集也进入 WelcomeCanvas，复用相同上传和显式分析交互，课程上传仍经课程 Episode 绑定操作；后续新增 Episode 的侧栏入口保留。还需保证欢迎页删除源文件时同步解除课程 Episode 绑定，避免悬空 source_file。

## Outcome

- Signal: useful

## Source Nodes

- OverviewCanvas
- WelcomeCanvas
- CourseEpisodeUploadDialog
- API
- ProjectManager