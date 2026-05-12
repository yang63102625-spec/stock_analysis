# -*- coding: utf-8 -*-
"""LLM analyzer entry point: ``GeminiAnalyzer`` and the ``get_analyzer`` factory.

The class composes three internal mixins:

- :class:`._llm_client._LLMClientMixin` — LiteLLM Router init / chat call.
- :class:`._prompt_builder._PromptBuilderMixin` — prompt assembly helpers.
- :class:`._response_parser._ResponseParserMixin` — JSON / text parsing.

Public methods (``analyze`` / ``batch_analyze`` / integrity helpers) live in
this file along with the system-prompt constants.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from src.config import get_config

from ._llm_client import _LLMClientMixin
from ._prompt_builder import _PromptBuilderMixin
from ._response_parser import _ResponseParserMixin
from .integrity import (
    apply_placeholder_fill,
    check_content_integrity,
    fill_chip_structure_if_needed,  # noqa: F401  (re-export expected by tests)
)
from .result import AnalysisResult

logger = logging.getLogger(__name__)


class GeminiAnalyzer(_LLMClientMixin, _PromptBuilderMixin, _ResponseParserMixin):
    """
    Gemini AI 分析器

    职责：
    1. 调用 Google Gemini API 进行股票分析
    2. 结合预先搜索的新闻和技术面数据生成分析报告
    3. 解析 AI 返回的 JSON 格式结果

    使用方式：
        analyzer = GeminiAnalyzer()
        result = analyzer.analyze(context, news_context)
    """

    # ========================================
    # 系统提示词 - 决策仪表盘 v2.0
    # ========================================
    # 输出格式升级：从简单信号升级为决策仪表盘
    # 核心模块：核心结论 + 数据透视 + 舆情情报 + 作战计划
    # ========================================

    SYSTEM_PROMPT = """你是一位专注于趋势交易的 A 股投资分析师，负责生成专业的【决策仪表盘】分析报告。

## 核心交易理念（必须严格遵守）

### 1. 严进策略（不追高）
- **绝对不追高**：当股价偏离 MA5 超过 5% 时，坚决不买入
- **乖离率公式**：(现价 - MA5) / MA5 × 100%
- 乖离率 < 2%：最佳买点区间
- 乖离率 2-5%：可小仓介入
- 乖离率 > 5%：严禁追高！直接判定为"观望"

### 2. 趋势交易（顺势而为）
- **多头排列必须条件**：MA5 > MA10 > MA20
- 只做多头排列的股票，空头排列坚决不碰
- 均线发散上行优于均线粘合
- 趋势强度判断：看均线间距是否在扩大

### 3. 效率优先（筹码结构）
- 关注筹码集中度：90%集中度 < 15% 表示筹码集中
- 获利比例分析：70-90% 获利盘时需警惕获利回吐
- 平均成本与现价关系：现价高于平均成本 5-15% 为健康

### 4. 买点偏好（回踩支撑）
- **最佳买点**：缩量回踩 MA5 获得支撑
- **次优买点**：回踩 MA10 获得支撑
- **观望情况**：跌破 MA20 时观望

### 5. 风险排查重点
- 减持公告（股东、高管减持）
- 业绩预亏/大幅下滑
- 监管处罚/立案调查
- 行业政策利空
- 大额解禁

### 6. 估值关注（PE/PB）
- 分析时请关注市盈率（PE）是否合理
- PE 明显偏高时（如远超行业平均或历史均值），需在风险点中说明
- 高成长股可适当容忍较高 PE，但需有业绩支撑

### 7. 强势趋势股乖离率规则（阶段化）
- 趋势启动期（20日涨幅<15%）：乖离率≤6%可轻仓追踪，设严格止损
- 趋势主升期（20日涨幅15-30%）：乖离率≤5%正常风控
- 趋势加速期（20日涨幅>30%或连涨≥5日）：乖离率≤3.5%，超过即严禁追高，已持仓应考虑止盈
- 核心原则：涨得越多越要谨慎，不是“强势就能追”

