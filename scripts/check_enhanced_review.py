#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试增强版复盘系统
"""

import sys
import os
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import setup_env, get_config
from src.enhanced_market_analyzer import EnhancedMarketAnalyzer
from src.wechat_formatter import WechatFormatter, PublishPlatform, WechatConfig
from src.logging_config import setup_logging

def test_enhanced_analyzer():
    """测试增强版分析器"""
    print("=" * 80)
    print("测试增强版市场分析器")
    print("=" * 80)
    
    # 创建增强版分析器
    analyzer = EnhancedMarketAnalyzer(region="cn")
    
    # 测试基础市场概览
    print("\n1. 测试基础市场概览...")
    overview = analyzer.get_market_overview()
    print(f"   日期: {overview.date}")
    print(f"   指数数量: {len(overview.indices)}")
    print(f"   上涨家数: {overview.up_count}")
    print(f"   下跌家数: {overview.down_count}")
    print(f"   成交额: {overview.total_amount:.0f}亿")
    
    # 测试情绪分析
    print("\n2. 测试市场情绪分析...")
    sentiment = analyzer.analyze_market_sentiment(overview)
    print(f"   情绪等级: {sentiment.sentiment.value}")
    print(f"   恐慌贪婪指数: {sentiment.fear_greed_index:.1f}/100")
    print(f"   市场热度: {sentiment.market_heat:.1f}/100")
    print(f"   资金流向: {sentiment.fund_flow_trend}")
    
    # 测试板块热点分析
    print("\n3. 测试板块热点分析...")
    hotspots = analyzer.analyze_sector_hotspots(overview)
    print(f"   热点板块数量: {len(hotspots)}")
    for i, hotspot in enumerate(hotspots[:3], 1):
        print(f"   {i}. {hotspot.name}: {hotspot.change_pct:+.2f}% ({hotspot.sustainability})")
        if hotspot.concept_tags:
            print(f"      概念: {', '.join(hotspot.concept_tags)}")
    
    # 测试外界环境分析
    print("\n4. 测试外界环境分析...")
    env = analyzer.analyze_external_environment()
    print(f"   政策面: {env.policy_impact}")
    print(f"   国际市场: {env.international_market}")
    print(f"   宏观数据: {env.macro_data}")
    
    # 测试技术面分析
    print("\n5. 测试技术面分析...")
    tech = analyzer.analyze_technical_aspects(overview)
    print(f"   趋势方向: {tech.trend_direction} {tech.get_trend_emoji()}")
    print(f"   关键支撑: {tech.key_support:.0f}")
    print(f"   关键阻力: {tech.key_resistance:.0f}")
    print(f"   量价关系: {tech.volume_price_relation}")
    
    return analyzer

def test_wechat_formatter():
    """测试公众号格式化器"""
    print("\n" + "=" * 80)
    print("测试公众号格式化器")
    print("=" * 80)
    
    # 模拟报告内容
    test_report = """## 📊 2024-04-02 A股智能复盘

### 🎯 一、市场概况
今日A股市场整体呈现震荡下跌态势，上证指数收跌0.74%，深证成指跌1.60%，创业板指跌2.31%。

> 📊 **市场数据速览**
> 
> 📈 涨跌: **1052** ↑ / **4378** ↓ / **120** → | 涨停: **32** / 跌停: **20**
> 
> 💰 成交额: **18578** 亿 | 情绪指数: **45**/100 (中性)

### 📈 二、情绪解读
市场恐慌贪婪指数为45，处于中性偏恐慌区域，投资者情绪相对谨慎。

> 🎭 **情绪指标**
> 
> 恐慌贪婪指数: **45**/100 | 市场热度: **60**/100
> 
> 资金流向: **存量资金博弈** | 量比: **0.9**

### 🔥 三、热点聚焦
新能源板块表现活跃，油田服务、油服工程等板块领涨。

> 🔥 **热点板块**
> 
> 1. 🚀 **油田服务** +5.2% - 强势突破，关注持续性
>    💡 清洁能源 | 政策支持 | 碳中和
> 2. 📈 **油服工程** +4.1% - 温和上涨，可持续关注
> 3. 🔥 **油气及炼化工程** +3.8% - 涨幅有限，观察为主

### 🌍 四、外围影响
**政策面**: 政策面保持稳定，关注后续政策信号

**国际市场**: 美股期货偏强，亚太市场偏弱，外围市场对A股形成负面影响

### 📊 五、技术研判
**趋势方向**: 震荡整理 🔄

**关键位置**: 支撑 3880 / 阻力 3960

**量价关系**: 价跌量缩，下跌动能减弱

### 💡 六、策略建议
**风险等级**: 中性

**操作建议**: 均衡配置，观察方向

**重点关注**: 优质成长股回调机会，关注政策催化板块

