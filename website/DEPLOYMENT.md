# Memo 官网部署说明

## 静态文件

部署目录：

```text
/root/MEMO/guanwang/
```

目录结构：

```text
index.html
boot-visual.html
downloads/
```

## Windows 安装包

官网主下载链接固定为：

```text
downloads/Memo-Desktop-Companion-Setup-latest.exe
```

每次发布新版本时：

1. 上传版本化安装包，例如：

   ```text
   downloads/Memo-Desktop-Companion-Setup-0.9.2-alpha.exe
   ```

2. 更新 `Memo-Desktop-Companion-Setup-latest.exe` 为最新安装包副本。
3. 更新官网页面中的版本说明（如有）。

不要将 `.env`、数据库、备份或用户会话文件上传到官网目录。
