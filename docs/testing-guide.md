# Memo 测试指南

## 1. 原则

测试必须使用隔离数据库，不能污染 `data/memo.db`。

当前测试配置：

- `test.bat` 会设置 `MEMO_ENV=test`
- pytest fixture 会强制使用 `data/memo_test.db`
- 测试结束后清理 `memo_test.db*`

## 2. 运行测试

```bat
test.bat
```

或：

```bat
set MEMO_ENV=test
pytest
```

## 3. 写入自检

```bat
set MEMO_ENV=test
python scripts\init_db.py --self-test
```

不要在 production 下执行写入自检，除非明确设置：

```bat
set MEMO_ALLOW_PRODUCTION_SELF_TEST=true
python scripts\init_db.py --self-test
```

## 4. Dashboard 构建验证

```bat
npm run build
```

## 5. 发布前检查

```bat
python scripts\doctor.py
python scripts\build_release.py --include-dist
```

## 6. 当前测试覆盖

- Space 创建 / 绑定记忆 / Space recall / 待办绑定
- Space 名称检测
- MCP 工具冒烟测试
- 端到端记忆写入与检索基础流程

后续建议补充：

- 记忆治理 action 测试
- Space 归档 / 恢复 / alias 测试
- build_release 排除敏感文件测试
- doctor pending migration 检测测试
