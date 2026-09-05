# T-C7 — SQLite 情报数据库(全文检索地基)

> 任务来源:`资深架构师优化建议_产品化.md` §#7 · 批次:1(地基)
> 优先级:P0 · 预估代码量:700~900 行 · 依赖:无
> 影响:`run_daily.py` 渲染完成后自动入库

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.7
- **目标**:日报积累成可检索的本地情报库,`query "OpenAI" --days 30` 一查便知
- **现状**:历史 66 份日报躺在 `data/reports/`,只能翻文件名找
- **落地后**:
  ```bash
  python main.py index build                  # 一次性建索引(扫 data/reports/)
  python main.py index rebuild                # 重新建
  python main.py query "OpenAI" --days 30     # 全文检索
  python main.py query "融资" --category funding
  python main.py query "Claude 4" --importance-min 85
  python main.py stats --since 2026-08-01
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/__init__.py`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/db.py`(~350 行,SQLite + FTS5)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/indexer.py`(~150 行,JSON → DB)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/query.py`(~200 行,CLI 查询层)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_db_indexer.py`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_db_query.py`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `index` / `query` / `stats` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/run_daily.py`(渲染完成后自动写库)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`(加 §"情报检索")
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`(追加第 10 批 T-C7 记录)

## 落地步骤(严格按顺序)

1. **建表 schema**(`db.py`):
   ```sql
   CREATE TABLE reports (
     date TEXT PRIMARY KEY, title TEXT, word_count INT,
     pdf_path TEXT, html_path TEXT, json_path TEXT, indexed_at TEXT
   );
   CREATE TABLE items (
     id INTEGER PRIMARY KEY, report_date TEXT, category TEXT,
     importance INT, title TEXT, summary TEXT, body TEXT,
     FOREIGN KEY(report_date) REFERENCES reports(date)
   );
   CREATE TABLE entities (
     name TEXT, report_date TEXT, mention_count INT,
     PRIMARY KEY(name, report_date)
   );
   CREATE VIRTUAL TABLE items_fts USING fts5(
     title, summary, body, content='items', content_rowid='id',
     tokenize='unicode61 remove_diacritics 2'
   );
   ```
2. **`indexer.py`**:扫 `data/reports/*/daily_*.json`,抽取 report_date / title / summary / items[] → 写库(用 `BEGIN/COMMIT` 包裹,失败回滚)
3. **`query.py`**:CLI 层,实现 `query(keyword, days, category, importance_min, limit=10)`,中文分词靠 `unicode61`
4. **`stats.py`**:实现按公司/栏目/重要性分布聚合 SQL
5. **CLI 注册**:`main.py` 加 `index build/rebuild`、`query` / `stats`
6. **自动入库**:在 `run_daily.py` 渲染完成后调用 `indexer.index_report(json_path)`,失败不阻塞主流程,只 warn
7. **测试**(≥10 个,跨 indexer + query):
   - 空库 → query 返回空列表
   - 1 条 / 5 条跨日 / 关键词命中 / 不命中 / 按栏目 / 按重要性
   - rebuild 后数量正确
   - 中文字符不丢失
   - 事务回滚(故意抛异常 → DB 不写入)
   - 增量:再添加 1 条 → DB 总数 +1
8. **更新文档**:使用实操文档.md 加一节、架构评审与优化计划.md 追加批次记录
9. **commit**:`feat(T-C7): sqlite + fts5 全文检索索引日报`

## 验收清单(可勾选)

- [ ] `python main.py index build` 把 66 份日报全部入库,`data/intel.db` < 50MB
- [ ] `python main.py query "OpenAI" --days 30` 命中条数正确,中文不丢字
- [ ] `python main.py stats --since 2026-08-01` 返回按公司/栏目/重要性分布
- [ ] `python run_daily.py --full` 跑完后自动入库(无需手动 rebuild)
- [ ] `python -m pytest -v` 全绿(123 + N 个,N≥10)
- [ ] 使用实操文档.md 有对应小节
- [ ] 架构评审与优化计划.md 追加批次记录
- [ ] commit 信息:`feat(T-C7): sqlite + fts5 全文检索索引日报`
- [ ] log 落到 `runs/codex/<时间戳>/T-C7.log`,含 diff stat + pytest 末 30 行 + commit hash

## 禁止项

- 不要碰 `data/raw/`、`data/reports/` 已沉淀的 66 份日报 JSON
- 不要修改 `config/app_config.yaml` 的 `ai` 节
- 不要新增 `requirements.txt` 之外的强依赖(SQLite FTS5 是内置)
- 不要自动 push / 不要提交 main 分支
- 不要顺手重构其他模块

## 失败处理

- 任意验收项不通过 → 不要 commit,把失败原因贴 log 后退出
- DB 锁冲突(并发) → 加 5s 退避,3 次后放弃并 warn
- 跑不下去 → log 写明阻塞点 + 报错 traceback

## 完成后输出

```
=== T-C7 Report ===
diff stat:
  app/storage/__init__.py     | 5 ++
  app/storage/db.py           | 320 ++++++++
  app/storage/indexer.py      | 145 ++++
  ...
pytest 末 30 行:
  ==================== 133 passed in 4.32s ====================
commit hash: abc1234
总结: <1 句话>
```
