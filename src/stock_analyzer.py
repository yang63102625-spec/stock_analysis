# -*- coding: utf-8 -*-
"""
===================================
趋势交易分析器 - 基于用户交易理念
===================================

交易理念核心原则：
1. 严进策略 - 不追高，追求每笔交易成功率
2. 趋势交易 - MA5>MA10>MA20 多头排列，顺势而为
3. 效率优先 - 关注筹码结构好的股票
4. 买点偏好 - 在 MA5/MA10 附近回踩买入

技术标准：
- 多头排列：MA5 > MA10 > MA20
- 乖离率：(Close - MA5) / MA5 < 5%（不追高）
- 量能形态：缩量回调优先
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List
from enum import Enum

import pandas as pd
import numpy as np


logger = logging.getLogger(__name__)


class TrendStatus(Enum):
    """趋势状态枚举"""
    STRONG_BULL = "强势多头"      # MA5 > MA10 > MA20，且间距扩大
    BULL = "多头排列"             # MA5 > MA10 > MA20
    WEAK_BULL = "弱势多头"        # MA5 > MA10，但 MA10 < MA20
    CONSOLIDATION = "盘整"        # 均线缠绕
    WEAK_BEAR = "弱势空头"        # MA5 < MA10，但 MA10 > MA20
    BEAR = "空头排列"             # MA5 < MA10 < MA20
    STRONG_BEAR = "强势空头"      # MA5 < MA10 < MA20，且间距扩大


class VolumeStatus(Enum):
    """量能状态枚举"""
    HEAVY_VOLUME_UP = "放量上涨"       # 量价齐升
    HEAVY_VOLUME_DOWN = "放量下跌"     # 放量杀跌
    SHRINK_VOLUME_UP = "缩量上涨"      # 无量上涨
    SHRINK_VOLUME_DOWN = "缩量回调"    # 缩量回调（好）
    NORMAL = "量能正常"


class BuySignal(Enum):
    """买入信号枚举"""
    STRONG_BUY = "强烈买入"       # 多条件满足
    BUY = "买入"                  # 基本条件满足
    HOLD = "持有"                 # 已持有可继续
    WAIT = "观望"                 # 等待更好时机
    SELL = "卖出"                 # 趋势转弱
    STRONG_SELL = "强烈卖出"      # 趋势破坏


class MACDStatus(Enum):
    """MACD状态枚举"""
    GOLDEN_CROSS_ZERO = "零轴上金叉"      # DIF上穿DEA，且在零轴上方
    GOLDEN_CROSS = "金叉"                # DIF上穿DEA
    BULLISH = "多头"                    # DIF>DEA>0
    CROSSING_UP = "上穿零轴"             # DIF上穿零轴
    CROSSING_DOWN = "下穿零轴"           # DIF下穿零轴
    BEARISH = "空头"                    # DIF<DEA<0
    DEATH_CROSS = "死叉"                # DIF下穿DEA


class RSIStatus(Enum):
    """RSI状态枚举"""
    OVERBOUGHT = "超买"        # RSI > 70
    STRONG_BUY = "强势买入"    # 50 < RSI < 70
    NEUTRAL = "中性"          # 40 <= RSI <= 60
    WEAK = "弱势"             # 30 < RSI < 40
    OVERSOLD = "超卖"         # RSI < 30


@dataclass
class TrendAnalysisResult:
    """趋势分析结果"""
    code: str
    
    # 趋势判断
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    ma_alignment: str = ""           # 均线排列描述
    trend_strength: float = 0.0      # 趋势强度 0-100
    
    # 均线数据
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    current_price: float = 0.0
    
    # 乖离率（与 MA5 的偏离度）
    bias_ma5: float = 0.0            # (Close - MA5) / MA5 * 100
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    
    # 量能分析
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    volume_ratio_5d: float = 0.0     # 当日成交量/5日均量
    volume_ratio_3d: float = 1.0     # Today volume / 3-day average
    volume_ratio_10d: float = 1.0    # Today volume / 10-day average
    volume_ratio_20d: float = 1.0    # Today volume / 20-day average
    volume_warning: str = ""         # Mega volume warning message
    volume_exhaustion: bool = False  # Volume exhaustion flag
    volume_trend: str = ""           # 量能趋势描述

    # ATR volatility
    atr_20: float = 0.0              # 20-day Average True Range

    # 支撑压力
    support_ma5: bool = False        # MA5 是否构成支撑
    support_ma10: bool = False       # MA10 是否构成支撑
    resistance_levels: List[float] = field(default_factory=list)
    support_levels: List[float] = field(default_factory=list)

    # MACD 指标
    macd_dif: float = 0.0          # DIF 快线
    macd_dea: float = 0.0          # DEA 慢线
    macd_bar: float = 0.0           # MACD 柱状图
    macd_status: MACDStatus = MACDStatus.BULLISH
    macd_signal: str = ""            # MACD 信号描述

    # RSI 指标
    rsi_6: float = 0.0              # RSI(6) 短期
    rsi_12: float = 0.0             # RSI(12) 中期
    rsi_24: float = 0.0             # RSI(24) 长期
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    rsi_signal: str = ""              # RSI 信号描述

    # Capital flow (external source, filled by caller)
    capital_flow_score: int = 0       # 0-10, capital flow score
    main_force_signal: str = ""       # Main force activity description
    north_signal: str = ""            # North-bound capital description

    # 买入信号
    buy_signal: BuySignal = BuySignal.WAIT
    signal_score: int = 0            # 综合评分 0-100
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)

    # Market environment (broad market condition for score adjustment)
    market_environment: str = "neutral"  # 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'

    # Per-dimension scores for backtesting effectiveness analysis
    dim_trend_score: int = 0           # 0-30
    dim_bias_score: int = 0            # 0-15
    dim_volume_score: int = 0          # 0-18
    dim_support_score: int = 0         # 0-12
    dim_macd_score: int = 0            # 0-10
    dim_rsi_score: int = 0             # 0-5
    dim_capital_flow_score: int = 0    # 0-10
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'trend_status': self.trend_status.value,
            'ma_alignment': self.ma_alignment,
            'trend_strength': self.trend_strength,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'current_price': self.current_price,
            'bias_ma5': self.bias_ma5,
            'bias_ma10': self.bias_ma10,
            'bias_ma20': self.bias_ma20,
            'volume_status': self.volume_status.value,
            'volume_ratio_5d': self.volume_ratio_5d,
            'volume_ratio_3d': self.volume_ratio_3d,
            'volume_ratio_10d': self.volume_ratio_10d,
            'volume_ratio_20d': self.volume_ratio_20d,
            'volume_warning': self.volume_warning,
            'volume_exhaustion': self.volume_exhaustion,
            'volume_trend': self.volume_trend,
            'atr_20': self.atr_20,
            'support_ma5': self.support_ma5,
            'support_ma10': self.support_ma10,
            'buy_signal': self.buy_signal.value,
            'signal_score': self.signal_score,
            'signal_reasons': self.signal_reasons,
            'risk_factors': self.risk_factors,
            'macd_dif': self.macd_dif,
            'macd_dea': self.macd_dea,
            'macd_bar': self.macd_bar,
            'macd_status': self.macd_status.value,
            'macd_signal': self.macd_signal,
            'rsi_6': self.rsi_6,
            'rsi_12': self.rsi_12,
            'rsi_24': self.rsi_24,
            'rsi_status': self.rsi_status.value,
            'rsi_signal': self.rsi_signal,
            'capital_flow_score': self.capital_flow_score,
            'main_force_signal': self.main_force_signal,
            'north_signal': self.north_signal,
            'dim_trend_score': self.dim_trend_score,
            'dim_bias_score': self.dim_bias_score,
            'dim_volume_score': self.dim_volume_score,
            'dim_support_score': self.dim_support_score,
            'dim_macd_score': self.dim_macd_score,
            'dim_rsi_score': self.dim_rsi_score,
            'dim_capital_flow_score': self.dim_capital_flow_score,
            'market_environment': self.market_environment,
        }


class StockTrendAnalyzer:
    """
    股票趋势分析器

    基于用户交易理念实现：
    1. 趋势判断 - MA5>MA10>MA20 多头排列
    2. 乖离率检测 - 不追高，偏离 MA5 超过 5% 不买
    3. 量能分析 - 偏好缩量回调
    4. 买点识别 - 回踩 MA5/MA10 支撑
    5. MACD 指标 - 趋势确认和金叉死叉信号
    6. RSI 指标 - 超买超卖判断
    """
    
    # Trading parameters (BIAS thresholds computed locally in _generate_signal)
    VOLUME_SHRINK_RATIO = 0.7   # 缩量判断阈值（当日量/5日均量）
    VOLUME_HEAVY_RATIO = 1.5    # 放量判断阈值
    MA_SUPPORT_TOLERANCE = 0.02  # MA 支撑判断容忍度（2%）

    # MACD 参数（标准12/26/9）
    MACD_FAST = 12              # 快线周期
    MACD_SLOW = 26             # 慢线周期
    MACD_SIGNAL = 9             # 信号线周期

    # RSI 参数
    RSI_SHORT = 6               # 短期RSI周期
    RSI_MID = 12               # 中期RSI周期
    RSI_LONG = 24              # 长期RSI周期
    RSI_OVERBOUGHT = 70        # 超买阈值
    RSI_OVERSOLD = 30          # 超卖阈值
    
    def __init__(self):
        """初始化分析器"""
        pass
    
    def analyze(self, df: pd.DataFrame, code: str, market_environment: str = "neutral") -> TrendAnalysisResult:
        """
        Analyze stock trend.
        
        Args:
            df: DataFrame containing OHLCV data
            code: Stock code
            market_environment: Broad market condition ('strong_bull'/'bull'/'neutral'/'bear'/'strong_bear')
            
        Returns:
            TrendAnalysisResult analysis result
        """
        result = TrendAnalysisResult(code=code)
        
        if df is None or df.empty or len(df) < 20:
            logger.warning(f"{code} 数据不足，无法进行趋势分析")
            result.risk_factors.append("数据不足，无法完成分析")
            return result
        
        # 确保数据按日期排序
        df = df.sort_values('date').reset_index(drop=True)
        
        # 计算均线
        df = self._calculate_mas(df)

        # 计算 MACD 和 RSI
        df = self._calculate_macd(df)
        df = self._calculate_rsi(df)

        # 获取最新数据
        latest = df.iloc[-1]
        result.current_price = float(latest['close'])
        result.ma5 = float(latest['MA5'])
        result.ma10 = float(latest['MA10'])
        result.ma20 = float(latest['MA20'])
        result.ma60 = float(latest.get('MA60', 0))

        # 1. 趋势判断
        self._analyze_trend(df, result)

        # 2. 乖离率计算
        self._calculate_bias(result)

        # 3. 量能分析
        self._analyze_volume(df, result)

        # Fallback: compute ATR_20 locally if not present in df (database doesn't store it)
        if 'ATR_20' not in df.columns and all(c in df.columns for c in ('high', 'low', 'close')) and len(df) >= 20:
            prev_close = df['close'].shift(1)
            tr = pd.concat([
                (df['high'] - df['low']),
                (df['high'] - prev_close).abs(),
                (df['low'] - prev_close).abs()
            ], axis=1).max(axis=1)
            df['ATR_20'] = tr.rolling(window=20).mean()

        # Store ATR_20 in result (from data_provider or local fallback)
        if 'ATR_20' in df.columns and not df['ATR_20'].isna().all():
            result.atr_20 = float(df.iloc[-1]['ATR_20']) if not pd.isna(df.iloc[-1]['ATR_20']) else 0.0

        # 4. 支撑压力分析
        self._analyze_support_resistance(df, result)

        # 5. MACD 分析
        self._analyze_macd(df, result)

        # 6. RSI 分析
        self._analyze_rsi(df, result)

        # Set market environment before signal generation (affects score adjustment)
        result.market_environment = market_environment

        # 7. 生成买入信号
        self._generate_signal(df, result)

        return result
    
    def _calculate_mas(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算均线"""
        df = df.copy()
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        if len(df) >= 60:
            df['MA60'] = df['close'].rolling(window=60).mean()
        else:
            df['MA60'] = df['MA20']  # 数据不足时使用 MA20 替代
        return df

    def _calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 MACD 指标

        公式：
        - EMA(12)：12日指数移动平均
        - EMA(26)：26日指数移动平均
        - DIF = EMA(12) - EMA(26)
        - DEA = EMA(DIF, 9)
        - MACD = (DIF - DEA) * 2
        """
        df = df.copy()

        # 计算快慢线 EMA
        ema_fast = df['close'].ewm(span=self.MACD_FAST, adjust=False).mean()
        ema_slow = df['close'].ewm(span=self.MACD_SLOW, adjust=False).mean()

        # 计算快线 DIF
        df['MACD_DIF'] = ema_fast - ema_slow

        # 计算信号线 DEA
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=self.MACD_SIGNAL, adjust=False).mean()

        # 计算柱状图
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2

        return df

    def _calculate_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 RSI 指标

        公式：
        - RS = 平均上涨幅度 / 平均下跌幅度
        - RSI = 100 - (100 / (1 + RS))
        """
        df = df.copy()

        for period in [self.RSI_SHORT, self.RSI_MID, self.RSI_LONG]:
            # 计算价格变化
            delta = df['close'].diff()

            # 分离上涨和下跌
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            # 计算平均涨跌幅
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()

            # 计算 RS 和 RSI
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            # 填充 NaN 值
            rsi = rsi.fillna(50)  # 默认中性值

            # 添加到 DataFrame
            col_name = f'RSI_{period}'
            df[col_name] = rsi

        return df
    
    def _analyze_trend(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析趋势状态
        
        核心逻辑：判断均线排列和趋势强度
        """
        ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
        
        # 判断均线排列
        if ma5 > ma10 > ma20:
            # 检查间距是否在扩大（强势）
            prev = df.iloc[-5] if len(df) >= 5 else df.iloc[-1]
            prev_spread = (prev['MA5'] - prev['MA20']) / prev['MA20'] * 100 if prev['MA20'] > 0 else 0
            curr_spread = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0
            
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BULL
                result.ma_alignment = "强势多头排列，均线发散上行"
                result.trend_strength = 90
            else:
                result.trend_status = TrendStatus.BULL
                result.ma_alignment = "多头排列 MA5>MA10>MA20"
                result.trend_strength = 75
                
        elif ma5 > ma10 and ma10 <= ma20:
            result.trend_status = TrendStatus.WEAK_BULL
            result.ma_alignment = "弱势多头，MA5>MA10 但 MA10≤MA20"
            result.trend_strength = 55
            
        elif ma5 < ma10 < ma20:
            prev = df.iloc[-5] if len(df) >= 5 else df.iloc[-1]
            prev_spread = (prev['MA20'] - prev['MA5']) / prev['MA5'] * 100 if prev['MA5'] > 0 else 0
            curr_spread = (ma20 - ma5) / ma5 * 100 if ma5 > 0 else 0
            
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BEAR
                result.ma_alignment = "强势空头排列，均线发散下行"
                result.trend_strength = 10
            else:
                result.trend_status = TrendStatus.BEAR
                result.ma_alignment = "空头排列 MA5<MA10<MA20"
                result.trend_strength = 25
                
        elif ma5 < ma10 and ma10 >= ma20:
            result.trend_status = TrendStatus.WEAK_BEAR
            result.ma_alignment = "弱势空头，MA5<MA10 但 MA10≥MA20"
            result.trend_strength = 40
            
        else:
            result.trend_status = TrendStatus.CONSOLIDATION
            result.ma_alignment = "均线缠绕，趋势不明"
            result.trend_strength = 50
    
    def _calculate_bias(self, result: TrendAnalysisResult) -> None:
        """
        计算乖离率
        
        乖离率 = (现价 - 均线) / 均线 * 100%
        
        严进策略：乖离率超过 5% 不追高
        """
        price = result.current_price
        
        if result.ma5 > 0:
            result.bias_ma5 = (price - result.ma5) / result.ma5 * 100
        if result.ma10 > 0:
            result.bias_ma10 = (price - result.ma10) / result.ma10 * 100
        if result.ma20 > 0:
            result.bias_ma20 = (price - result.ma20) / result.ma20 * 100
    
    def _analyze_volume(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析量能
        
        偏好：缩量回调 > 放量上涨 > 缩量上涨 > 放量下跌
        """
        if len(df) < 5:
            return
        
        latest = df.iloc[-1]
        vol_5d_avg = df['volume'].iloc[-6:-1].mean()
        
        if vol_5d_avg > 0:
            result.volume_ratio_5d = float(latest['volume']) / vol_5d_avg
        
        # 判断价格变化
        prev_close = df.iloc[-2]['close']
        price_change = (latest['close'] - prev_close) / prev_close * 100
        
        # 量能状态判断
        if result.volume_ratio_5d >= self.VOLUME_HEAVY_RATIO:
            if price_change > 0:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                result.volume_trend = "放量上涨，多头力量强劲"
            else:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                result.volume_trend = "放量下跌，注意风险"
        elif result.volume_ratio_5d <= self.VOLUME_SHRINK_RATIO:
            if price_change > 0:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
                result.volume_trend = "缩量上涨，上攻动能不足"
            else:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
                result.volume_trend = "缩量回调，洗盘特征明显（好）"
        else:
            result.volume_status = VolumeStatus.NORMAL
            result.volume_trend = "量能正常"

        # Extended volume trend analysis
        if len(df) >= 20:
            vol_3d_avg = df['volume'].iloc[-4:-1].mean()   # Recent 3-day average
            vol_10d_avg = df['volume'].iloc[-11:-1].mean()  # 10-day average
            vol_20d_avg = df['volume'].iloc[-21:-1].mean()  # 20-day average

            today_vol = float(df.iloc[-1]['volume'])

            # Store extended volume metrics in result
            result.volume_ratio_3d = today_vol / vol_3d_avg if vol_3d_avg > 0 else 1.0
            result.volume_ratio_10d = today_vol / vol_10d_avg if vol_10d_avg > 0 else 1.0
            result.volume_ratio_20d = today_vol / vol_20d_avg if vol_20d_avg > 0 else 1.0

            # Mega volume warning (>5x 20-day average)
            if result.volume_ratio_20d >= 5.0:
                result.volume_warning = "天量预警：成交量超过20日均量5倍，注意见顶风险"

            # Volume exhaustion detection (3-day avg declining vs 10-day avg)
            if vol_3d_avg < vol_10d_avg * 0.6:
                result.volume_exhaustion = True
                result.volume_trend = result.volume_trend + "（量能衰竭，上攻乏力）"
    
    def _analyze_support_resistance(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析支撑压力位
        
        买点偏好：回踩 MA5/MA10 获得支撑
        """
        price = result.current_price
        
        # 检查是否在 MA5 附近获得支撑
        if result.ma5 > 0:
            ma5_distance = abs(price - result.ma5) / result.ma5
            if ma5_distance <= self.MA_SUPPORT_TOLERANCE and price >= result.ma5:
                result.support_ma5 = True
                result.support_levels.append(result.ma5)
        
        # 检查是否在 MA10 附近获得支撑
        if result.ma10 > 0:
            ma10_distance = abs(price - result.ma10) / result.ma10
            if ma10_distance <= self.MA_SUPPORT_TOLERANCE and price >= result.ma10:
                result.support_ma10 = True
                if result.ma10 not in result.support_levels:
                    result.support_levels.append(result.ma10)
        
        # MA20 作为重要支撑
        if result.ma20 > 0 and price >= result.ma20:
            result.support_levels.append(result.ma20)
        
        # 近期高点作为压力
        if len(df) >= 20:
            recent_high = df['high'].iloc[-20:].max()
            if recent_high > price:
                result.resistance_levels.append(recent_high)

    def _analyze_macd(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析 MACD 指标

        核心信号：
        - 零轴上金叉：最强买入信号
        - 金叉：DIF 上穿 DEA
        - 死叉：DIF 下穿 DEA
        """
        if len(df) < self.MACD_SLOW:
            result.macd_signal = "数据不足"
            return

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 获取 MACD 数据
        result.macd_dif = float(latest['MACD_DIF'])
        result.macd_dea = float(latest['MACD_DEA'])
        result.macd_bar = float(latest['MACD_BAR'])

        # 判断金叉死叉
        prev_dif_dea = prev['MACD_DIF'] - prev['MACD_DEA']
        curr_dif_dea = result.macd_dif - result.macd_dea

        # 金叉：DIF 上穿 DEA
        is_golden_cross = prev_dif_dea <= 0 and curr_dif_dea > 0

        # 死叉：DIF 下穿 DEA
        is_death_cross = prev_dif_dea >= 0 and curr_dif_dea < 0

        # 零轴穿越
        prev_zero = prev['MACD_DIF']
        curr_zero = result.macd_dif
        is_crossing_up = prev_zero <= 0 and curr_zero > 0
        is_crossing_down = prev_zero >= 0 and curr_zero < 0

        # 判断 MACD 状态
        if is_golden_cross and curr_zero > 0:
            result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
            result.macd_signal = "⭐ 零轴上金叉，强烈买入信号！"
        elif is_crossing_up:
            result.macd_status = MACDStatus.CROSSING_UP
            result.macd_signal = "⚡ DIF上穿零轴，趋势转强"
        elif is_golden_cross:
            result.macd_status = MACDStatus.GOLDEN_CROSS
            result.macd_signal = "✅ 金叉，趋势向上"
        elif is_death_cross:
            result.macd_status = MACDStatus.DEATH_CROSS
            result.macd_signal = "❌ 死叉，趋势向下"
        elif is_crossing_down:
            result.macd_status = MACDStatus.CROSSING_DOWN
            result.macd_signal = "⚠️ DIF下穿零轴，趋势转弱"
        elif result.macd_dif > 0 and result.macd_dea > 0:
            result.macd_status = MACDStatus.BULLISH
            result.macd_signal = "✓ 多头排列，持续上涨"
        elif result.macd_dif < 0 and result.macd_dea < 0:
            result.macd_status = MACDStatus.BEARISH
            result.macd_signal = "⚠ 空头排列，持续下跌"
        else:
            result.macd_status = MACDStatus.BULLISH
            result.macd_signal = " MACD 中性区域"

    def _analyze_rsi(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        分析 RSI 指标

        核心判断：
        - RSI > 70：超买，谨慎追高
        - RSI < 30：超卖，关注反弹
        - 40-60：中性区域
        """
        if len(df) < self.RSI_LONG:
            result.rsi_signal = "数据不足"
            return

        latest = df.iloc[-1]

        # 获取 RSI 数据
        result.rsi_6 = float(latest[f'RSI_{self.RSI_SHORT}'])
        result.rsi_12 = float(latest[f'RSI_{self.RSI_MID}'])
        result.rsi_24 = float(latest[f'RSI_{self.RSI_LONG}'])

        # 以中期 RSI(12) 为主进行判断
        rsi_mid = result.rsi_12

        # 判断 RSI 状态
        if rsi_mid > self.RSI_OVERBOUGHT:
            result.rsi_status = RSIStatus.OVERBOUGHT
            result.rsi_signal = f"⚠️ RSI超买({rsi_mid:.1f}>70)，短期回调风险高"
        elif rsi_mid > 60:
            result.rsi_status = RSIStatus.STRONG_BUY
            result.rsi_signal = f"✅ RSI强势({rsi_mid:.1f})，多头力量充足"
        elif rsi_mid >= 40:
            result.rsi_status = RSIStatus.NEUTRAL
            result.rsi_signal = f" RSI中性({rsi_mid:.1f})，震荡整理中"
        elif rsi_mid >= self.RSI_OVERSOLD:
            result.rsi_status = RSIStatus.WEAK
            result.rsi_signal = f"⚡ RSI弱势({rsi_mid:.1f})，关注反弹"
        else:
            # RSI < 30: check stabilization condition (RSI rising for 2 consecutive days)
            if len(df) >= 3:
                rsi_col = f'RSI_{self.RSI_MID}'
                rsi_today = float(df.iloc[-1][rsi_col])
                rsi_yesterday = float(df.iloc[-2][rsi_col])
                rsi_2days_ago = float(df.iloc[-3][rsi_col])

                is_stabilizing = (rsi_today > rsi_yesterday > rsi_2days_ago)

                if is_stabilizing:
                    result.rsi_status = RSIStatus.OVERSOLD
                    result.rsi_signal = f"⭐ RSI超卖企稳({rsi_mid:.1f}<30)，连续回升，反弹机会大"
                else:
                    result.rsi_status = RSIStatus.WEAK
                    result.rsi_signal = f"⚠️ RSI超卖({rsi_mid:.1f}<30)但未企稳，谨慎抄底"
            else:
                result.rsi_status = RSIStatus.WEAK
                result.rsi_signal = f"⚠️ RSI超卖({rsi_mid:.1f}<30)，数据不足判断企稳"

    @staticmethod
    def classify_buy_signal(score: int, trend_status: 'TrendStatus') -> 'BuySignal':
        """Unified buy signal classification based on score and trend status."""
        if score >= 75 and trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL):
            return BuySignal.STRONG_BUY
        if score >= 60 and trend_status in (
            TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL
        ):
            return BuySignal.BUY
        if score >= 45:
            return BuySignal.HOLD
        if score >= 30:
            return BuySignal.WAIT
        if trend_status in (TrendStatus.BEAR, TrendStatus.STRONG_BEAR):
            return BuySignal.STRONG_SELL
        return BuySignal.SELL

    def _generate_signal(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        Generate buy signal based on comprehensive scoring system.

        Scoring dimensions (total 100):
        - Trend (30): bullish alignment scores high
        - Bias (15): close to MA5 scores high
        - Volume (18): shrink pullback scores high
        - Support (12): MA support scores high
        - MACD (10): golden cross scores high
        - RSI (5): oversold with stabilization scores high
        - Capital flow (10): main force + north-bound inflow scores high
        """
        score = 0
        reasons = []
        risks = []

        # === 趋势评分（30分）===
        trend_scores = {
            TrendStatus.STRONG_BULL: 30,
            TrendStatus.BULL: 26,
            TrendStatus.WEAK_BULL: 18,
            TrendStatus.CONSOLIDATION: 12,
            TrendStatus.WEAK_BEAR: 8,
            TrendStatus.BEAR: 4,
            TrendStatus.STRONG_BEAR: 0,
        }
        trend_score = trend_scores.get(result.trend_status, 12)
        score += trend_score

        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            reasons.append(f"✅ {result.trend_status.value}，顺势做多")
        elif result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            risks.append(f"⚠️ {result.trend_status.value}，不宜做多")

        # === 乖离率评分（15分，强势趋势补偿）===
        score_before_bias = score
        bias = result.bias_ma5
        if bias != bias or bias is None:  # NaN or None defense
            bias = 0.0
        # Bias threshold: 5% for normal, consistent with LLM prompt "bias>5% no chasing"
        base_threshold = 5.0

        # Dynamic bias threshold based on ATR volatility
        if result.atr_20 and result.atr_20 > 0:
            current_price = result.current_price
            if current_price > 0:
                atr_pct = (result.atr_20 / current_price) * 100
                # Dynamic threshold: scale by volatility ratio
                # High volatility stocks (ATR%>3%) get wider threshold
                # Low volatility stocks (ATR%<1.5%) get tighter threshold
                volatility_factor = atr_pct / 2.0  # Normalize: ATR%=2% -> factor=1.0
                dynamic_threshold = base_threshold * max(0.7, min(1.5, volatility_factor))
                base_threshold = round(dynamic_threshold, 2)

        # Calculate trend stage metrics from df for bias threshold adjustment
        gain_20d = 0.0
        consecutive_up_days = 0
        if df is not None and len(df) >= 20:
            # 20-day cumulative gain
            close_20d_ago = df['close'].iloc[-20]
            gain_20d = (df['close'].iloc[-1] - close_20d_ago) / close_20d_ago * 100
            # Consecutive up days (from most recent)
            for i in range(len(df) - 1, 0, -1):
                if df['close'].iloc[i] > df['close'].iloc[i - 1]:
                    consecutive_up_days += 1
                else:
                    break

        # Bias threshold by trend stage (phase-based, not one-size-fits-all)
        is_strong_trend = False
        if result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL):
            if gain_20d > 30 or consecutive_up_days >= 5:
                # Acceleration phase: highest topping risk, tightest threshold
                effective_threshold = 3.5
                is_strong_trend = True
            elif gain_20d > 15:
                # Main rally phase: standard threshold
                effective_threshold = base_threshold  # 5.0
                is_strong_trend = True
            else:
                # Early stage: allow slightly more room for trend tracking
                effective_threshold = 6.0
                is_strong_trend = True
        else:
            effective_threshold = base_threshold  # 5.0 for non-bull trends

        if bias < 0:
            # Price below MA5 (pullback)
            if bias > -3:
                score += 15
                reasons.append(f"✅ 价格略低于MA5({bias:.1f}%)，回踩买点")
            elif bias > -5:
                score += 12
                reasons.append(f"✅ 价格回踩MA5({bias:.1f}%)，观察支撑")
            else:
                # Check MA20 direction to distinguish oversold bounce vs trend breakdown
                if len(df) >= 5 and 'MA20' in df.columns:
                    ma20_today = float(df.iloc[-1]['MA20'])
                    ma20_5days_ago = float(df.iloc[-5]['MA20'])

                    if ma20_today > ma20_5days_ago:
                        # MA20 still rising - oversold bounce opportunity
                        score += 11
                        reasons.append(f"⭐ 超跌回踩({bias:.1f}%)但MA20仍上行，超跌反弹机会")
                    else:
                        # MA20 declining - trend breakdown, limit score
                        score += 4
                        risks.append(f"⚠️ 乖离率大({bias:.1f}%)且MA20下行，趋势可能破坏")
                else:
                    score += 6
                    risks.append(f"⚠️ 乖离率过大({bias:.1f}%)，可能破位")
        elif bias < 2:
            score += 14
            reasons.append(f"✅ 价格贴近MA5({bias:.1f}%)，介入好时机")
        elif bias > effective_threshold:
            # Check effective_threshold BEFORE base_threshold (effective can be < base in acceleration)
            if effective_threshold <= 3.5:
                score += 0
                risks.append(
                    f"🚫 加速见顶阶段(20日涨{gain_20d:.0f}%)，乖离率{bias:.1f}%过高，严禁追高！"
                )
            elif effective_threshold >= 6.0:
                score += 3
                risks.append(
                    f"⚠️ 趋势启动期乖离率偏高({bias:.1f}%>{effective_threshold:.1f}%)，追高需设严格止损"
                )
            else:
                score += 0
                risks.append(
                    f"🚫 乖离率过高({bias:.1f}%>{effective_threshold:.1f}%)，严禁追高！"
                )
        elif bias < base_threshold:
            score += 11
            reasons.append(f"⚡ 价格略高于MA5({bias:.1f}%)，可小仓介入")
        elif bias > base_threshold and is_strong_trend:
            if effective_threshold >= 6.0:
                score += 8
                reasons.append(
                    f"✅ 趋势启动期乖离率({bias:.1f}%)在容许范围内，可轻仓追踪"
                )
            else:
                score += 3
                risks.append(
                    f"⚠️ 强势趋势中乖离率偏高({bias:.1f}%)，追高风险大，注意止盈"
                )
        else:
            score += 3
            risks.append(
                f"❌ 乖离率过高({bias:.1f}%>{base_threshold:.1f}%)，严禁追高！"
            )

        # === Volume scoring (18 pts) ===
        bias_score_local = score - score_before_bias
        volume_scores = {
            VolumeStatus.SHRINK_VOLUME_DOWN: 18,  # Shrink pullback - adjusted below by market condition
            VolumeStatus.HEAVY_VOLUME_UP: 14,     # Heavy volume up - good
            VolumeStatus.NORMAL: 11,              # Normal volume
            VolumeStatus.SHRINK_VOLUME_UP: 7,     # Shrink volume up - weak
            VolumeStatus.HEAVY_VOLUME_DOWN: 0,    # Heavy volume down - worst
        }
        # Adjust SHRINK_VOLUME_DOWN score based on market trend
        if result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            if result.trend_status in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR):
                vol_score = 0   # Bear market: shrink decline is normal trend, NOT a buy signal at all
            elif result.trend_status == TrendStatus.CONSOLIDATION:
                vol_score = 10  # Sideways: direction unclear, further discount
            else:
                vol_score = 18  # Bull market: healthy shrink pullback (washout)
        else:
            vol_score = volume_scores.get(result.volume_status, 9)

        # Penalty for volume exhaustion and abnormal volume
        if result.volume_exhaustion:
            vol_score = max(0, vol_score - 5)  # Volume exhaustion penalty
            risks.append("⚠️ 量能衰竭，上涨动力不足")
        if result.volume_warning:
            vol_score = max(0, vol_score - 15)  # Extreme volume warning (天量见顶)
            risks.append("🚫 天量警告！极可能见顶，严禁追高")

        score += vol_score

        if result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            reasons.append("✅ 缩量回调，主力洗盘")
        elif result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            risks.append("⚠️ 放量下跌，注意风险")

        # === Support scoring (12 pts) ===
        score_before_support = score
        if result.support_ma5:
            score += 7  # MA5 support more important
            reasons.append("✅ MA5支撑有效")
        if result.support_ma10:
            score += 5
            reasons.append("✅ MA10支撑有效")
        support_score_local = score - score_before_support

        # === MACD scoring (10 pts) ===
        macd_scores = {
            MACDStatus.GOLDEN_CROSS_ZERO: 10,  # Golden cross above zero - strongest
            MACDStatus.GOLDEN_CROSS: 8,        # Golden cross
            MACDStatus.CROSSING_UP: 7,         # Crossing above zero
            MACDStatus.BULLISH: 5,             # DIF>DEA>0
            MACDStatus.BEARISH: 1,             # Bearish
            MACDStatus.CROSSING_DOWN: 0,       # Crossing below zero
            MACDStatus.DEATH_CROSS: 0,         # Death cross
        }
        macd_score = macd_scores.get(result.macd_status, 3)
        score += macd_score

        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS]:
            reasons.append(f"✅ {result.macd_signal}")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN]:
            risks.append(f"⚠️ {result.macd_signal}")
        else:
            reasons.append(result.macd_signal)

        # === RSI scoring (5 pts) ===
        rsi_scores = {
            RSIStatus.OVERSOLD: 5,        # Oversold with stabilization - best
            RSIStatus.STRONG_BUY: 4,      # Strong momentum
            RSIStatus.NEUTRAL: 3,         # Neutral
            RSIStatus.WEAK: 2,            # Weak
            RSIStatus.OVERBOUGHT: 0,      # Overbought - worst
        }
        rsi_score = rsi_scores.get(result.rsi_status, 3)
        score += rsi_score

        if result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.STRONG_BUY]:
            reasons.append(f"✅ {result.rsi_signal}")
        elif result.rsi_status == RSIStatus.OVERBOUGHT:
            risks.append(f"⚠️ {result.rsi_signal}")
        else:
            reasons.append(result.rsi_signal)

        # === Capital flow scoring (10 pts) — score comes from external analysis ===
        score += result.capital_flow_score
        if result.main_force_signal:
            if result.capital_flow_score >= 6:
                reasons.append(f"✅ {result.main_force_signal}")
            elif result.capital_flow_score >= 2:
                reasons.append(f"⚡ {result.main_force_signal}")
            elif result.main_force_signal and result.main_force_signal != "资金流向数据暂不可用":
                risks.append(f"⚠️ {result.main_force_signal}")
        if result.north_signal and result.north_signal != "北向资金数据暂不可用":
            reasons.append(result.north_signal)

        # Persist per-dimension scores for backtesting effectiveness analysis
        result.dim_trend_score = trend_score
        result.dim_bias_score = bias_score_local
        result.dim_volume_score = vol_score
        result.dim_support_score = support_score_local
        result.dim_macd_score = macd_score
        result.dim_rsi_score = rsi_score
        result.dim_capital_flow_score = result.capital_flow_score

        # === Market environment adjustment (modifier, not an independent dimension) ===
        market_env = result.market_environment
        if market_env == 'strong_bear':
            score = int(score * 0.85)  # Was 0.75, adjusted to avoid missing bear market rebounds
            risks.append("⚠️ 大盘环境极弱，个股做多难度极大")
        elif market_env == 'bear':
            score = int(score * 0.90)  # Was 0.85, slightly relaxed for individual stock opportunities
            risks.append("⚠️ 大盘环境偏弱，个股做多难度加大")
        elif market_env == 'strong_bull':
            score = min(100, int(score * 1.05))
            reasons.append("✅ 大盘环境强势，顺势做多概率更高")
        # bull / neutral: no adjustment

        # === 综合判断 ===
        result.signal_score = score
        result.signal_reasons = reasons
        result.risk_factors = risks

        # Classify buy signal using unified logic
        result.buy_signal = self.classify_buy_signal(score, result.trend_status)
    
    def format_analysis(self, result: TrendAnalysisResult) -> str:
        """
        格式化分析结果为文本

        Args:
            result: 分析结果

        Returns:
            格式化的分析文本
        """
        lines = [
            f"=== {result.code} 趋势分析 ===",
            f"",
            f"📊 趋势判断: {result.trend_status.value}",
            f"   均线排列: {result.ma_alignment}",
            f"   趋势强度: {result.trend_strength}/100",
            f"",
            f"📈 均线数据:",
            f"   现价: {result.current_price:.2f}",
            f"   MA5:  {result.ma5:.2f} (乖离 {result.bias_ma5:+.2f}%)",
            f"   MA10: {result.ma10:.2f} (乖离 {result.bias_ma10:+.2f}%)",
            f"   MA20: {result.ma20:.2f} (乖离 {result.bias_ma20:+.2f}%)",
            f"",
            f"📊 量能分析: {result.volume_status.value}",
            f"   量比(vs5日): {result.volume_ratio_5d:.2f}",
            f"   量能趋势: {result.volume_trend}",
            f"",
            f"📈 MACD指标: {result.macd_status.value}",
            f"   DIF: {result.macd_dif:.4f}",
            f"   DEA: {result.macd_dea:.4f}",
            f"   MACD: {result.macd_bar:.4f}",
            f"   信号: {result.macd_signal}",
            f"",
            f"📊 RSI指标: {result.rsi_status.value}",
            f"   RSI(6): {result.rsi_6:.1f}",
            f"   RSI(12): {result.rsi_12:.1f}",
            f"   RSI(24): {result.rsi_24:.1f}",
            f"   信号: {result.rsi_signal}",
            f"",
            f"💰 资金面: {result.capital_flow_score}/10",
            f"   主力: {result.main_force_signal or 'N/A'}",
            f"   北向: {result.north_signal or 'N/A'}",
            f"",
            f"🎯 操作建议: {result.buy_signal.value}",
            f"   综合评分: {result.signal_score}/100",
        ]

        if result.signal_reasons:
            lines.append(f"")
            lines.append(f"✅ 买入理由:")
            for reason in result.signal_reasons:
                lines.append(f"   {reason}")

        if result.risk_factors:
            lines.append(f"")
            lines.append(f"⚠️ 风险因素:")
            for risk in result.risk_factors:
                lines.append(f"   {risk}")

        return "\n".join(lines)
