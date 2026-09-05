# T-C8 — 跨期对比与趋势(`ai-daily trend`)

> 任务来源:`资深架构师优化建议_产品化.md` §#8 · 批次:3(智能)
> 优先级:P1 · 预估代码量:400~500 行 · 依赖:**T-C7**

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.8
- **目标**:"这周融资热点是哪些公司?""上周 vs 本周头条差异" 一查便知
- **现状**:要看趋势只能手工翻 N 份 PDF
- **落地后**:
  ```bash
  python main.py trend funding --weeks 4
  # 近 4 周融资热点:
  #   1. OpenAI  8 次 · 累计 $32B
  #   2. Anthropic  6 次 · 累计 $18B
  python main.py trend headlines --diff last-week
  # 本周新增头条: + OpenAI GPT-5 编码版
  # 上周头条已下榜: - Meta 开源 Llama 4
  python main.py trend topics --weeks 12
  # 近 12 周话题热度曲线
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/trend.py`(~250 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/cli/trend.py`(~150 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/report/trend_chart.py`(~100 行,Pillow 折线图,可选)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_trend.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `trend` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **`trend.py`** 基于 T-C7 的 SQLite 索引写聚合 SQL:
   - `trend_funding(weeks)`:`SELECT entities.name, COUNT(*), SUM(amount) FROM items JOIN entities ... WHERE category='funding' AND report_date >= date('now', '-N weeks') GROUP BY entities.name ORDER BY COUNT(*) DESC LIMIT 10`
   - `trend_headlines_diff(last_week)`:本周 vs 上周 头条对比(新增/保留/下榜)
   - `trend_topics(weeks)`:按 category 周聚合,产出 (week, category, count) 序列
2. **`cli/trend.py`**:
   - `funding [--weeks N]`:打印 TOP 10
   - `headlines [--diff last-week|prev-week]`:打印差异
   - `topics [--weeks N]`:打印热度序列;`--format chart` → Pillow 折线图(PNG,无 matplotlib)
3. **测试**(≥5 个,基于 mock 数据集):
   - 4 周融资数据 → TOP 10 正确
   - 头条差异正确区分新增/保留/下榜
   - 12 周话题序列正确
   - chart 输出 PNG 尺寸正确
   - 空数据 → 友好提示
4. **commit**:`feat(T-C8): cross-period trend analysis`

## 验收清单

- [ ] `trend funding --weeks 4` 有 4 周数据时返回正确 TOP 列表
- [ ] `trend headlines --diff last-week` 区分新增/保留/下榜 三类
- [ ] `trend topics --weeks 12` 输出话题热度序列
- [ ] `--format chart` 输出 PNG 折线图(可选 Pillow)
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"趋势对比"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-C8): cross-period trend analysis`
- [ ] log 完整

## 禁止项

- 不要新增 matplotlib 依赖(用 Pillow 即可)
- 不要自动 push
- 不要直接改 T-C7 的 schema(只读)

## 失败处理

- T-C7 未完成 → log 写明阻塞点("需要先跑 T-C7")
- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-C8 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