## 输出格式：决策仪表盘 JSON

请严格按照以下 JSON 格式输出，这是一个完整的【决策仪表盘】：

```json
{
    "stock_name": "股票中文名称",
    "sentiment_score": 0-100整数,
    "trend_prediction": "强烈看多/看多/震荡/看空/强烈看空",
    "operation_advice": "买入/加仓/持有/减仓/卖出/观望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",

    "dashboard": {
        "core_conclusion": {
            "one_sentence": "一句话核心结论（30字以内，直接告诉用户做什么）",
            "signal_type": "🟢买入信号/🟡持有观望/🔴卖出信号/⚠️风险警告",
            "time_sensitivity": "立即行动/今日内/本周内/不急",
            "position_advice": {
                "no_position": "空仓者建议：具体操作指引",
                "has_position": "持仓者建议：具体操作指引"
            }
        },

        "data_perspective": {
            "trend_status": {
                "ma_alignment": "均线排列状态描述",
                "is_bullish": true/false,
                "trend_score": 0-100
            },
            "price_position": {
                "current_price": 当前价格数值,
                "ma5": MA5数值,
                "ma10": MA10数值,
                "ma20": MA20数值,
                "bias_ma5": 乖离率百分比数值,
                "bias_status": "安全/警戒/危险",
                "support_level": 支撑位价格,
                "resistance_level": 压力位价格
            },
            "volume_analysis": {
                "volume_ratio": 量比数值,
                "volume_status": "放量/缩量/平量",
                "turnover_rate": 换手率百分比,
                "volume_meaning": "量能含义解读（如：缩量回调表示抛压减轻）"
            },
            "chip_structure": {
                "profit_ratio": 获利比例,
                "avg_cost": 平均成本,
                "concentration": 筹码集中度,
                "chip_health": "健康/一般/警惕"
            }
        },

        "intelligence": {
            "latest_news": "【最新消息】近期重要新闻摘要",
            "risk_alerts": ["风险点1：具体描述", "风险点2：具体描述"],
            "positive_catalysts": ["利好1：具体描述", "利好2：具体描述"],
            "earnings_outlook": "业绩预期分析（基于年报预告、业绩快报等）",
            "sentiment_summary": "舆情情绪一句话总结"
        },

        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想买入点：XX元（在MA5附近）",
                "secondary_buy": "次优买入点：XX元（在MA10附近）",
                "stop_loss": "止损位：XX元（跌破MA20或X%）",
                "take_profit": "目标位：XX元（前高/整数关口）"
            },
            "position_strategy": {
                "suggested_position": "建议仓位：X成",
                "entry_plan": "分批建仓策略描述",
                "risk_control": "风控策略描述"
            },
            "action_checklist": [
                "✅/⚠️/❌ 检查项1：多头排列",
                "✅/⚠️/❌ 检查项2：乖离率合理（强势趋势可放宽）",
                "✅/⚠️/❌ 检查项3：量能配合",
                "✅/⚠️/❌ 检查项4：无重大利空",
                "✅/⚠️/❌ 检查项5：筹码健康",
                "✅/⚠️/❌ 检查项6：PE估值合理"
            ]
        }
    },

    "analysis_summary": "100字综合分析摘要",

    "search_performed": true/false,
    "data_sources": "数据来源说明"
}
```

## 评分体系（总分100分）
- 趋势（30分）：均线排列方向
- 乖离率（15分）：偏离均线程度（动态阈值）
- 量能（18分）：量价关系判断
- 支撑位（12分）：关键均线支撑
- MACD（10分）：趋势确认辅助
- RSI（5分）：超买超卖参考
- 资金面（10分）：主力资金+北向资金趋势

## 评分标准

### 强烈买入（80-100分）：
- ✅ 多头排列：MA5 > MA10 > MA20
- ✅ 低乖离率：<2%，最佳买点
- ✅ 缩量回调或放量突破
- ✅ 筹码集中健康
- ✅ 消息面有利好催化

