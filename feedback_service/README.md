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

本地通过 HTTP 调试管理后台时，需要在测试环境中设置：

```text
FEEDBACK_ALLOW_INSECURE_DEV=1
FEEDBACK_COOKIE_SECURE=0
```

不要在公网或正式环境启用上述配置。

## 运行与部署

1. 复制 `.env.example` 为部署环境配置，设置独立的管理员密码哈希、Session Secret 和 IP Hash Secret。
2. 安装 `feedback_service/requirements.txt`。
3. 仅监听本机回环地址：

```bash
uvicorn feedback_service.app:app --host 127.0.0.1 --port 9130
```

正式环境必须满足以下要求：

- 端口 `9130` 不对公网开放，只允许本机 Nginx 反向代理访问。
- Nginx 必须覆盖客户端传入的 `X-Forwarded-For`，例如使用 `proxy_set_header X-Forwarded-For $remote_addr;`，否则基于 IP 哈希的提交和登录限速可能被伪造请求头绕过。
- 官网启用 HTTPS，并保持 `FEEDBACK_COOKIE_SECURE=1`。
- 升级部署时保留 `.env`、SQLite 数据库和上传图片目录，不要将它们提交到 Git。

推荐目录：

```text
服务目录：/opt/memo-feedback/app
数据目录：/var/lib/memo-feedback
监听地址：127.0.0.1:9130
用户页面：https://memo.zhaguzhagu.com/feedback.html
管理后台：https://memo.zhaguzhagu.com/admin/feedback
```
