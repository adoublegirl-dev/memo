# Memo 官网 Nginx 部署手册

> 适用状态：官网文件和安装包已经上传到服务器，但 Nginx、域名站点、HTTPS 还没有配置。

---

## 1. 部署目标

将 Memo 官网部署到 zhaguzhagu 服务器，并通过以下域名访问：

```text
memo.zhaguzhagu.com
```

官网源文件当前上传目录：

```text
/root/MEMO/guanwang
```

推荐 Nginx 实际读取目录：

```text
/var/www/memo
```

---

## 2. 服务器信息

```text
服务器：zhaguzhagu
IP：156.226.176.68
SSH 端口：22000
账号：root
密码：运行部署脚本时安全输入（不要写入文档或代码）
系统：Ubuntu 22.04.5 LTS
```

---

## 3. 安全边界

本次只允许操作 Memo 官网相关路径：

```text
/root/MEMO/guanwang
/var/www/memo
/etc/nginx/sites-available/memo.zhaguzhagu.com
/etc/nginx/sites-enabled/memo.zhaguzhagu.com
```

不要修改或重启无关项目：

```text
/root/BWKK
/root/shiguangji
/root/GG
Docker selfweb
```

不要清空：

```text
/etc/nginx/sites-enabled/*
/etc/nginx/conf.d/*
```

只能新增 Memo 官网自己的 Nginx 配置。

---

## 4. 登录服务器

```bash
ssh -p 22000 root@156.226.176.68
```

---

## 5. 确认文件已上传

执行：

```bash
ls -lh /root/MEMO/guanwang
ls -lh /root/MEMO/guanwang/assets
ls -lh /root/MEMO/guanwang/downloads
```

应该看到：

```text
/root/MEMO/guanwang/index.html
/root/MEMO/guanwang/boot-visual.html
/root/MEMO/guanwang/assets/memo-bg.png
/root/MEMO/guanwang/downloads/Memo-Setup-latest.exe
/root/MEMO/guanwang/downloads/Memo-Lite-Setup-latest.exe
```

安装包大小大致为：

```text
Memo-Setup-latest.exe      约 232 MB
Memo-Lite-Setup-latest.exe 约 76 MB
```

---

## 6. 同步到 Nginx 推荐目录

不建议让 Nginx 直接读取 `/root` 下的文件，容易出现 403 权限问题。

建议复制到：

```text
/var/www/memo
```

执行：

```bash
mkdir -p /var/www/memo
rsync -av --delete /root/MEMO/guanwang/ /var/www/memo/
chown -R www-data:www-data /var/www/memo
find /var/www/memo -type d -exec chmod 755 {} \;
find /var/www/memo -type f -exec chmod 644 {} \;
```

检查：

```bash
ls -lh /var/www/memo
ls -lh /var/www/memo/assets
ls -lh /var/www/memo/downloads
```

---

## 7. 检查 Nginx 是否安装

```bash
nginx -v
systemctl status nginx --no-pager
```

如果提示 Nginx 未安装：

```bash
apt update
apt install -y nginx
```

如果 Nginx 已安装但未启动：

```bash
systemctl enable nginx
systemctl start nginx
```

---

## 8. 创建 Memo 官网 Nginx 配置

创建配置文件：

```bash
cat > /etc/nginx/sites-available/memo.zhaguzhagu.com <<'EOF'
server {
    listen 80;
    server_name memo.zhaguzhagu.com;

    root /var/www/memo;
    index index.html;

    client_max_body_size 1024m;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /downloads/ {
        alias /var/www/memo/downloads/;
        autoindex off;
        add_header Content-Disposition "attachment";
        add_header Cache-Control "no-cache";
    }

    location ~* \.html$ {
        add_header Cache-Control "no-cache";
    }

    location ~* \.(css|js|png|jpg|jpeg|gif|svg|webp|ico)$ {
        expires 7d;
        add_header Cache-Control "public";
    }
}
EOF
```

---

## 9. 启用站点

```bash
ln -sf /etc/nginx/sites-available/memo.zhaguzhagu.com /etc/nginx/sites-enabled/memo.zhaguzhagu.com
```

检查 Nginx 配置：

```bash
nginx -t
```

如果显示 successful：

```bash
systemctl reload nginx
```

---

## 10. 检查域名 DNS

本地或服务器执行：

```bash
nslookup memo.zhaguzhagu.com
```

期望解析到：

```text
156.226.176.68
```

如果没有解析，需要到域名 DNS 后台新增 A 记录：

```text
主机记录：memo
记录类型：A
记录值：156.226.176.68
```

---

## 11. HTTP 验收

浏览器访问：

```text
http://memo.zhaguzhagu.com/
```

服务器本地也可以测试：

```bash
curl -I http://127.0.0.1 -H "Host: memo.zhaguzhagu.com"
```

期望：

```text
HTTP/1.1 200 OK
```

检查下载链接：

```bash
curl -I http://127.0.0.1/downloads/Memo-Setup-latest.exe -H "Host: memo.zhaguzhagu.com"
curl -I http://127.0.0.1/downloads/Memo-Lite-Setup-latest.exe -H "Host: memo.zhaguzhagu.com"
```

期望：

```text
HTTP/1.1 200 OK
```

