---
status: accepted
---

# 项目图片模型按制作阶段配置

项目设置不再向创作者暴露图片请求的技术形态（t2i / i2i）。同一制作阶段可能因是否带参考图而
改变请求形态，但它仍应使用用户为该阶段选择的模型。项目级图片覆盖因此改为四个语义槽：
`image_provider_asset`、`image_provider_reference`、`image_provider_storyboard`、
`image_provider_keyframe`。

解析顺序为：请求级显式覆盖 > 项目制作阶段 > 存量项目能力槽 > 项目默认图片模型 > 全局能力槽
> 全局默认图片模型 > 自动推断。存量 `image_provider_t2i/i2i` 仅作兼容回退，不再在项目设置呈现；
全局层仍保留能力槽，用于没有项目制作上下文的调用。Web UI 与 Agent 入口都只负责声明资源/任务
类型，执行层在同一 `ConfigResolver` 中映射制作阶段，避免两套默认值。

Storyboard 包括普通分镜、多宫格分镜和 Video Unit Storyboard Sheet；关键帧包括 Video Unit 关键
首帧；角色、场景、道具、商品资产图属于资产生成。图片编辑继承被编辑资源的制作阶段，不因底层
固定使用 i2i 而切换到另一个用户配置。
