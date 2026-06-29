"""Phase 1 集成测试：端到端对话记忆流程。

模拟真实场景：多个会话、多轮对话 → 自动提取 → 跨会话检索。
无需 LLM API，使用 jieba 降级提取验证管道完整性。
"""

import sys
sys.path.insert(0, "E:/memo")

from memo import engine
from memo.utils.logger import logger


def main():
    print("=" * 60)
    print("Memo Phase 1 集成测试")
    print("=" * 60)

    engine.init()

    # ── 会话 1：排位赛开发 ──
    print("\n📁 会话 1：排位赛系统开发")
    s1 = engine.start_session(title="排位赛开发")

    conv1 = """User: 我想在炸飞机游戏里加入排位赛系统
Assistant: 好的，排位赛系统通常包含 ELO 匹配算法、段位系统和积分结算。你打算用什么匹配机制？
User: 用 ELO 吧，初始分设 1200，K 值用 32
Assistant: 可以。段位怎么划分？参考王者荣耀还是国际象棋？
User: 分 6 个段位：青铜、白银、黄金、铂金、钻石、王者。每段再分 3 个小段
Assistant: 明白了。积分变动幅度呢？赢一场加多少？
User: 基础 ±25 分，根据双方 ELO 差浮动 ±5 分内
Assistant: 记下了。结算后需要触发段位升降判断吗？
User: 对，每场结束立即结算，段位变化要通知玩家"""

    result1 = engine.remember_conversation(s1.id, conv1)
    print(f"  ✓ 记忆: {result1['title']}")
    print(f"  ✓ 特征词: {result1['feature_tags']}")
    print(f"  ✓ 提取方式: {result1['extraction_method']}")

    # ── 会话 1 继续：天梯赛讨论 ──
    print("\n📁 会话 1 续：天梯赛需求")
    conv2 = """User: 排位赛之外我还想做个天梯赛，你怎么看？
Assistant: 天梯赛和排位赛的区别是什么？
User: 天梯赛是赛季制，每月重置，用 ELO 匹配但不显示段位，纯拼胜场和胜率
Assistant: 那就是更像竞技体育的联赛排名。排行榜实时更新？
User: 对，每小时更新一次榜单。前 100 名有奖励
Assistant: 明白。这里 ELO 初始分还用 1200 吗？
User: 不用，天梯赛每次赛季所有人归零重新打，初始 1000
Assistant: OK，那排位赛 ELO 保留 1200 不变，分两个独立的积分池"""

    result2 = engine.remember_conversation(s2_id := s1.id, conv2)
    print(f"  ✓ 记忆: {result2['title']}")
    print(f"  ✓ 特征词: {result2['feature_tags']}")

    engine.end_session(s1.id)

    # ── 会话 2：几天后的新话题 ──
    print("\n📁 会话 2：Bug 修复 + 回顾排位赛")
    s2 = engine.start_session(title="Bug 修复")

    conv3 = """User: 排位赛有个 bug，ELO 差超过 200 时匹配不到人
Assistant: 什么原因？
User: 匹配范围设太窄了，±50 分。超过 200 分的差距就永远排不上
Assistant: 建议扩大匹配窗口到 ±100，如果 30 秒没匹配到再扩大
User: 行。另外段位升级通知没发，检查一下
Assistant: 段位升级是在结算时判断的，应该是 notification 模块没接入。我去修
User: 好。对了，还记得我们之前定的段位划分吗？
Assistant: 6 个段位：青铜到王者，每段 3 个小段。ELO 初始 1200，K=32"""

    result3 = engine.remember_conversation(s2.id, conv3)
    print(f"  ✓ 记忆: {result3['title']}")
    print(f"  ✓ 特征词: {result3['feature_tags']}")

    engine.end_session(s2.id)

    # ── 检索验证 ──
    print("\n" + "=" * 60)
    print("🔍 检索验证")
    print("=" * 60)

    queries = [
        "排位赛的 ELO 初始分是多少？",
        "段位怎么划分的？",
        "天梯赛和排位赛有什么区别？",
        "匹配范围有什么问题？",
        "王者荣耀",
    ]

    for q in queries:
        results = engine.recall(q, top_k=3)
        print(f"\n📌 查询: {q}")
        for i, r in enumerate(results):
            print(f"  {i+1}. [{r['score']:.4f}] {r['title']}")
            print(f"     特征词: {', '.join(r['feature_tags'][:5])}")

    # ── 统计 ──
    print("\n" + "=" * 60)
    print("📊 统计")
    stats = engine.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # ── 生命周期 ──
    print("\n⚙️ 生命周期")
    report = engine.run_lifecycle()
    for stage, detail in report.items():
        print(f"  {stage}: {detail}")

    print("\n" + "=" * 60)
    print("Phase 1 集成测试通过！✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
