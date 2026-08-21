# Memo Feedback Service

轻量反馈服务，提供官网反馈提交和管理员处理后台。

## 边界

- SQLite 与图片保存在 `FEEDBACK_DATA_DIR`，不进入 Git。
- 所有 SQL 值均使用 SQLite 参数化绑定；动态查询只拼接代码内固定子句。
- 图片仅接受 JPG/PNG/WebP，服务端验证真实格式并重新编码为 WebP，清除 EXIF。
- 管理接口使用 HttpOnly/Secure/SameSite Cookie，写操作额外校验 CSRF。
- 后台渲染用户内容只使用 `textContent`，不执行用户 HTML。

## 限制

- 标题：5～80字符
- 正文：20～2000字符
- 图片：最多3张，单张5MB，总计10MB
- 联系方式：最多100字符
- 提交频率：同一IP哈希10分钟3次、24小时10次

## 本地测试

```bash
python -m pytest tests/test_feedback_service.py -q
```

## 服务器

```text
服务目录：/opt/memo-feedback/app
数据目录：/var/lib/memo-feedback
监听地址：127.0.0.1:9130
用户页面：https://memo.zhaguzhagu.com/feedback.html
管理后台：https://memo.zhaguzhagu.com/admin/feedback
```

首次运行 `website/部署Memo反馈系统.bat` 时会要求设置管理员账号密码；后续部署保留 `.env`、数据库和上传图片。
