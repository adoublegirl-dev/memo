# Memo 閮ㄧ讲鎸囧崡

> 璁╀换浣?MCP 鍏煎鐨?AI Agent 鎷ユ湁娲荤殑銆佷細杩涘寲鐨勮蹇嗙郴缁熴€傝但甯冨涔?+ 鎵╂暎婵€娲?+ 缃戠姸璁板繂鍥捐氨 + 浜烘牸寮曟搸銆?

---

## 鏀寔骞冲彴

| Agent | 閰嶇疆鏂瑰紡 |
|-------|---------|
| **HanaAgent** | MCP 閰嶇疆 + Agent 鎻愮ず璇?|
| **Claude Desktop** | `claude_desktop_config.json` |
| **Claude Code (CLI)** | `claude mcp add` |
| **Cursor** | `.cursor/mcp.json` |
| **浠绘剰 MCP Agent** | MCP 鏍囧噯閰嶇疆 |

---

## 绗竴姝ワ細Clone + 瀹夎

```bash
git clone https://github.com/adoublegirl-dev/memo.git <椤圭洰璺緞>
cd <椤圭洰璺緞>

pip install -r requirements.txt
pip install "mcp>=1.0"
```

> pip 鎱㈠姞闀滃儚锛歚pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

> 灏?`<椤圭洰璺緞>` 鏇挎崲涓轰綘鐨?Memo 瀹為檯鐩綍銆?

---

## 绗簩姝ワ細閰嶇疆鐜

```bash
copy .env.example .env
# 缂栬緫 .env 濉叆浣犵殑 API Key
```

濉叆锛圖eepSeek 绀轰緥锛夛細

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
MEMO_EXTRACTION_MODEL=deepseek-v4-flash
MEMO_GATING_MODEL=deepseek-v4-flash
MEMO_DB_PATH=memo/data/memo.db
MEMO_LOG_LEVEL=INFO
```

> 鏃?API Key 涔熻兘璺戯紙jieba 闄嶇骇鎻愬彇锛夛紝鍙槸鎽樿璐ㄩ噺绋嶄綆銆?

---

## 绗笁姝ワ細鍒濆鍖?+ 鑷

```bash
# 鍥藉唴鐢ㄦ埛鍏堣闀滃儚
# Windows: set HF_ENDPOINT=https://hf-mirror.com
# macOS/Linux: export HF_ENDPOINT=https://hf-mirror.com

python scripts/init_db.py
```

鐪嬪埌銆岃嚜妫€閫氳繃锛丮emo 绯荤粺灏辩华銆傘€嶅嵆鎴愬姛銆?

---

## 绗洓姝ワ細閰嶇疆 Agent 鎺ュ叆

### HanaAgent MCP 閰嶇疆

```json
{
  "mcpServers": {
    "memo": {
      "command": "python",
      "args": ["<椤圭洰璺緞>/scripts/run_mcp.py"],
      "env": { "HF_ENDPOINT": "https://hf-mirror.com" }
    }
  }
}
```

### 娉ㄥ叆 Agent 鎻愮ず璇?

澶嶅埗 `AGENT_PROMPT.md`锛堟垨瑙佷笅鏂囧揩閫熺増鏈級鍒板姪鎵嬬殑 System Prompt 涓細

```
## Memo 璁板繂绯荤粺