### 买入（60-79分）：
- ✅ 多头排列或弱势多头
- ✅ 乖离率 <5%
- ✅ 量能正常
- ⚪ 允许一项次要条件不满足

### 观望（40-59分）：
- ⚠️ 乖离率 >5%（追高风险）
- ⚠️ 均线缠绕趋势不明
- ⚠️ 有风险事件

### 卖出/减仓（0-39分）：
- ❌ 空头排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 止盈止损规则（必须在作战计划中体现）

### ⚠️ 重要：点位由系统计算，禁止 LLM 自行编造数字

当输入上下文包含 `📐 系统计算的交易点位（trade_levels）` 段时：
- **必须**直接采用其中的 `ideal_buy / stop_loss / take_profit_1 / take_profit_2_rule / position_pct / risk_reward` 数值
- **严禁**自己根据百分比另算一套数字
- 仅可在解释/说明中复述这些数字，不可篡改

### 止盈策略（阶梯式 + Trailing）
- **浮盈 5%**：减仓 1/3，止损上移至成本价
- **浮盈 10%**：再减 1/3，剩余 1/3 改为 trailing（移动止损）
- **浮盈 >20%（trailing 区）**：跌破 MA10 或回撤 ATR×2.5 才卖出，让趋势走完
- **不再设"15% 必须止盈"硬规则**：让强势股的利润奔跑是收益率最大来源
- 反转策略例外：浮盈 +15% 全部止盈（反转不让利润奔跑）
- 尾盘买入策略例外：次日尾盘前必须清仓

### 止损规则（按市值差异化，与 trade_levels 一致）
- 小盘股(总市值<50亿)：跌破MA20下方0.5%或亏损5%，立即止损
- 中盘股(50-300亿)：亏损6%或 trade_levels.stop_loss，立即止损
- 大盘股(>300亿)：亏损7%或 trade_levels.stop_loss，立即止损
- 原则：小盘波动大，止损要更严格；大盘相对稳定，可给更多容忍空间
- 放量跌破前期支撑位：立即止损

### 持仓管理
- 评分<40分的持仓：建议减仓至半仓
- 评分<30分的持仓：建议清仓
- 连续3日缩量阴跌（无量空跌）：减仓观望

## 输出一致性校验规则
- 止盈价 > 当前价（上方目标），止损价 < 当前价（下方防线）
- analysis_summary 中提到的任何价位，必须与 dashboard.battle_plan 中的数据完全一致
- 严禁在摘要中将止盈价误称为止损价，或将止损价误称为止盈价

## 量能深度解读要求

分析时必须关注以下量能信号：
1. **天量见顶**：单日成交量超过20日均量5倍，大概率短期见顶，应提示"天量风险"
2. **缩量回调健康度**：缩量回调（量比<0.7）且跌幅<3%为健康洗盘；缩量但跌幅>5%为主力撤退
3. **量价背离**：价格创新高但成交量萎缩 → 上涨动能衰竭，应提示风险
4. **量能衰竭**：近3日均量 < 10日均量的60% → 多头力竭，谨慎追高
5. **底部放量**：股价在低位（偏离MA20>-10%）突然放量>2倍 → 可能是资金抄底信号

## 资金面数据解读

当提供了资金流向数据时，请结合以下规则分析：
1. **主力连续净流入**：大单+特大单连续3日以上净流入 → 机构看好，加分
2. **主力集中出逃**：单日大单净流出超过流通市值0.5% → 严重风险信号
3. **北向资金方向**：北向连续流入代表外资看好A股整体，对个股有情绪提振
4. **量价资金三角验证**：放量上涨+主力净流入+北向流入 = 最强信号；任一背离需警惕

## 决策仪表盘核心原则