### ⚠️ 七、风险提示
市场有风险，投资需谨慎。本分析仅供参考，不构成投资建议。
"""
    
    # 创建配置
    config = WechatConfig(
        account_name="A股智能分析",
        slogan="AI驱动的股市复盘，让投资更智能",
        use_emoji=True,
        use_dividers=True,
        add_footer=True
    )
    
    # 创建格式化器
    formatter = WechatFormatter(config)
    
    # 测试微信公众号格式
    print("\n1. 测试微信公众号格式...")
    wechat_report = formatter.format_market_review(test_report, PublishPlatform.WECHAT)
    print(f"   格式化后长度: {len(wechat_report)} 字符")
    
    # 测试小红书格式
    print("\n2. 测试小红书格式...")
    xiaohongshu_report = formatter.format_market_review(test_report, PublishPlatform.XIAOHONGSHU)
    print(f"   小红书格式长度: {len(xiaohongshu_report)} 字符")
    
    # 测试标题建议
    print("\n3. 测试标题建议...")
    titles = formatter.create_title_suggestions(test_report)
    for i, title in enumerate(titles, 1):
        print(f"   {i}. {title}")
    
    # 测试摘要生成
    print("\n4. 测试摘要生成...")
    summary = formatter.generate_summary(test_report)
    print(f"   摘要: {summary}")
    
    return wechat_report

def test_full_enhanced_review():
    """测试完整的增强版复盘流程"""
    print("\n" + "=" * 80)
    print("测试完整增强版复盘流程")
    print("=" * 80)
    
    try:
        # 创建增强版分析器
        analyzer = EnhancedMarketAnalyzer(region="cn")
        
        # 运行完整复盘
        print("\n正在运行增强版复盘分析...")
        report = analyzer.run_enhanced_daily_review()
        
        if report:
            print(f"\n✅ 增强版复盘报告生成成功！")
            print(f"   报告长度: {len(report)} 字符")
            
            # 格式化为公众号格式
            formatter = WechatFormatter()
            wechat_report = formatter.format_market_review(report, PublishPlatform.WECHAT)
            
            print(f"   公众号格式长度: {len(wechat_report)} 字符")
            
            # 保存报告到文件
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 保存原始报告
            with open(f'test_enhanced_report_{timestamp}.md', 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"   原始报告已保存: test_enhanced_report_{timestamp}.md")
            
            # 保存公众号格式报告
            with open(f'test_wechat_report_{timestamp}.md', 'w', encoding='utf-8') as f:
                f.write(wechat_report)
            print(f"   公众号报告已保存: test_wechat_report_{timestamp}.md")
            
            return True
        else:
            print("❌ 报告生成失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("🚀 增强版A股复盘系统测试")
    print("=" * 80)
    
    # 设置环境
    setup_env()
    
    # 配置日志
    setup_logging(log_prefix="enhanced_test", debug=True)
    
    # 获取配置
    config = get_config()
    print(f"配置加载完成:")
    print(f"  - 使用增强版复盘: {config.use_enhanced_market_review}")
    print(f"  - 生成公众号格式: {config.generate_wechat_format}")
    print(f"  - 公众号名称: {config.wechat_account_name}")
    
    success_count = 0
    total_tests = 3
    
    try:
        # 测试1: 增强版分析器
        print("\n" + "🧪 测试 1/3: 增强版分析器")
        analyzer = test_enhanced_analyzer()
        if analyzer:
            success_count += 1
            print("✅ 增强版分析器测试通过")
        else:
            print("❌ 增强版分析器测试失败")
    except Exception as e:
        print(f"❌ 增强版分析器测试异常: {e}")
    
    try:
        # 测试2: 公众号格式化器
        print("\n" + "🧪 测试 2/3: 公众号格式化器")
        wechat_report = test_wechat_formatter()
        if wechat_report:
            success_count += 1
            print("✅ 公众号格式化器测试通过")
        else:
            print("❌ 公众号格式化器测试失败")
    except Exception as e:
        print(f"❌ 公众号格式化器测试异常: {e}")
    
    try:
        # 测试3: 完整流程
        print("\n" + "🧪 测试 3/3: 完整增强版复盘流程")
        if test_full_enhanced_review():
            success_count += 1
            print("✅ 完整流程测试通过")
        else:
            print("❌ 完整流程测试失败")
    except Exception as e:
        print(f"❌ 完整流程测试异常: {e}")
    
    # 测试结果汇总
    print("\n" + "=" * 80)
    print("📊 测试结果汇总")
    print("=" * 80)
    print(f"总测试数: {total_tests}")
    print(f"成功数: {success_count}")
    print(f"失败数: {total_tests - success_count}")
    print(f"成功率: {success_count / total_tests * 100:.1f}%")
    
    if success_count == total_tests:
        print("\n🎉 所有测试通过！增强版复盘系统可以正常使用。")
        print("\n📝 使用方法:")
        print("1. 在 .env 中设置 USE_ENHANCED_MARKET_REVIEW=true")
        print("2. 运行 python main.py --market-review")
        print("3. 查看生成的增强版报告和公众号格式报告")
    else:
        print("\n⚠️  部分测试失败，请检查错误信息并修复问题。")
    
    return success_count == total_tests

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)