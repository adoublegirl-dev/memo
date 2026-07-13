# Memo 鏂版満閮ㄧ讲鎵ц璇存槑

> 浠庨浂寮€濮嬶紝10 鍒嗛挓瀹屾垚 Memo 璁板繂绯荤粺閮ㄧ讲銆傞€傜敤浜庝换浣?Windows/macOS 鏈哄櫒銆?

---

## 绗竴姝ワ細Clone 椤圭洰

鎵撳紑缁堢锛?

```bash
git clone https://github.com/adoublegirl-dev/memo.git <椤圭洰璺緞>
cd <椤圭洰璺緞>
```

> 濡傛灉 GitHub 杩炰笉涓婏紝鎵嬪姩寤轰竴涓」鐩枃浠跺す锛屾妸椤圭洰鏂囦欢瑙ｅ帇杩涘幓銆?

---

## 绗簩姝ワ細瀹夎渚濊禆

```bash
pip install -r requirements.txt
pip install "mcp>=1.0"
```

> pip 鎱㈠姞鍥藉唴闀滃儚锛歚pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

---

## 绗笁姝ワ細閰嶇疆鐜

```bash
copy .env.example .env
# 缂栬緫 .env 濉叆浣犵殑 API Key
```

鍦?`.env` 閲屽～鍏ワ細

```env
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_DB_PATH=memo/data/memo.db
MEMO_LOG_LEVEL=INFO
```

---

## 绗洓姝ワ細棣栨杩愯楠岃瘉

```bash
# 涓嬭浇宓屽叆妯″瀷锛堢害 120 MB锛岄娆￠渶鑱旂綉锛?
python -c "from memo.utils.embedding import embedding_model; print('dim:', len(embedding_model.encode('test')))"

# 鍩虹鑷
python scripts/quick_check.py
```

鐪嬪埌 `Phase 0 鍩虹璁炬柦楠岃瘉閫氳繃锛乣 鍗虫垚鍔熴€?

> HuggingFace 涓嬭浇鎱細鍏堣 `$env:HF_ENDPOINT='https://hf-mirror.com'`

---

## 绗簲姝ワ細閰嶇疆 Agent 鎺ュ叆

> 灏嗕笅闈㈠懡浠や腑鐨?`<椤圭洰璺緞>` 鏇挎崲涓轰綘鐨?Memo 瀹為檯鐩綍锛堝 `D:/Memo` 鎴?`/home/user/Memo`锛夈€?

### 5A. HanaAgent

鍦?HanaAgent 璁剧疆 鈫?MCP 涓坊鍔犺繛鎺ュ櫒锛孞SON 閰嶇疆锛?

```json
{
  "name": "memo",
  "transport": "stdio",
  "command": "python",
  "args": ["<椤圭洰璺緞>/scripts/run_mcp.py"]
}
```

### 5B. Claude Desktop

缂栬緫 `%APPDATA%\Claude\claude_desktop_config.json`锛?

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<椤圭洰璺緞>/scripts/run_mcp.py"]
    }
  }
}
```

### 5C. 鍏朵粬 MCP Agent

閫氱敤閰嶇疆锛氭寚鍚?`<椤圭洰璺緞>/scripts/run_mcp.py` 鍗冲彲銆?

---

## 绗叚姝ワ細鍚姩鍚庡彴鏈嶅姟

鍙屽嚮 `start_all.bat`锛圵indows锛夋垨杩愯锛?

```bash
python scripts/memo_dashboard.py   # 鐪嬫澘 鈫?http://localhost:9120
python scripts/memo_watcher.py     # 鍚庡彴瀹堟姢杩涚▼
```

---

## 绗竷姝ワ細楠岃瘉 Agent 鑳借皟 Memo

瀵?Agent 璇达細

> 甯垜鏌ョ湅 Memo 璁板繂绯荤粺鐨勭粺璁′俊鎭?

濡傛灉杩斿洖浜嗕細璇濇暟銆佽蹇嗘暟銆佺壒寰佽瘝鏁帮紝璇存槑鎺ュ叆鎴愬姛銆?

---

## 鏃ュ父鎿嶄綔閫熸煡

| 鎿嶄綔 | 鍛戒护 |
|------|------|
| 涓€閿惎鍔?| 鍙屽嚮 `start_all.bat` |
| 涓€閿仠姝?| 鍙屽嚮 `stop_all.bat` |
| 鏌ョ湅鐪嬫澘 | 娴忚鍣ㄦ墦寮€ `http://localhost:9120` |
| 瀹屾暣鎬ч獙璇?| `python scripts/verify_all.py` |
| 瀵煎叆鍘嗗彶浼氳瘽 | `python scripts/import_sessions.py` |
| 鏇存柊浠ｇ爜 | `git pull` |

---

## 椤圭洰缁撴瀯

```
椤圭洰鏍圭洰褰?
鈹溾攢鈹€ memo/               # 鏍稿績 Python 鍖?
鈹溾攢鈹€ docs/               # 鏂囨。
鈹溾攢鈹€ scripts/            # 鑴氭湰
鈹溾攢鈹€ tests/              # 娴嬭瘯
鈹溾攢鈹€ start_all.bat       # 涓€閿惎鍔?
鈹溾攢鈹€ stop_all.bat        # 涓€閿仠姝?
鈹溾攢鈹€ .env.example        # 閰嶇疆妯℃澘
鈹溾攢鈹€ CHANGELOG.md        # 鐗堟湰璁板綍
鈹斺攢鈹€ README.md           # 椤圭洰璇存槑
```

---

## 娉ㄦ剰浜嬮」

1. **API Key 瀹夊叏**锛歚.env` 宸插湪 `.gitignore` 鎺掗櫎锛屼笉浼氳 push
2. **鏁版嵁搴撳浠?*锛氬鍒?`memo/data/memo.db` 鍗冲彲澶囦唤鍏ㄩ儴璁板繂
3. **澶氭満鍚屾**锛氫唬鐮侀€氳繃 git 鍚屾锛屾暟鎹簱鏂囦欢鎵嬪姩澶嶅埗
4. **鏇存柊浠ｇ爜**锛歚git pull` 鍚庡鏋滀緷璧栧彉浜嗭紝閲嶆柊 `pip install -r requirements.txt`