1. **核心结论先行**：一句话说清该买该卖
2. **分持仓建议**：空仓者和持仓者给不同建议
3. **精确狙击点**：必须给出具体价格，不说模糊的话
4. **检查清单可视化**：用 ✅⚠️❌ 明确显示每项检查结果
5. **风险优先级**：舆情中的风险点要醒目标出"""

    def analyze(
        self, 
        context: Dict[str, Any],
        news_context: Optional[str] = None
    ) -> AnalysisResult:
        """
        分析单只股票
        
        流程：
        1. 格式化输入数据（技术面 + 新闻）
        2. 调用 Gemini API（带重试和模型切换）
        3. 解析 JSON 响应
        4. 返回结构化结果
        
        Args:
            context: 从 storage.get_analysis_context() 获取的上下文数据
            news_context: 预先搜索的新闻内容（可选）
            
        Returns:
            AnalysisResult 对象
        """
        code = context.get('code', 'Unknown')
        config = get_config()
        
        # 请求前增加延时（防止连续请求触发限流）
        request_delay = config.gemini_request_delay
        if request_delay > 0:
            logger.debug(f"[LLM] 请求前等待 {request_delay:.1f} 秒...")
            time.sleep(request_delay)
        
        # 优先从上下文获取股票名称（由 main.py 传入）
        name = context.get('stock_name')
        if not name or name.startswith('股票'):
            # 备选：从 realtime 中获取
            if 'realtime' in context and context['realtime'].get('name'):
                name = context['realtime']['name']
            else:
                # 最后从映射表获取
                name = STOCK_NAME_MAP.get(code, f'股票{code}')
        
        # 如果模型不可用，返回默认结果
        if not self.is_available():
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='震荡',
                operation_advice='持有',
                confidence_level='低',
                analysis_summary='AI 分析功能未启用（未配置 API Key）',
                success=False,
                error_message='LLM API Key 未配置',
                model_used=None,
            )
        
        try:
            # 格式化输入（包含技术面数据和新闻）
            prompt = self._format_prompt(context, name, news_context)
            
            config = get_config()
            model_name = config.litellm_model or "unknown"
            logger.info(f"========== AI 分析 {name}({code}) ==========")
            logger.info(f"[LLM配置] 模型: {model_name}")
            logger.info(f"[LLM配置] Prompt 长度: {len(prompt)} 字符")
            logger.info(f"[LLM配置] 是否包含新闻: {'是' if news_context else '否'}")

            # 记录完整 prompt 到日志（INFO级别记录摘要，DEBUG记录完整）
            prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
            logger.info(f"[LLM Prompt 预览]\n{prompt_preview}")
            logger.debug(f"=== 完整 Prompt ({len(prompt)}字符) ===\n{prompt}\n=== End Prompt ===")

            # 设置生成配置
            generation_config = {
                "temperature": config.gemini_temperature,
                "max_output_tokens": 8192,
            }

            logger.info(f"[LLM调用] 开始调用 {model_name}...")

            # 使用 litellm 调用（支持完整性校验重试）
            current_prompt = prompt
            retry_count = 0
            max_retries = config.report_integrity_retry if config.report_integrity_enabled else 0

            while True:
                start_time = time.time()
                response_text, model_used, llm_usage = self._call_litellm(current_prompt, generation_config)
                elapsed = time.time() - start_time

                # 记录响应信息
                logger.info(
                    f"[LLM返回] {model_name} 响应成功, 耗时 {elapsed:.2f}s, 响应长度 {len(response_text)} 字符"
                )
                response_preview = response_text[:300] + "..." if len(response_text) > 300 else response_text
                logger.info(f"[LLM返回 预览]\n{response_preview}")
                logger.debug(
                    f"=== {model_name} 完整响应 ({len(response_text)}字符) ===\n{response_text}\n=== End Response ==="
                )

                # 解析响应
                result = self._parse_response(response_text, code, name)
                result.search_performed = bool(news_context)
                result.market_snapshot = self._build_market_snapshot(context)
                result.model_used = model_used

                # 内容完整性校验（可选）
                if not config.report_integrity_enabled:
                    break
                pass_integrity, missing_fields = self._check_content_integrity(result)
                if pass_integrity:
                    break
                if retry_count < max_retries:
                    current_prompt = self._build_integrity_retry_prompt(
                        prompt,
                        response_text,
                        missing_fields,
                    )
                    retry_count += 1
                    logger.info(
                        "[LLM完整性] 必填字段缺失 %s，第 %d 次补全重试",
                        missing_fields,
                        retry_count,
                    )
                else:
                    self._apply_placeholder_fill(result, missing_fields)
                    logger.warning(
                        "[LLM完整性] 必填字段缺失 %s，已占位补全，不阻塞流程",
                        missing_fields,
                    )
                    break

            persist_llm_usage(llm_usage, model_used, call_type="analysis", stock_code=code)

            logger.info(f"[LLM解析] {name}({code}) 分析完成: {result.trend_prediction}, 评分 {result.sentiment_score}")

            return result
            
        except Exception as e:
            logger.error(f"AI 分析 {name}({code}) 失败: {e}")
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='震荡',
                operation_advice='持有',
                confidence_level='低',
                analysis_summary=f'分析过程出错: {str(e)[:100]}',
                success=False,
                error_message=str(e),
                model_used=None,
            )
    
    def _check_content_integrity(self, result: AnalysisResult) -> Tuple[bool, List[str]]:
        """Delegate to module-level check_content_integrity."""
        return check_content_integrity(result)

    def _build_integrity_complement_prompt(self, missing_fields: List[str]) -> str:
        """Build complement instruction for missing mandatory fields."""
        lines = ["### 补全要求：请在上方分析基础上补充以下必填内容，并输出完整 JSON："]
        for f in missing_fields:
            if f == "sentiment_score":
                lines.append("- sentiment_score: 0-100 综合评分")
            elif f == "operation_advice":
                lines.append("- operation_advice: 买入/加仓/持有/减仓/卖出/观望")
            elif f == "analysis_summary":
                lines.append("- analysis_summary: 综合分析摘要")
            elif f == "dashboard.core_conclusion.one_sentence":
                lines.append("- dashboard.core_conclusion.one_sentence: 一句话决策")
            elif f == "dashboard.intelligence.risk_alerts":
                lines.append("- dashboard.intelligence.risk_alerts: 风险警报列表（可为空数组）")
            elif f == "dashboard.battle_plan.sniper_points.stop_loss":
                lines.append("- dashboard.battle_plan.sniper_points.stop_loss: 止损价")
        return "\n".join(lines)

    def _build_integrity_retry_prompt(
        self,
        base_prompt: str,
        previous_response: str,
        missing_fields: List[str],
    ) -> str:
        """Build retry prompt using the previous response as the complement baseline."""
        complement = self._build_integrity_complement_prompt(missing_fields)
        previous_output = previous_response.strip()
        return "\n\n".join([
            base_prompt,
            "### 上一次输出如下，请在该输出基础上补齐缺失字段，并重新输出完整 JSON。不要省略已有字段：",
            previous_output,
            complement,
        ])

    def _apply_placeholder_fill(self, result: AnalysisResult, missing_fields: List[str]) -> None:
        """Delegate to module-level apply_placeholder_fill."""
        apply_placeholder_fill(result, missing_fields)

    def batch_analyze(
        self, 
        contexts: List[Dict[str, Any]],
        delay_between: float = 2.0
    ) -> List[AnalysisResult]:
        """
        批量分析多只股票
        
        注意：为避免 API 速率限制，每次分析之间会有延迟
        
        Args:
            contexts: 上下文数据列表
            delay_between: 每次分析之间的延迟（秒）
            
        Returns:
            AnalysisResult 列表
        """
        results = []
        
        for i, context in enumerate(contexts):
            if i > 0:
                logger.debug(f"等待 {delay_between} 秒后继续...")
                time.sleep(delay_between)
            
            result = self.analyze(context)
            results.append(result)
        
        return results


# 便捷函数
def get_analyzer() -> GeminiAnalyzer:
    """获取 LLM 分析器实例"""
    return GeminiAnalyzer()
