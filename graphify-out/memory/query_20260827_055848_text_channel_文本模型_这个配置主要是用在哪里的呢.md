---
type: "query"
date: "2026-08-27T05:58:48.219288+00:00"
question: "Text Channel 文本模型 这个配置主要是用在哪里的呢"
contributor: "graphify"
outcome: "useful"
source_nodes: ["TextTaskType", "TEXT_TASK_TIERS", "ConfigResolver", "TextGenerator", "EpisodePlanner"]
---

# Q: Text Channel 文本模型 这个配置主要是用在哪里的呢

## Answer

Expanded from original query via vocab: [text, backend, task, tier, simple, complex, script, overview, planning, style, agent, 分集规划]. Text Channel 配置的是 ArcReel 服务端内置文本生成管道，不是 Agent 对话模型。简单档用于项目概述、风格与视频风格分析、H3 提示词优化等，并因部分任务读取图片而需要 vision 能力；复杂档用于剧本生成、分集规划和 step1 内容抽取与拆分；默认模型是未指定档位时的兜底。解析顺序为项目档位、项目默认、全局档位、全局默认、自动推断。Agent 对话与 subagent 推理由单独的 Agent 供应商配置决定。

## Outcome

- Signal: useful

## Source Nodes

- TextTaskType
- TEXT_TASK_TIERS
- ConfigResolver
- TextGenerator
- EpisodePlanner