---

## 12. 配置 HTTPS

如果 certbot 未安装：

```bash
apt update
apt install -y certbot python3-certbot-nginx
```

申请证书：

```bash
certbot --nginx -d memo.zhaguzhagu.com
```

过程中如果询问是否将 HTTP 重定向到 HTTPS，建议选择：

```text
2: Redirect
```

完成后检查：

```bash
nginx -t
systemctl reload nginx
```

访问：

```text
https://memo.zhaguzhagu.com/
```

---

## 13. 防火墙检查

如果 HTTP / HTTPS 无法访问，检查防火墙。

如果使用 ufw：

```bash
ufw status
ufw allow 80/tcp
ufw allow 443/tcp
```

如果云服务商有安全组，也要放行：

```text
TCP 80
TCP 443
```

不要修改 SSH 端口 22000。

---

## 14. 页面最终验收

访问：

```text
https://memo.zhaguzhagu.com/
```

确认页面特征：

```text
第一屏显示 MEMO
slogan 为：让记忆不再是碎片
MEMO 是透明线框字
背景图只在第一屏
向下滚动后背景图消失
后续页面为深色毛玻璃风格
第二屏有 Memo 图谱效果
下载区有 下载 Full / 下载 Lite
```

---

## 15. 下载链接验收

浏览器访问：

```text
https://memo.zhaguzhagu.com/downloads/Memo-Setup-latest.exe
https://memo.zhaguzhagu.com/downloads/Memo-Lite-Setup-latest.exe
```

文件大小应大致为：

```text
Full：约 232 MB
Lite：约 76 MB
```

---

## 16. 常见问题

### 16.1 访问 403

可能原因：Nginx 没有权限读取文件。

确认是否已经同步到：

```text
/var/www/memo
```

并执行过：

```bash
chown -R www-data:www-data /var/www/memo
find /var/www/memo -type d -exec chmod 755 {} \;
find /var/www/memo -type f -exec chmod 644 {} \;
```

### 16.2 页面还是旧版

尝试：

```text
Ctrl + F5
无痕窗口
https://memo.zhaguzhagu.com/index.html?t=1
```

服务器检查：

```bash
head -40 /var/www/memo/index.html
```

确认是否包含：

```text
让记忆不再是碎片
cover-mark
```

### 16.3 下载 404

检查文件：

```bash
ls -lh /var/www/memo/downloads
```

检查 Nginx 配置：

```nginx
location /downloads/ {
    alias /var/www/memo/downloads/;
}
```

注意 `alias` 末尾的 `/` 必须保留。

### 16.4 HTTPS 申请失败

先确认 DNS 已生效：

```bash
nslookup memo.zhaguzhagu.com
```

并确认 HTTP 能访问：

```text
http://memo.zhaguzhagu.com/
```

然后再执行：

```bash
certbot --nginx -d memo.zhaguzhagu.com
```

---

## 17. 回滚方案

上传脚本会在 `/root/MEMO/guanwang` 下创建备份目录：

```text
/root/MEMO/guanwang/_backup_YYYYMMDD-HHMMSS
```

如果新版有问题，可以先恢复源目录：

```bash
cp -a /root/MEMO/guanwang/_backup_YYYYMMDD-HHMMSS/index.html /root/MEMO/guanwang/index.html
cp -a /root/MEMO/guanwang/_backup_YYYYMMDD-HHMMSS/assets/memo-bg.png /root/MEMO/guanwang/assets/memo-bg.png
cp -a /root/MEMO/guanwang/_backup_YYYYMMDD-HHMMSS/downloads/Memo-Setup-latest.exe /root/MEMO/guanwang/downloads/Memo-Setup-latest.exe
cp -a /root/MEMO/guanwang/_backup_YYYYMMDD-HHMMSS/downloads/Memo-Lite-Setup-latest.exe /root/MEMO/guanwang/downloads/Memo-Lite-Setup-latest.exe
```

然后同步到 Nginx 目录：

```bash
rsync -av --delete /root/MEMO/guanwang/ /var/www/memo/
chown -R www-data:www-data /var/www/memo
systemctl reload nginx
```

---

## 18. 最小执行顺序

如果只需要最短路径，按这个顺序：

```text
1. SSH 登录 156.226.176.68:22000
2. 确认 /root/MEMO/guanwang 文件存在
3. rsync 到 /var/www/memo
4. 创建 /etc/nginx/sites-available/memo.zhaguzhagu.com
5. ln -sf 启用站点
6. nginx -t
7. systemctl reload nginx
8. 配置 DNS：memo → 156.226.176.68
9. 访问 http://memo.zhaguzhagu.com
10. certbot --nginx -d memo.zhaguzhagu.com
11. 访问 https://memo.zhaguzhagu.com
12. 测试 Full / Lite 下载
```

---

## 19. 本次官网文件说明

首页来自本地文件：

```text
D:\个人\Hanako项目文件\Memo_V0.1.0\website\index-glass.html
```

上传到服务器后命名为：

```text
index.html
```

背景图：

```text
assets/memo-bg.png
```

启动图谱：

```text
boot-visual.html
```

下载文件：

```text
downloads/Memo-Setup-latest.exe
downloads/Memo-Lite-Setup-latest.exe
```
