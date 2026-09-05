# T-B5 — 衍生卡片图(`ai-daily cards`)

> 任务来源:`资深架构师优化建议_产品化.md` §#5 · 批次:4(个性化)
> 优先级:P2 · 预估代码量:400~500 行 · 依赖:无(可选 Pillow)

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.5
- **目标**:每条事件一张 1080×1080 可分享卡片图(朋友圈/微博/小红书用)
- **现状**:公众号发布通常会做"每条一张图",但目前要手工从 PDF 截图或重新设计
- **落地后**:
  ```bash
  python main.py cards --date 2026-09-05
  # 生成:data/reports/{date}/cards/01_xxx.png ... 06_xxx.png ...
  python main.py cards --date 2026-09-05 --style dark
  python main.py cards --date 2026-09-05 --only top
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/cards.py`(~300 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/card_templates.py`(~100 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_cards.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `cards` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/requirements.txt`(加 Pillow,标 optional)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **`cards.py`**:用 Pillow 绘制 PNG
   - 模板:头条卡片 / 普通事件卡片 / 关键数据卡片 / 引用金句卡片
   - 1080×1080,带项目品牌水印(弱)
   - 文字超长自动折行,关键数据显式标出
   - 中文字体:`/System/Library/Fonts/PingFang.ttc`(macOS)/ `wqy-zenhei.ttc`(Linux),失败 → 降级 ASCII
2. **`card_templates.py`**:每种模板的画布参数 + 文本布局(jinja2)
3. **CLI**:`python main.py cards --date YYYY-MM-DD [--style light|dark] [--only top] [--template-file PATH]`
4. **可选依赖处理**:`Pillow` 不在 requirements.txt 时,`cards` 子命令给友好提示
5. **测试**(≥5 个):
   - 图片尺寸正确(1080×1080)
   - 文字存在(用 `pytesseract` OCR 可选,或像素直方图比对)
   - 文件可读
   - 字体失败 → 降级 ASCII
   - dark/light 主题切换正常
6. **commit**:`feat(T-B5): shareable card images`

## 验收清单

- [ ] 跑一次 → 生成 N 张 PNG(头条 1 张/事件,关键数据事件再加 1 张)
- [ ] 卡片 1080×1080,带项目品牌水印(弱)
- [ ] 文字超长自动折行,关键数据显式标出
- [ ] dark/light 主题切换正常
- [ ] 字体失败 → 降级 ASCII 不崩
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"卡片图"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-B5): shareable card images`
- [ ] log 完整

## 禁止项

- Pillow 标 optional,缺失时友好提示
- 不要自动 push
- 不要顺手改其他模块

## 失败处理

- Pillow 缺失 → 友好提示,不崩
- 字体缺失 → 降级 ASCII
- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-B5 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