鍐欏叆璁板繂鏃讹紝鎵ц Python 鑴氭湰锛?
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memo.integration import MemoClient
c = MemoClient()
r = c.remember("鐢ㄦ埛瑕佽鐨勫唴瀹?)
print(r["title"] + " | " + str(r["feature_tags"]))

妫€绱㈣蹇嗭細
c.recall("鏌ヨ鍏抽敭璇?, top_k=5)

姣忔鍐欏叆鍚庡憡鐭ョ敤鎴锋爣棰?鐗瑰緛璇嶅嵆鍙€備笉瑕佺敤 pin_memory銆?
```

---

## 绗簲姝ワ細鍚姩鏈嶅姟

鍙屽嚮 `start_all.bat`锛圵indows锛夛紝鎴栬繍琛岋細

```bash
python scripts/memo_dashboard.py   # 鐪嬫澘 鈫?http://localhost:9120
python scripts/memo_watcher.py     # 鍚庡彴瀹堟姢杩涚▼
```

鍋滄锛氬弻鍑?`stop_all.bat`

---

## 绗叚姝ワ細瀵煎叆鍘嗗彶浼氳瘽锛堝彲閫夛級

濡傛灉鎯虫妸 HanaAgent 杩囧線鐨勮亰澶╄褰曚竴娆℃€у叆搴擄細

### 6.1 瀵煎叆鍓嶅噯澶?

```bash
# 纭繚鏈嶅姟宸插仠姝?
double-click stop_all.bat  # Windows

# 锛堝彲閫夛級娓呯┖鐜版湁娴嬭瘯鏁版嵁
python scripts/_mark_legacy.py
python scripts/_clean_legacy.py
```

### 6.2 鎵ц瀵煎叆

```bash
# Windows: set HF_ENDPOINT=https://hf-mirror.com
python scripts/import_sessions.py --skip-cas
```

- `--skip-cas`锛氳烦杩囬€愭潯鍙樻洿妫€娴嬶紝閫熷害蹇?3-4 鍊?
- 鑴氭湰鑷姩鎵弿 `~/.hanako/agents/hanako/sessions/` 涓嬫墍鏈夊巻鍙蹭細璇?
- 姣忚疆瀵硅瘽锛歁VG 闂ㄦ帶棰勫垽浠峰€?鈫?LLM 鎻愬彇鐗瑰緛璇?鎽樿 鈫?鍐欏叆
- 闂ㄦ帶鑷姩杩囨护闂茶亰锛?鍡ソ鐨?銆?鐭ラ亾浜?绛夛級锛屽彧淇濈暀鏈変环鍊煎唴瀹?

### 6.3 瀵煎叆鍚庡鐞?

瀵煎叆鏃惰烦杩囦簡 CAS 鍙樻洿妫€娴嬶紝闇€瑕佸鍏ュ悗缁熶竴鍋氫竴娆℃壒閲忔壂鎻忥細

```bash
python -c "from memo.core.engine import engine; engine.init(); r=engine.run_lifecycle(); print(r)"
```

杩欎細鎵ц锛氶仐蹇樿“鍑?鈫?consolidation 鈫?CAS 鎵归噺鍙樻洿鎵弿 鈫?蹇収銆?

> 鎵归噺鎵弿姣旈€愭潯瀵规瘮楂樻晥寰楀鈥斺€斿鍏?77 杞彧闇€鍑犲崄绉掞紝鑰岄€愭潯闇€瑕佹暟鐧炬棰濆 LLM 璋冪敤銆?

### 6.4 楠岃瘉瀵煎叆缁撴灉

```bash
# 鍚姩鐪嬫澘锛屾祻瑙堝櫒鎵撳紑 http://localhost:9120
# 鍒囨崲鍒般€屽浘璋辫鍥俱€嶆煡鐪嬬壒寰佽瘝鍏宠仈缃戠粶
```

---

## 鏃ュ父鎿嶄綔閫熸煡

| 鎿嶄綔 | 鍛戒护 |
|------|------|
| 涓€閿惎鍔?| 鍙屽嚮 `start_all.bat` |
| 涓€閿仠姝?| 鍙屽嚮 `stop_all.bat` |
| 鏌ョ湅鐪嬫澘 | `http://localhost:9120` |
| 瀵煎叆鍘嗗彶浼氳瘽 | `python scripts/import_sessions.py --skip-cas` |
| 瀵煎叆鍚庢壒閲?CAS 鎵弿 | `python -c "from memo.core.engine import engine; engine.init(); engine.run_lifecycle()"` |
| 鏍囪鐜版湁鏁版嵁 | `python scripts/_mark_legacy.py` |
| 娓呯悊鏍囪鏁版嵁 | `python scripts/_clean_legacy.py` |
| 鏇存柊浠ｇ爜 | `git pull` |

---

## 鏍稿績鑳藉姏

### MVG 璁板繂浠峰€奸棬鎺?
鍐欏叆鍓?LLM 4 缁磋瘎鍒嗛鍒わ紝鎬诲垎 < 3.0 璺宠繃锛堣繃婊ら棽鑱婏級

### CAS 鍙樻洿鎰熺煡
鍐欏叆鍚庤嚜鍔ㄦ娴嬫槸鍚︽帹缈绘棫浜嬪疄锛屾爣璁版棫璁板繂澶辨晥

### SCB 浼氳瘽鍑濊仛鍔涘姞鎴?
鍚屼細璇濆唴鐗瑰緛璇嶅叧鑱旇竟鏉冮噸鍔犳垚 + 璧竷瀛︿範

### D3.js 鍔涘鍚戝浘
鐪嬫澘銆屽浘璋辫鍥俱€嶅彲瑙嗗寲鐗瑰緛璇嶈妭鐐?+ 璧竷鍏崇郴杈癸紝鐐瑰嚮鑺傜偣楂樹寒閭诲眳 + 鍏宠仈璁板繂

### 浜烘牸寮曟搸锛?0 缁村害锛?
浠庤蹇嗚嚜鍔ㄦ彁鐐?values / decisions / preferences / identity / sensitivity / relationship / knowledge / communication / mental_model / emotion

---

## 閰嶇疆椤归€熸煡

| 鐜鍙橀噺 | 榛樿鍊?| 璇存槑 |
|------|------|------|
| `LLM_API_KEY` | 鈥?| LLM API Key |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | API 鍦板潃 |
| `MEMO_EXTRACTION_MODEL` | `deepseek-v4-flash` | 鎻愬彇鐢ㄦā鍨?|
| `MEMO_GATING_MODEL` | `deepseek-v4-flash` | 闂ㄦ帶鐢ㄦā鍨?|
| `MEMO_DB_PATH` | `memo/data/memo.db` | 鏁版嵁搴撹矾寰?|
| `MEMO_GATING_ENABLED` | `true` | 鍚敤闂ㄦ帶 |
| `MEMO_GATING_THRESHOLD` | `3.0` | 闂ㄦ帶鍐欏叆闃堝€?|
| `MEMO_CHANGE_DETECTION_ENABLED` | `true` | 鍚敤 CAS |
| `MEMO_SESSION_BOOST_ALPHA` | `0.5` | 浼氳瘽鍔犳垚绯绘暟 |
| `MEMO_SESSION_SPREAD_BOOST` | `1.2` | 鎵╂暎鍔犳垚绯绘暟 |

---

## 椤圭洰缁撴瀯

```
椤圭洰鏍圭洰褰?
鈹溾攢鈹€ memo/               # 鏍稿績 Python 鍖?
鈹?  鈹溾攢鈹€ core/           # 寮曟搸 + 閰嶇疆
鈹?  鈹溾攢鈹€ store/          # 鏁版嵁搴?鍥?鍚戦噺
鈹?  鈹溾攢鈹€ models/         # 鏁版嵁妯″瀷
鈹?  鈹溾攢鈹€ extraction/     # LLM 鎻愬彇鍣?+ 闂ㄦ帶 + 鍙樻洿妫€娴?
鈹?  鈹溾攢鈹€ retrieval/      # 涓夐€氶亾妫€绱?+ 铻嶅悎
鈹?  鈹溾攢鈹€ lifecycle/      # 閬楀繕/鍥哄寲/蹇収
鈹?  鈹溾攢鈹€ persona/        # 浜烘牸寮曟搸
鈹?  鈹溾攢鈹€ mcp/            # MCP Server
鈹?  鈹溾攢鈹€ integration/    # MemoClient 鐩存帴璋冪敤
鈹?  鈹斺攢鈹€ utils/          # LLM/宓屽叆/鏃ュ織
鈹溾攢鈹€ scripts/            # 杩愮淮鑴氭湰
鈹溾攢鈹€ docs/               # 鏂囨。
鈹溾攢鈹€ data/               # 鏁版嵁搴撴枃浠?
鈹溾攢鈹€ start_all.bat       # 涓€閿惎鍔?
鈹溾攢鈹€ stop_all.bat        # 涓€閿仠姝?
鈹斺攢鈹€ .env.example        # 閰嶇疆妯℃澘
```

---

## 甯歌闂

### Q: 鏁版嵁搴撹閿佷簡鎬庝箞鍔烇紵

鍏堝仠姝㈡湇鍔★紝鐒跺悗鐢?SQLite 宸ュ叿妫€鏌ユ暟鎹簱瀹屾暣鎬с€傚垏鍕跨洿鎺ュ垹闄?`memo.db` 鏂囦欢銆傚闇€閲嶅缓锛屽厛澶囦唤锛歚copy memo\data\memo.db memo\data\memo.db.backup`锛屽啀杩愯 `python scripts/init_db.py` 閲嶅缓绌哄簱銆?

### Q: LLM 璋冪敤澶辫触锛?

宸插唴缃?3 娆℃寚鏁伴€€閬块噸璇曘€備粛澶辫触浼氳嚜鍔ㄩ檷绾у埌 jieba 鎻愬彇锛屼笉涓㈡暟鎹€傚鍏ュぇ鏁伴噺鏃跺姞 `--skip-cas` 璺宠繃鍙樻洿妫€娴嬶紝瀵煎叆鍚庣粺涓€璺?`run_lifecycle()`銆?

### Q: 鎬庝箞娓呯悊娴嬭瘯鏁版嵁锛?

鍏堣窇 `python scripts/_mark_legacy.py` 鏍囪鐜版湁鏁版嵁锛岀瓑姝ｅ紡鏁版嵁鍏ュ簱鍚庤窇 `python scripts/_clean_legacy.py` 娓呮爣璁版暟鎹€?

### Q: 鏁版嵁瀹夊叏鍚楋紵

鍏ㄩ儴瀛樺偍鍦ㄦ湰鍦?SQLite 鏂囦欢銆侺LM 鎻愬彇鍙紶褰撳墠瀵硅瘽鐗囨锛屼笉浼犲叏閲忓巻鍙层€?

---

> GitHub: https://github.com/adoublegirl-dev/memo
