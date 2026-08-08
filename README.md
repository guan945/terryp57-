# terryp57 雪球动态 → Notion 同步

自动管道：每天22:00抓取雪球用户 terryp57 的新帖子，推送到本仓库 inbox/，GitHub Actions 自动写入 Notion 数据库（terryp57雪球动态）。

- inbox/：待同步的帖子数据（JSON）
- processed/：已同步的数据
- state/：Notion 数据库ID缓存
- config/：同步配置（Notion父页面ID等）
- .github/scripts/sync.py：同步脚本
